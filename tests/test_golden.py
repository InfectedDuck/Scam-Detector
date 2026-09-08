"""T115, offline half — golden end-to-end fixtures.

The M1 gate in the build plan reads: "analyze() returns a correct verdict on 60
fixtures, no bot needed". This file is that gate. Every case in
``tests/fixtures/golden/`` goes through the pinned seam,
``saqbol.pipeline.analyze(text, locale=..., surface="api")``, on the default
analyzer with no provider key present, so what is being measured is the
deterministic rules plus lexical retrieval and nothing else. No key, no
network, no model.

Fixture shape (one YAML file per playbook, plus ``hard_negatives.yaml``)::

    playbook_id: kz.bank_security_call      # null for the hard negatives
    cases:
      - id: ru_whatsapp_call_hook_and_otp   # unique across every file
        lang_hint: ru                       # ru / kk / zh / en / null
        channel: call                       # informational only
        text: ...                           # the message as the target saw it
        expect:
          band_in: [scam]                   # the verdict band must be one of these
          playbook_id: kz.bank_security_call
          must_hit_families: [A, C]         # family = first letter of an indicator id
          must_not_hit_families: [G]
          evidence_contains: ["назовите код"]  # substrings of evidence span texts
        note: why this case exists
        xfail: reason                       # optional: the whole case is a known gap
        xfail_playbook: reason              # optional: only the playbook name is a gap

Assertion semantics:

* The band must be in ``band_in``.
* When ``band_in`` is entirely inside {scam, suspicious}, ``playbook_id`` must
  equal the expected one. When the verdict is ``likely_safe`` the playbook must
  be ``None`` (fuse.py guarantees that; this checks the guarantee reaches the
  seam).
* Every family in ``must_hit_families`` has at least one hit; none in
  ``must_not_hit_families`` does.
* Every ``evidence_contains`` substring appears in some evidence span text.
* ``normalized[span.start:span.end] == span.text`` for every evidence span.

Two flavours of expected failure, both non-strict so a closed gap shows up as
XPASS rather than as a failure:

* ``xfail`` marks the whole case. Used where a rule family has no phrase for
  the language, or where the catalogue structurally cannot see the difference
  (a pasted news headline about a scam).
* ``xfail_playbook`` softens only the playbook-name assertion, which is checked
  last. The rule assertions stay strict. Used for the Kazakh cases: the rules
  score them correctly, but the ``kz.*`` playbooks carry no Kazakh
  ``retrieval_phrases`` yet, so the lexical retriever cannot name the script.
  When those phrases land, these cases start passing without any edit here.

Run with ``-rxX`` to see the gaps listed, and ``-s`` for the language summary.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from saqbol.core.normalize import normalize
from saqbol.core.retrieval import LexicalRetriever
from saqbol.core.types import Band, Lang, Verdict
from saqbol.pipeline import analyze, default_analyzer, reset_default
from saqbol.playbooks import loader

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
HARD_NEGATIVES_FILE = "hard_negatives.yaml"

#: Anything that would turn the default analyzer into a hybrid one. Stripped for
#: the duration of this module so a developer's .env cannot make the golden
#: gate depend on a model, or on the network.
PROVIDER_ENV = ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "OPENROUTER_API_KEY", "SAQBOL_MODEL")

MIN_CASES = 60
MIN_PER_PLAYBOOK = 3
MIN_HARD_NEGATIVES = 21
MIN_KAZAKH_SCAM_CASES = 10
MIN_CHINESE_CASES = 6

FLAGGED = frozenset({Band.SCAM, Band.SUSPICIOUS})
FAMILIES = frozenset("ABCDEFGHIJ")

CASE_KEYS = frozenset(
    {"id", "lang_hint", "channel", "text", "expect", "note", "xfail", "xfail_playbook"}
)
EXPECT_KEYS = frozenset(
    {"band_in", "playbook_id", "must_hit_families", "must_not_hit_families", "evidence_contains"}
)


# ------------------------------------------------------------------ loading


@dataclass(frozen=True)
class Case:
    file: str
    id: str
    text: str
    lang_hint: Lang | None
    band_in: frozenset[Band]
    playbook_id: str | None
    must_hit: tuple[str, ...]
    must_not_hit: tuple[str, ...]
    evidence_contains: tuple[str, ...]
    xfail: str | None
    xfail_playbook: str | None

    @property
    def key(self) -> str:
        return f"{self.file}::{self.id}"

    @property
    def is_hard_negative(self) -> bool:
        return self.file == HARD_NEGATIVES_FILE

    @property
    def expects_flag(self) -> bool:
        """The case expects a scam or suspicious verdict, so a playbook must be named."""
        return bool(self.band_in) and self.band_in <= FLAGGED

    @property
    def strict(self) -> bool:
        """Nothing about this case is softened: it counts toward the gate."""
        return self.xfail is None and self.xfail_playbook is None


def _families(raw: object, where: str) -> tuple[str, ...]:
    values = tuple(str(v) for v in (raw or []))
    bad = [v for v in values if v not in FAMILIES]
    if bad:
        raise ValueError(f"{where}: unknown indicator families {bad}; expected letters A-J")
    return values


def _one_case(file: str, file_playbook: str | None, raw: dict) -> Case:
    where = f"{file}::{raw.get('id', '?')}"
    unknown = set(raw) - CASE_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
    expect = raw.get("expect") or {}
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown expect keys {sorted(unknown)}")
    if not raw.get("id") or not str(raw.get("text", "")).strip():
        raise ValueError(f"{where}: every case needs an id and a text")
    if not raw.get("note"):
        raise ValueError(f"{where}: every case needs a note saying what it tests")

    band_in = frozenset(Band(b) for b in expect.get("band_in") or [])
    if not band_in:
        raise ValueError(f"{where}: expect.band_in must list at least one band")

    playbook_id = expect.get("playbook_id", file_playbook)
    hint = raw.get("lang_hint")
    return Case(
        file=file,
        id=str(raw["id"]),
        text=str(raw["text"]),
        lang_hint=Lang(hint) if hint else None,
        band_in=band_in,
        playbook_id=playbook_id,
        must_hit=_families(expect.get("must_hit_families"), where),
        must_not_hit=_families(expect.get("must_not_hit_families"), where),
        evidence_contains=tuple(str(s) for s in (expect.get("evidence_contains") or [])),
        xfail=(str(raw["xfail"]).strip() or None) if raw.get("xfail") else None,
        xfail_playbook=(
            (str(raw["xfail_playbook"]).strip() or None) if raw.get("xfail_playbook") else None
        ),
    )


def load_cases() -> list[Case]:
    cases: list[Case] = []
    for path in sorted(GOLDEN.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        file_playbook = doc.get("playbook_id")
        if path.name != HARD_NEGATIVES_FILE and file_playbook != path.stem:
            raise ValueError(f"{path.name}: playbook_id {file_playbook!r} must match the file name")
        for raw in doc.get("cases") or []:
            cases.append(_one_case(path.name, file_playbook, raw))

    counts = Counter(c.id for c in cases)
    duplicates = sorted(i for i, n in counts.items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate case ids across the golden set: {duplicates}")
    return cases


CASES: list[Case] = load_cases()


def _param(case: Case) -> object:
    marks = [pytest.mark.xfail(reason=case.xfail, strict=False)] if case.xfail else []
    return pytest.param(case, id=case.key, marks=marks)


# ------------------------------------------------------------------ running


@pytest.fixture(scope="module", autouse=True)
def rules_only_default_analyzer():
    """The default analyzer must be the offline one for every case in this module.

    `default_analyzer()` builds a model client whenever the provider key for the
    configured model is in the environment. That is the right behaviour for the
    bot and the API, and the wrong one here: the golden gate measures the
    deterministic layer, so the keys are stripped and the analyzer rebuilt.
    """
    saved = {name: os.environ.pop(name) for name in PROVIDER_ENV if name in os.environ}
    reset_default()
    try:
        analyzer = default_analyzer()
        assert analyzer.client is None, "golden fixtures must run without a model"
        assert isinstance(analyzer.retriever, LexicalRetriever)
        yield
    finally:
        reset_default()
        os.environ.update(saved)


def run(case: Case) -> Verdict:
    return asyncio.run(analyze(case.text, locale=case.lang_hint, surface="api"))


def _describe(verdict: Verdict) -> str:
    hits = ", ".join(
        f"{h.indicator_id}[{' | '.join(s.text for s in h.spans) or 'detail'}]"
        for h in verdict.indicators
    )
    return (
        f"band={verdict.band.value} risk={verdict.risk} playbook={verdict.playbook_id} "
        f"lang={verdict.language.value} hits: {hits or 'none'}"
    )


@pytest.mark.parametrize("case", [_param(c) for c in CASES])
def test_golden_case(case: Case) -> None:
    verdict = run(case)
    normalized = normalize(case.text, lang_hint=case.lang_hint).text
    detail = _describe(verdict)

    # The evidence invariant comes first: a span that misquotes the message is
    # wrong regardless of what the verdict says.
    for span in verdict.evidence:
        assert normalized[span.start : span.end] == span.text, (
            f"{case.key}: span [{span.start}:{span.end}] quotes {span.text!r} but the "
            f"normalized text there is {normalized[span.start : span.end]!r}"
        )

    assert verdict.band in case.band_in, (
        f"{case.key}: band {verdict.band.value} not in "
        f"{sorted(b.value for b in case.band_in)}\n  {detail}"
    )

    families = {hit.indicator_id[0] for hit in verdict.indicators}
    missing = [f for f in case.must_hit if f not in families]
    assert not missing, f"{case.key}: families {missing} did not fire\n  {detail}"
    forbidden = [f for f in case.must_not_hit if f in families]
    assert not forbidden, f"{case.key}: forbidden families {forbidden} fired\n  {detail}"

    span_texts = [span.text for span in verdict.evidence]
    for needle in case.evidence_contains:
        assert any(needle in text for text in span_texts), (
            f"{case.key}: no evidence span contains {needle!r}; spans: {span_texts}"
        )

    if verdict.band is Band.LIKELY_SAFE:
        assert verdict.playbook_id is None, (
            f"{case.key}: a likely_safe verdict must not name a playbook\n  {detail}"
        )

    # Checked last, and the only assertion `xfail_playbook` may soften.
    if case.expects_flag and verdict.playbook_id != case.playbook_id:
        message = (
            f"{case.key}: playbook {verdict.playbook_id!r} != expected "
            f"{case.playbook_id!r}\n  {detail}"
        )
        if case.xfail_playbook:
            pytest.xfail(f"{case.xfail_playbook}\n{message}")
        pytest.fail(message)


# ---------------------------------------------------------------- the corpus


def test_golden_playbook_ids_exist() -> None:
    """Every playbook named anywhere in the golden set is a loaded playbook."""
    playbooks = loader.load_all()
    assert playbooks, "no playbooks loaded"
    for case in CASES:
        if case.playbook_id is not None:
            assert case.playbook_id in playbooks, (
                f"{case.key} names unknown playbook {case.playbook_id!r}"
            )
    files = {path.stem for path in GOLDEN.glob("*.yaml")} - {Path(HARD_NEGATIVES_FILE).stem}
    assert files <= set(playbooks), (
        f"golden files without a playbook: {sorted(files - set(playbooks))}"
    )


def test_golden_corpus_shape() -> None:
    """The M1 gate: enough cases, spread across every playbook and language."""
    playbooks = loader.load_all()
    scams = [c for c in CASES if not c.is_hard_negative]
    negatives = [c for c in CASES if c.is_hard_negative]

    per_playbook = Counter(c.playbook_id for c in scams)
    per_hint = Counter(c.lang_hint.value if c.lang_hint else "none" for c in CASES)
    per_hint_scam = Counter(c.lang_hint.value if c.lang_hint else "none" for c in scams)
    strict = [c for c in CASES if c.strict]
    whole_gaps = [c for c in CASES if c.xfail]
    playbook_gaps = [c for c in CASES if c.xfail_playbook]

    lines = [
        "",
        f"golden cases: {len(CASES)} "
        f"({len(scams)} scam, {len(negatives)} hard negative; {len(strict)} strict, "
        f"{len(whole_gaps)} xfail, {len(playbook_gaps)} xfail_playbook)",
        "per playbook: " + ", ".join(f"{pid}={per_playbook[pid]}" for pid in sorted(playbooks)),
        "per language (declared lang_hint, all cases): "
        + ", ".join(f"{lang}={n}" for lang, n in sorted(per_hint.items())),
        "per language (declared lang_hint, scam cases): "
        + ", ".join(f"{lang}={n}" for lang, n in sorted(per_hint_scam.items())),
    ]
    print("\n".join(lines))

    assert len(CASES) >= MIN_CASES
    assert len(strict) >= MIN_CASES, (
        f"the gate must be met by cases with no xfail of either kind: {len(strict)} < {MIN_CASES}"
    )
    assert len(negatives) >= MIN_HARD_NEGATIVES
    for pid in playbooks:
        assert per_playbook[pid] >= MIN_PER_PLAYBOOK, f"{pid} has {per_playbook[pid]} cases"
    assert per_hint_scam[Lang.KK.value] >= MIN_KAZAKH_SCAM_CASES
    assert per_hint[Lang.ZH.value] >= MIN_CHINESE_CASES

    kazakh_playbooks = {c.playbook_id for c in scams if c.lang_hint is Lang.KK}
    kz_playbooks = {pid for pid in playbooks if pid.startswith("kz.")}
    assert kz_playbooks <= kazakh_playbooks, (
        f"kz playbooks without a Kazakh case: {sorted(kz_playbooks - kazakh_playbooks)}"
    )
    assert any(
        c.lang_hint is Lang.ZH for c in scams if c.playbook_id and c.playbook_id.startswith("cn.")
    )


def test_hard_negatives_expect_no_playbook() -> None:
    """A hard negative never expects a script, and never accepts the scam band."""
    for case in CASES:
        if case.is_hard_negative:
            assert case.playbook_id is None, case.key
            assert Band.SCAM not in case.band_in, case.key
            assert Band.LIKELY_SAFE in case.band_in, case.key
