"""Core domain types.

Mirrors docs/02_DATA_CONTRACTS.md section 1. If you change anything here,
change that document in the same commit.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Lang(StrEnum):
    RU = "ru"
    KK = "kk"
    EN = "en"
    ZH = "zh"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Band(StrEnum):
    SCAM = "scam"
    SUSPICIOUS = "suspicious"
    UNSURE = "unsure"
    LIKELY_SAFE = "likely_safe"


class Stage(StrEnum):
    """Where the victim is inside the script. Only set for multi-message threads."""

    CONTACT = "contact"
    HOOK = "hook"
    TRUST = "trust"
    PRESSURE = "pressure"
    EXTRACTION = "extraction"
    CASHOUT = "cashout"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_WEIGHT: dict[Severity, int] = {
    Severity.CRITICAL: 40,
    Severity.HIGH: 25,
    Severity.MEDIUM: 12,
    Severity.LOW: 5,
}

#: Rule score is capped here before normalising to [0, 1].
RULE_SCORE_CAP = 100


class EvidenceSpan(BaseModel):
    """Character offsets into the NORMALIZED text.

    Invariant, asserted in fuse.py and in tests:
        normalized[span.start : span.end] == span.text
    """

    start: int
    end: int
    text: str
    indicator_id: str

    def matches(self, normalized: str) -> bool:
        return normalized[self.start : self.end] == self.text


class IndicatorHit(BaseModel):
    indicator_id: str
    severity: Severity
    spans: list[EvidenceSpan] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)

    @property
    def weight(self) -> int:
        return SEVERITY_WEIGHT[self.severity]


class Entities(BaseModel):
    urls: list[str] = Field(default_factory=list)
    resolved_urls: dict[str, str] = Field(default_factory=dict)
    phones: list[str] = Field(default_factory=list)
    short_codes: list[str] = Field(default_factory=list)
    card_numbers: list[str] = Field(default_factory=list)
    iins: list[str] = Field(default_factory=list)
    amounts: list[str] = Field(default_factory=list)
    crypto_addresses: list[str] = Field(default_factory=list)
    app_names: list[str] = Field(default_factory=list)
    has_apk: bool = False
    qr_payloads: list[str] = Field(default_factory=list)


class NormalizedText(BaseModel):
    """Output of stage 0. All downstream offsets refer to `text`."""

    text: str
    original: str
    lang: Lang
    lang_confidence: float
    is_code_switched: bool = False
    script_ratios: dict[str, float] = Field(default_factory=dict)
    #: Tokens mixing two or more scripts, e.g. Cyrillic "а" inside a Latin word.
    #: Strong homograph-attack signal, consumed by indicator G1.
    mixed_script_tokens: list[str] = Field(default_factory=list)


class AnalysisInput(BaseModel):
    text: str | None = None
    image_b64: str | None = None
    surface: str = "api"
    lang_hint: Lang | None = None
    consent_dataset: bool = False
    thread: list[str] = Field(default_factory=list)


class Components(BaseModel):
    rule_norm: float
    retrieval_sim: float
    llm_conf: float
    self_consistency: float | None = None

    def values(self) -> list[float]:
        return [self.rule_norm, self.retrieval_sim, self.llm_conf]


class Verdict(BaseModel):
    check_id: str
    band: Band
    risk: float
    playbook_id: str | None = None
    playbook_confidence: float = 0.0
    stage: Stage | None = None
    indicators: list[IndicatorHit] = Field(default_factory=list)
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    action_key: str = ""
    hotline: str = ""
    language: Lang = Lang.UNKNOWN
    components: Components
    abstained_because: str | None = None
    model: str = ""
    latency_ms: int = 0
    cached: bool = False


class LLMJudgement(BaseModel):
    """Forced output schema for the judge node.

    Never trusted as-is. See docs/02_DATA_CONTRACTS.md section 2 for the three
    post-processing rules applied in graph.py.
    """

    playbook_id: str | None = None
    confidence: float = 0.0
    stage: Stage | None = None
    evidence_quotes: list[str] = Field(default_factory=list)
    reasoning: str = ""
