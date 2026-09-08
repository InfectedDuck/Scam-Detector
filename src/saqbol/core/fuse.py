"""Stage 5: fusion, combination bonuses and abstention.

Three signals arrive here and one verdict leaves. The interesting part is not
the weighted sum, it is the decision to say `unsure`.

**Why abstention exists.** A wrong "likely safe" costs a user money. A system
with one signal cannot tell a confident answer from a lucky one, so it never
abstains and its errors are silent. Here the deterministic rules and the model
are two independent judgements of the same message, and when they disagree the
honest output is that we do not know. Coverage and risk-at-coverage are then
reportable, which is what makes the abstention a result rather than a feature.

**Disagreement is measured between the rules and the model only**, not across
all three components as the first draft of the architecture had it. Retrieval
similarity is an input to the model's judgement, not a third opinion, and its
scale is not calibrated against the other two: an unrelated message still sits
at moderate cosine similarity to its nearest playbook. Including it made almost
everything abstain. Two independent judgements, one disagreement measure.

**Missing components are dropped and the weights renormalised.** The
`rules_only` leaderboard row runs with no retrieval and no model, so a fixed
divisor would cap its risk at the rule weight and it could never reach the scam
band, making the baseline unbeatable by construction and meaningless.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from saqbol.core.types import (
    RULE_SCORE_CAP,
    Band,
    Components,
    EvidenceSpan,
    IndicatorHit,
    Lang,
    LLMJudgement,
    NormalizedText,
    Stage,
    Verdict,
)


@dataclass(frozen=True)
class FusionWeights:
    """Relative trust in each signal. Fitted on the calibration split (T505),
    never on test."""

    rule: float = 0.45
    retrieval: float = 0.20
    llm: float = 0.35


@dataclass(frozen=True)
class Thresholds:
    scam: float = 0.70
    suspicious: float = 0.45
    #: Gap between the rules and the model above which neither is trusted.
    disagreement: float = 0.40
    #: Share of self-consistency samples that must agree.
    self_consistency: float = 0.60
    #: Band in which self-consistency sampling is worth paying for.
    sample_lo: float = 0.30
    sample_hi: float = 0.75


DEFAULT_WEIGHTS = FusionWeights()
DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class Combination:
    """A pair of signals that means more together than apart.

    Tokens are either a family letter ("C") or a full indicator id
    ("E1.safe_account"), so a rule can be named precisely where the family is
    too broad.
    """

    name: str
    bonus: int
    left: frozenset[str]
    right: frozenset[str]
    reason: str


#: From docs/03_INDICATORS.md, "Combination rules".
COMBINATIONS: tuple[Combination, ...] = (
    Combination(
        "authority_plus_credentials",
        20,
        frozenset("C"),
        frozenset("A"),
        "Impersonation plus a credential request is the core of the bank-security script",
    ),
    Combination(
        "authority_contradicted",
        15,
        frozenset("C"),
        frozenset("I"),
        "The claimed institution is contradicted by the contact metadata",
    ),
    Combination(
        "safe_account_under_pressure",
        15,
        frozenset({"E1.safe_account"}),
        frozenset("B"),
        "The safe-account fiction only works under pressure",
    ),
    Combination(
        "remote_access_with_authority",
        20,
        frozenset({"F1.remote_access_app", "F2.apk_attachment"}),
        frozenset("C"),
        "Remote access plus a claimed authority is near-conclusive",
    ),
    Combination(
        "delivery_link",
        10,
        frozenset("G"),
        frozenset({"C6.courier_post"}),
        "A courier claim carrying a risky link is the delivery-link pattern",
    ),
)


def _matches(hit: IndicatorHit, tokens: frozenset[str]) -> bool:
    return hit.indicator_id in tokens or hit.indicator_id[0] in tokens


def combination_bonuses(hits: Iterable[IndicatorHit]) -> list[tuple[str, int]]:
    """Which combinations fire, and for how much."""
    hits = list(hits)
    fired = []
    for combo in COMBINATIONS:
        if any(_matches(h, combo.left) for h in hits) and any(
            _matches(h, combo.right) for h in hits
        ):
            fired.append((combo.name, combo.bonus))
    return fired


def rule_score(hits: Iterable[IndicatorHit]) -> tuple[int, list[str]]:
    """Severity weights plus combination bonuses, capped.

    Returns the score and the names of the combinations that fired, so a
    verdict can explain why it scored higher than the sum of its rules.
    """
    hits = list(hits)
    base = sum(h.weight for h in hits)
    fired = combination_bonuses(hits)
    total = base + sum(bonus for _name, bonus in fired)
    return min(RULE_SCORE_CAP, total), [name for name, _bonus in fired]


def rule_norm(hits: Iterable[IndicatorHit]) -> float:
    return rule_score(hits)[0] / RULE_SCORE_CAP


def should_sample_self_consistency(
    risk: float, thresholds: Thresholds = DEFAULT_THRESHOLDS
) -> bool:
    """Whether a five-sample self-consistency check is worth its cost.

    Sampling every request would roughly triple the model spend for no gain on
    the clear cases. Only the ambiguous middle band buys anything.
    """
    return thresholds.sample_lo <= risk <= thresholds.sample_hi


def assert_spans_match(text: str, hits: Iterable[IndicatorHit]) -> None:
    """Enforce the evidence invariant before a verdict is built.

    A span that does not quote the real text is a highlight pointing at the
    wrong words, which is worse than no highlight at all. Raising here means
    the failure surfaces in CI rather than in a user's verdict card.
    """
    for hit in hits:
        for span in hit.spans:
            if text[span.start : span.end] != span.text:
                raise ValueError(
                    f"{hit.indicator_id}: span [{span.start}:{span.end}] quotes "
                    f"{span.text!r} but the text there is "
                    f"{text[span.start : span.end]!r}"
                )


def collect_evidence(
    hits: Iterable[IndicatorHit], extra: Iterable[EvidenceSpan] | None = None
) -> list[EvidenceSpan]:
    """Every span, de-duplicated by position and ordered as the reader reads.

    `extra` carries spans that came from the model's quotes rather than from a
    rule, so they appear in the card without adding to the rule score.
    """
    seen: set[tuple[int, int, str]] = set()
    spans: list[EvidenceSpan] = []
    for span in list(extra or []):
        key = (span.start, span.end, span.indicator_id)
        if key not in seen:
            seen.add(key)
            spans.append(span)
    for hit in hits:
        for span in hit.spans:
            key = (span.start, span.end, span.indicator_id)
            if key in seen:
                continue
            seen.add(key)
            spans.append(span)
    spans.sort(key=lambda s: (s.start, s.end))
    return spans


def choose_playbook(
    judgement: LLMJudgement | None, retrieval: tuple[str, float] | None
) -> tuple[str | None, float]:
    """Which script the verdict names, and how strongly.

    The model's choice wins when it made one, because it saw the message and
    retrieval only saw vocabulary. Retrieval is the fallback so a rules-only or
    refused run still names something useful.

    Shared with the pipeline, which needs the same answer before fusion in
    order to look up the advice and the hotline.
    """
    if judgement is not None and judgement.playbook_id:
        return judgement.playbook_id, judgement.confidence
    if retrieval is not None:
        return retrieval
    return None, 0.0


def band_for(risk: float, thresholds: Thresholds = DEFAULT_THRESHOLDS) -> Band:
    if risk >= thresholds.scam:
        return Band.SCAM
    if risk >= thresholds.suspicious:
        return Band.SUSPICIOUS
    return Band.LIKELY_SAFE


def fuse(
    norm: NormalizedText,
    hits: Iterable[IndicatorHit],
    *,
    retrieval: tuple[str, float] | None = None,
    judgement: LLMJudgement | None = None,
    self_consistency: float | None = None,
    extra_evidence: Iterable[EvidenceSpan] | None = None,
    action_key: str = "",
    hotline: str = "",
    stage: Stage | None = None,
    check_id: str | None = None,
    model: str = "",
    latency_ms: int = 0,
    cached: bool = False,
    weights: FusionWeights = DEFAULT_WEIGHTS,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Verdict:
    """Combine the available signals into one verdict.

    `retrieval` is `(playbook_id, similarity)`. Both it and `judgement` may be
    absent, which is how the `rules_only` baseline runs.
    """
    hits = list(hits)
    extra = list(extra_evidence or [])
    assert_spans_match(norm.text, hits)
    for span in extra:
        if norm.text[span.start : span.end] != span.text:
            raise ValueError(
                f"{span.indicator_id}: span [{span.start}:{span.end}] does not quote the message"
            )

    rules = rule_norm(hits)
    similarity = retrieval[1] if retrieval else 0.0
    confidence = judgement.confidence if judgement else 0.0

    # Only components that actually ran contribute, and the weights are
    # renormalised over them.
    parts: list[tuple[float, float]] = [(weights.rule, rules)]
    if retrieval is not None:
        parts.append((weights.retrieval, similarity))
    if judgement is not None:
        parts.append((weights.llm, confidence))

    divisor = sum(weight for weight, _value in parts) or 1.0
    risk = sum(weight * value for weight, value in parts) / divisor

    # Two independent judgements: the rules and the model. Retrieval is an
    # input to the model's judgement, not a third opinion.
    abstained: str | None = None
    if judgement is not None:
        if abs(rules - confidence) > thresholds.disagreement:
            abstained = "disagreement"
        elif self_consistency is not None and self_consistency < thresholds.self_consistency:
            abstained = "low_self_consistency"

    band = Band.UNSURE if abstained else band_for(risk, thresholds)

    playbook_id, playbook_confidence = choose_playbook(judgement, retrieval)

    return Verdict(
        check_id=check_id or uuid.uuid4().hex,
        band=band,
        risk=round(risk, 4),
        playbook_id=playbook_id,
        playbook_confidence=round(playbook_confidence, 4),
        stage=stage or (judgement.stage if judgement else None),
        indicators=hits,
        evidence=collect_evidence(hits, extra),
        action_key=action_key,
        hotline=hotline,
        language=norm.lang or Lang.UNKNOWN,
        components=Components(
            rule_norm=round(rules, 4),
            retrieval_sim=round(similarity, 4),
            llm_conf=round(confidence, 4),
            self_consistency=self_consistency,
        ),
        abstained_because=abstained,
        model=model,
        latency_ms=latency_ms,
        cached=cached,
    )
