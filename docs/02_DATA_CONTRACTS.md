# SaqBol — Data contracts

Every schema in one place. Lock these before writing code. Changing a contract mid-build is the main source of wasted hours.

---

## 1. Core domain types

```python
# src/saqbol/core/types.py
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, Field


class Lang(StrEnum):
    RU = "ru"; KK = "kk"; EN = "en"; ZH = "zh"; MIXED = "mixed"; UNKNOWN = "unknown"


class Band(StrEnum):
    SCAM = "scam"
    SUSPICIOUS = "suspicious"
    UNSURE = "unsure"
    LIKELY_SAFE = "likely_safe"


class Stage(StrEnum):
    """Where the victim is inside the script. Only set for multi-message threads."""
    CONTACT    = "contact"      # first approach
    HOOK       = "hook"         # the story that creates attention
    TRUST      = "trust"        # credentials, fake documents, transfer to "officer"
    PRESSURE   = "pressure"     # urgency, threat, secrecy
    EXTRACTION = "extraction"   # asking for code / transfer / install
    CASHOUT    = "cashout"      # money already moving


class Severity(StrEnum):
    CRITICAL = "critical"   # weight 40
    HIGH     = "high"       # weight 25
    MEDIUM   = "medium"     # weight 12
    LOW      = "low"        # weight 5


SEVERITY_WEIGHT = {
    Severity.CRITICAL: 40, Severity.HIGH: 25,
    Severity.MEDIUM: 12,   Severity.LOW: 5,
}


class EvidenceSpan(BaseModel):
    """Character offsets into the NORMALIZED text. Must be verified to match."""
    start: int
    end: int
    text: str
    indicator_id: str          # e.g. "A1.otp_request"


class IndicatorHit(BaseModel):
    indicator_id: str
    severity: Severity
    spans: list[EvidenceSpan] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)   # e.g. {"lookalike_of": "kaspi.kz", "distance": 1}


class Entities(BaseModel):
    urls: list[str] = []
    resolved_urls: dict[str, str] = {}     # short → final
    phones: list[str] = []
    short_codes: list[str] = []            # 1414, 96110, bank codes
    card_numbers: list[str] = []           # masked immediately after detection
    iins: list[str] = []                   # KZ national ID, masked
    amounts: list[str] = []
    crypto_addresses: list[str] = []
    app_names: list[str] = []              # AnyDesk, TeamViewer, ...
    has_apk: bool = False
    qr_payloads: list[str] = []


class AnalysisInput(BaseModel):
    text: str | None = None
    image_b64: str | None = None
    surface: str                            # "telegram" | "web" | "api"
    lang_hint: Lang | None = None
    consent_dataset: bool = False
    thread: list[str] = []                  # prior messages, oldest first


class Components(BaseModel):
    rule_norm: float
    retrieval_sim: float
    llm_conf: float
    self_consistency: float | None = None


class Verdict(BaseModel):
    check_id: str
    band: Band
    risk: float                             # 0..1
    playbook_id: str | None
    playbook_confidence: float
    stage: Stage | None = None
    indicators: list[IndicatorHit] = []
    evidence: list[EvidenceSpan] = []
    action_key: str                         # i18n key, e.g. "action.hang_up_call_bank"
    hotline: str                            # "1414" | "96110" | bank number
    language: Lang
    components: Components
    abstained_because: str | None = None    # "disagreement" | "low_self_consistency"
    model: str
    latency_ms: int
    cached: bool = False
```

### Invariant to unit-test

Every `EvidenceSpan` must satisfy `normalized_text[span.start:span.end] == span.text`. Assert this in `fuse.py` and raise in tests. This single check is what makes the explainability claim real rather than decorative.

---

## 2. LLM structured output

The LLM never returns prose. It returns exactly this, enforced by pydantic through the provider's JSON-schema mode.

```python
class LLMJudgement(BaseModel):
    playbook_id: str | None      # MUST be one of the retrieved candidate IDs, or null
    confidence: float            # 0..1
    stage: Stage | None
    evidence_quotes: list[str]   # verbatim substrings of the input; resolved to spans afterwards
    reasoning: str               # <= 300 chars, for the design doc and error analysis, not shown to users
```

Rules enforced in code after the call, not trusted from the model:

1. `playbook_id` not in candidates → set to `None`, log a `schema_violation` metric.
2. Every `evidence_quotes` entry that is not a substring of the normalized input is **dropped**. If more than half are dropped, halve `confidence`.
3. The user-facing action text comes from the playbook YAML, never from the model. The model picks the playbook; the playbook supplies the advice.

Rule 3 is a safety property. A hallucinated phone number in scam advice is the worst failure this product can have.

