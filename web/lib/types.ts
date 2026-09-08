/**
 * TypeScript mirror of `src/saqbol/core/types.py` (docs/02_DATA_CONTRACTS.md §1),
 * as it appears on the wire from `POST /api/v1/analyze` (§5).
 *
 * pydantic serialises with the declared field names, so everything here is
 * snake_case on purpose. If a contract changes, change it in the doc first,
 * then here.
 */

export type Lang = "ru" | "kk" | "en" | "zh" | "mixed" | "unknown";

export type Band = "scam" | "suspicious" | "unsure" | "likely_safe";

export type Stage =
  | "contact"
  | "hook"
  | "trust"
  | "pressure"
  | "extraction"
  | "cashout";

export type Severity = "critical" | "high" | "medium" | "low";

/** docs/02_DATA_CONTRACTS.md §1 — SEVERITY_WEIGHT */
export const SEVERITY_WEIGHT: Record<Severity, number> = {
  critical: 40,
  high: 25,
  medium: 12,
  low: 5,
};

/** Ordered weakest → strongest, for picking the dominant severity of an overlap. */
export const SEVERITY_ORDER: Severity[] = ["low", "medium", "high", "critical"];

export interface EvidenceSpan {
  /** Offset into the NORMALIZED text, in Unicode code points (Python `str` indices). */
  start: number;
  /** Exclusive end offset, same units. */
  end: number;
  /** The substring itself. Invariant: normalized[start:end] === text. */
  text: string;
  /** e.g. "A1.otp_request" */
  indicator_id: string;
}

export interface IndicatorHit {
  indicator_id: string;
  severity: Severity;
  spans: EvidenceSpan[];
  detail: Record<string, unknown>;
}

export interface Components {
  rule_norm: number;
  retrieval_sim: number;
  llm_conf: number;
  self_consistency: number | null;
}

export interface Verdict {
  check_id: string;
  band: Band;
  /** 0..1 */
  risk: number;
  playbook_id: string | null;
  playbook_confidence: number;
  stage: Stage | null;
  indicators: IndicatorHit[];
  evidence: EvidenceSpan[];
  /** i18n key, e.g. "action.hang_up_call_bank" */
  action_key: string;
  /** "1414" | "96110" | a bank number */
  hotline: string;
  language: Lang;
  components: Components;
  abstained_because: "disagreement" | "low_self_consistency" | null;
  model: string;
  latency_ms: number;
  cached: boolean;
}

/** docs/02_DATA_CONTRACTS.md §1 — request body for POST /api/v1/analyze */
export interface AnalysisInput {
  text?: string | null;
  image_b64?: string | null;
  surface: "telegram" | "web" | "api";
  lang_hint?: Lang | null;
  consent_dataset?: boolean;
  thread?: string[];
}

/**
 * What the UI actually needs to render.
 *
 * CONTRACT GAP: evidence offsets index the normalized string, but `Verdict`
 * carries no normalized text, so a client cannot anchor a span without
 * re-deriving it. Until the backend adds a field, `fetchVerdict` normalises
 * locally (lib/normalize.ts) and every span is verified before it is drawn.
 * See lib/api.ts.
 */
export interface AnalyzeResult {
  verdict: Verdict;
  normalized_text: string;
}

/** POST /api/v1/analyze, 429 */
export interface RateLimited {
  error: "rate_limited";
  retry_after: number;
}

/** Limits from docs/02_DATA_CONTRACTS.md §5. */
export const MAX_TEXT_CHARS = 8000;

/** Screenshot upload: the formats the form accepts and the size it refuses above. */
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export type ImageType = (typeof IMAGE_TYPES)[number];
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

/** POST /api/v1/analyze, 422 — the backend cannot read screenshots yet. */
export interface ImageNotSupported {
  error: "image_not_supported";
}
