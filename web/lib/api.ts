import "server-only";

import type { AnalysisInput, AnalyzeResult, Band, Verdict } from "./types";
import { SEVERITY_WEIGHT } from "./types";
import { normalize } from "./normalize";
import { FIXTURES, SAMPLES } from "@/mock";

/**
 * The one seam between this app and the backend.
 *
 * Nothing else in the app knows whether a verdict came from Python or from
 * web/mock. When `SAQBOL_API_BASE` is set, this posts to
 * `POST /api/v1/analyze` (docs/02_DATA_CONTRACTS.md section 5) and the mock
 * path below stops running. Until then it serves fixtures.
 *
 * Deliberately server-only: the API base, and eventually any key, must not
 * reach the browser, and keeping the fixtures out of the client bundle keeps
 * first load small.
 */

const API_BASE = process.env.SAQBOL_API_BASE;

export const USING_MOCK = !API_BASE;

export class ApiError extends Error {
  constructor(
    readonly code: "rate_limited" | "too_large" | "failed",
    readonly retryAfter?: number,
  ) {
    super(code);
    this.name = "ApiError";
  }
}

export async function fetchVerdict(input: AnalysisInput): Promise<AnalyzeResult> {
  const normalized = normalize(input.text ?? "");

  if (!API_BASE) return mockVerdict(normalized);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/v1/analyze`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
      cache: "no-store",
    });
  } catch {
    throw new ApiError("failed");
  }

  if (response.status === 429) {
    const body = (await response.json().catch(() => null)) as { retry_after?: number } | null;
    throw new ApiError("rate_limited", body?.retry_after);
  }
  if (response.status === 413) throw new ApiError("too_large");
  if (!response.ok) throw new ApiError("failed");

  const verdict = (await response.json()) as Verdict & { normalized_text?: string };

  return {
    verdict,
    /**
     * CONTRACT GAP, see lib/types.ts. `Verdict` publishes offsets into the
     * normalized text but not the normalized text itself, so the only way to
     * anchor a span today is to re-derive it here. `normalized_text` is read
     * first so that adding the field to the pydantic model is all it takes to
     * make this exact; until then lib/highlight.ts verifies every span and
     * re-anchors the ones that do not line up.
     */
    normalized_text: verdict.normalized_text ?? normalized,
  };
}

// --------------------------------------------------------------------------
// MOCK ONLY. None of the following runs once SAQBOL_API_BASE is set.
// --------------------------------------------------------------------------

/**
 * Serve a fixture for arbitrary pasted text.
 *
 * A mock that returned one fixture unconditionally would draw its highlights
 * over whatever characters happened to sit at those offsets, which is precisely
 * the failure the real card is built to avoid. So instead: pick the fixture
 * whose evidence phrases actually occur in the pasted text, re-anchor those
 * phrases to where they really are, drop the rest, and re-run the stage-5
 * arithmetic from docs/01_ARCHITECTURE.md section 3 over what survived. The
 * card then tells the truth about its own inputs even though the analysis
 * behind them is canned.
 */
function mockVerdict(normalized: string): AnalyzeResult {
  // An untouched sample keeps its generated offsets, which is the pristine
  // path: every span anchors by offset, nothing is recovered by search.
  const exact = SAMPLES.find((s) => normalize(s.text) === normalized);
  if (exact) {
    return { verdict: FIXTURES[exact.id], normalized_text: normalized };
  }

  if (normalized.length === 0) {
    return { verdict: FIXTURES.real_notification, normalized_text: normalized };
  }

  let best: { id: string; hits: number } = { id: "real_notification", hits: 0 };
  for (const [id, verdict] of Object.entries(FIXTURES)) {
    const hits = verdict.evidence.filter((span) => findFolded(normalized, span.text)).length;
    if (hits > best.hits) best = { id, hits };
  }
  if (best.hits === 0) {
    return { verdict: FIXTURES.real_notification, normalized_text: normalized };
  }

  return { verdict: reanchor(FIXTURES[best.id], normalized), normalized_text: normalized };
}

/**
 * Case-insensitive search that returns the text's own spelling of the match, so
 * a pasted "Назовите код" still lands on the fixture's "назовите код" while the
 * span keeps satisfying normalized[start:end] == text.
 *
 * Case folding is done per code point and the folded arrays are compared
 * element-wise, so a character whose lowercase form is longer (rare, and not
 * in the scripts this handles) can shift the match but cannot corrupt the
 * offsets: the slice is always taken from the original text.
 */
function findFolded(
  normalized: string,
  phrase: string,
): { start: number; end: number; text: string } | null {
  const cps = Array.from(normalized);
  const folded = cps.map((c) => c.toLowerCase());
  const target = Array.from(phrase).map((c) => c.toLowerCase());
  if (target.length === 0) return null;
  outer: for (let i = 0; i + target.length <= folded.length; i++) {
    for (let j = 0; j < target.length; j++) {
      if (folded[i + j] !== target[j]) continue outer;
    }
    return { start: i, end: i + target.length, text: cps.slice(i, i + target.length).join("") };
  }
  return null;
}

/** Keep only the spans present in `normalized`, then rescore. */
function reanchor(fixture: Verdict, normalized: string): Verdict {
  const indicators = fixture.indicators
    .map((hit) => ({
      ...hit,
      spans: hit.spans.flatMap((span) => {
        const found = findFolded(normalized, span.text);
        return found ? [{ ...span, ...found }] : [];
      }),
    }))
    .filter((hit) => hit.spans.length > 0);

  const evidence = indicators
    .flatMap((hit) => hit.spans)
    .sort((a, b) => a.start - b.start || b.end - a.end);

  const weightSum = indicators.reduce(
    (n, hit) => n + SEVERITY_WEIGHT[hit.severity] * hit.spans.length,
    0,
  );
  const rule_norm = Math.min(1, weightSum / 100);

  // Fewer indicators fired than the fixture assumed, so pull the model's
  // confidence towards the rules rather than leaving a stale number on screen.
  const retained = evidence.length / Math.max(1, fixture.evidence.length);
  const llm_conf = round2(fixture.components.llm_conf * (0.55 + 0.45 * retained));
  const { retrieval_sim } = fixture.components;

  const risk = 0.45 * rule_norm + 0.2 * retrieval_sim + 0.35 * llm_conf;
  const disagreement = Math.abs(rule_norm - llm_conf);

  let band: Band;
  let abstained: Verdict["abstained_because"] = null;
  if (disagreement > 0.4) {
    band = "unsure";
    abstained = "disagreement";
  } else if (risk >= 0.7) {
    band = "scam";
  } else if (risk >= 0.45) {
    band = "suspicious";
  } else {
    band = "likely_safe";
  }

  return {
    ...fixture,
    check_id: `chk_mock_${normalized.length.toString(36)}${evidence.length}`,
    band,
    risk: round2(risk),
    indicators,
    evidence,
    components: { ...fixture.components, rule_norm: round2(rule_norm), llm_conf },
    abstained_because: abstained,
    cached: false,
  };
}

const round2 = (n: number) => Math.round(n * 100) / 100;