---

## 3. Playbook YAML

One file per playbook in `src/saqbol/playbooks/data/`. Validated by `schema.py` at load time and in CI.

```yaml
# src/saqbol/playbooks/data/kz.bank_security_call.yaml
id: kz.bank_security_call
version: 1
region: KZ
family: authority_impersonation

name:
  ru: "Звонок «службы безопасности банка»"
  kk: "«Банк қауіпсіздік қызметінен» қоңырау"
  en: "Fake bank security service call"
  zh: "冒充银行安全部门来电"

summary:
  ru: "Звонящий представляется сотрудником банка и говорит, что с вашего счёта пытаются списать деньги."
  kk: "..."      # translated in week 2 by co-annotators
  en: "..."
  zh: "..."

# Phrases used ONLY for embedding/retrieval. Not shown to users.
retrieval_phrases:
  - "служба безопасности банка"
  - "с вашего счёта пытаются списать деньги"
  - "переведите средства на безопасный счёт"
  - "назовите код из СМС"
  - "не кладите трубку, я вас соединю со следователем"
  - "банк қауіпсіздік қызметі"

# Which indicators typically co-occur. Used for a consistency check, not for scoring.
expected_indicators: [C1.bank_security, A1.otp_request, E1.safe_account, B1.urgency, J1.secrecy]

stages:
  contact:    { ru: "Входящий звонок или WhatsApp-звонок с незнакомого номера." }
  hook:       { ru: "«С вашего счёта пытаются списать сумму»." }
  trust:      { ru: "Называет ваше ФИО, переключает на «следователя», присылает «удостоверение»." }
  pressure:   { ru: "«Не кладите трубку», «это тайна следствия», «никому не говорите»." }
  extraction: { ru: "Просит код из СМС, полные данные карты, или перевод на «безопасный счёт»." }
  cashout:    { ru: "Деньги переведены или оформлен кредит." }

red_flags:
  ru:
    - "Настоящий банк никогда не просит код из СМС."
    - "«Безопасного счёта» не существует."
    - "Просьба не класть трубку — это способ помешать вам перезвонить."
  kk: ["..."]

action:
  key: action.hang_up_call_bank
  ru: "Положите трубку. Перезвоните в банк по номеру на обороте карты — не по тому, что вам назвали."
  kk: "..."
hotline: "1414"                 # eGov; bank-specific numbers listed in `hotlines`
hotlines:
  - { name: "Kaspi", number: "+7 727 330 00 00" }
  - { name: "eGov", number: "1414" }
  - { name: "Полиция", number: "102" }

sources:
  - https://www.gov.kz/...          # official warning
  - https://...                     # press article
```

Loader requirements:

- Fail loudly on a missing required field. A silently half-loaded playbook produces bad advice.
- `id` must match the filename.
- Embed `summary.ru + retrieval_phrases` with `multilingual-e5-small`, store in `playbooks.embedding`.
- Bump `version` whenever text changes; the verdict records which version answered.

---

## 4. Database schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per analysis. text is purged after 30 days; hash is kept.
CREATE TABLE checks (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    surface         TEXT NOT NULL,             -- telegram | web | api
    input_type      TEXT NOT NULL,             -- text | image | forward
    lang            TEXT NOT NULL,
    text_sha256     TEXT NOT NULL,
    text_scrubbed   TEXT,                      -- NULL after retention purge
    verdict         JSONB NOT NULL,
    playbook_id     TEXT,
    band            TEXT NOT NULL,
    risk            REAL NOT NULL,
    model           TEXT NOT NULL,
    latency_ms      INTEGER NOT NULL,
    cost_usd        NUMERIC(10,6),
    consent_dataset BOOLEAN NOT NULL DEFAULT FALSE,
    actor_hash      TEXT NOT NULL              -- HMAC(tg_user_id | ip), never the raw value
);
CREATE INDEX ON checks (created_at);
CREATE INDEX ON checks (text_sha256);
CREATE INDEX ON checks (playbook_id);

