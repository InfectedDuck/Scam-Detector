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

/** Exact successful response from `POST /api/v1/analyze`.
 *
 * Evidence offsets index `normalized_text`, not the raw submitted message.
 * The backend declares this field as required in `AnalyzeOut` so a web client
 * can render evidence without re-implementing the Python normalizer.
 */
export interface AnalyzeOut extends Verdict {
  normalized_text: string;
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

/**
 * POST /api/v1/analyze, 422 — screenshot outcomes. `image_not_supported` when
 * the API has no vision provider configured; `image_no_text` when the
 * screenshot held no readable message text (and nothing was typed alongside).
 * A 502 `image_unreadable` means the vision provider failed on the image.
 */
export interface ImageNotSupported {
  error: "image_not_supported" | "image_no_text" | "invalid_image";
}

/** GET /api/v1/stats — one row of `stats_daily`. Counts only, never text. */
export interface StatsDay {
  /** "YYYY-MM-DD" */
  day: string;
  checks: number;
  unique_actors: number;
  scam_count: number;
  unsure_count: number;
  top_playbook: string | null;
}

/** GET /api/v1/stats, 200 (docs/02_DATA_CONTRACTS.md §5). */
export interface Stats {
  total_checks: number;
  /**
   * The SUM of each day's distinct actors, so a device that returns on another
   * day is counted again. The page says so; do not label this "users".
   */
  unique_users: number;
  /** 0..1 */
  scam_share: number;
  /** The last 30 days, ascending. */
  days: StatsDay[];
  /** ISO 8601 */
  updated_at: string;
}