-- "Was this right?" votes. Feeds the review queue, never the dataset directly.
CREATE TABLE feedback (
    id          BIGSERIAL PRIMARY KEY,
    check_id    UUID REFERENCES checks(id) ON DELETE CASCADE,
    was_correct BOOLEAN,
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Human-reviewed queue on the way into KazScam.
CREATE TABLE dataset_candidates (
    id             BIGSERIAL PRIMARY KEY,
    check_id       UUID REFERENCES checks(id),
    text_scrubbed  TEXT NOT NULL,
    source         TEXT NOT NULL,      -- press | donated | synthetic
    source_url     TEXT,               -- required when source = 'press'
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    reviewer       TEXT,
    reviewed_at    TIMESTAMPTZ,
    reject_reason  TEXT
);

CREATE TABLE playbooks (
    id         TEXT PRIMARY KEY,
    version    INTEGER NOT NULL,
    content    JSONB NOT NULL,
    embedding  VECTOR(384) NOT NULL
);
CREATE INDEX ON playbooks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE rate_limits (
    actor_hash TEXT NOT NULL,
    day        DATE NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (actor_hash, day)
);

-- Materialized nightly for the public stats page. Never exposes text.
CREATE TABLE stats_daily (
    day             DATE PRIMARY KEY,
    checks          INTEGER NOT NULL,
    unique_actors   INTEGER NOT NULL,
    scam_count      INTEGER NOT NULL,
    unsure_count    INTEGER NOT NULL,
    top_playbook    TEXT
);
```

`actor_hash` is `HMAC-SHA256(secret, telegram_user_id or client_ip)`. Raw identifiers never touch the disk. Say this in PRIVACY.md.

---

## 5. HTTP API

```
POST /api/v1/analyze
  body: AnalysisInput
  200:  Verdict
  429:  {"error": "rate_limited", "retry_after": 3600}
  413:  image over 5 MB

POST /api/v1/feedback
  body: {check_id: str, was_correct: bool, comment: str | null}
  204

GET  /api/v1/stats
  200: {total_checks, unique_users, scam_share, days: [...], updated_at}

GET  /api/v1/playbooks            # public library, powers SEO pages
GET  /api/v1/playbooks/{id}

GET  /healthz                     # 200 with db + llm reachability booleans
```

Limits: 10 checks per `actor_hash` per day, 5 MB image, 8000 characters of text. Cloudflare Turnstile on the web form after the third check in a session.

---

## 6. KazScam dataset row

Released on Hugging Face as JSONL, one file per split.

```json
{
  "id": "kazscam-000417",
  "text": "Здравствуйте, это служба безопасности Kaspi. С вашего счёта пытаются списать 480 000 тг...",
  "label": "scam",
  "playbook_id": "kz.bank_security_call",
  "stage": "hook",
  "lang": "ru",
  "lang_secondary": null,
  "is_code_switched": false,
  "channel": "whatsapp",
  "source": "press",
  "source_url": "https://...",
  "collected_at": "2026-09-19",
  "annotator_a": "scam/kz.bank_security_call",
  "annotator_b": "scam/kz.bank_security_call",
  "adjudicated": false,
  "hard_negative": false,
  "scrub_applied": ["phone", "amount_kept", "name"]
}
```

Label set: `scam` | `legit` | `ambiguous`. Playbook ID only when `label == scam`.

### Splits

| Split | Contents | Used for |
|---|---|---|
| `train_synthetic` | LLM paraphrases of press rows | Training and prompt development only. **Never** in a reported metric. |
| `calibration` | 150 rows, stratified | Tuning fusion weights and abstention thresholds. Reported separately. |
| `test_press` | Rows from public warnings and press | Headline leaderboard number |
| `test_donated` | Consented user submissions | Held out. Second table. Shows real-world drift. |

Hard negatives live in `test_press` and `test_donated`, flagged by `hard_negative: true`. They are legitimate messages that look like scams: real 1414 codes, Kazpost tracking SMS, Kaspi promotions, Halyk login alerts, genuine OLX buyer chats. False-positive rate on this subset is a headline metric because a tool that flags a real bank SMS gets uninstalled.

**Leakage rules**, checked by a test in CI:

- No `text_sha256` appears in two splits.
- No synthetic row shares a source row with any test row.
- The calibration split is disjoint from every test split.

---

## 7. Eval results format

`eval/results/results.json`, committed so the leaderboard is reproducible and diffable.

```json
{
  "run_id": "2026-09-26T14:02Z",
  "dataset_version": "kazscam-v0.1",
  "n_bootstrap": 10000,
  "rows": [
    {
      "system": "hybrid",
      "model": "deepseek-v3",
      "split": "test_press",
      "lang": "kk",
      "ablation": "none",
      "macro_f1": 0.781,
      "ci95": [0.724, 0.833],
      "n": 148,
      "fpr_hard_negative": 0.061,
      "abstain_rate": 0.093
    }
  ]
}
```

`leaderboard.md` is generated from this file, never hand-edited. Systems: `rules_only`, `llm_zeroshot`, `hybrid`. Ablations: `none`, `translated`, `cue_masked`, `no_playbook_context`.

State in the README: no "X beats Y" claim without non-overlapping confidence intervals.
