/**
 * Turn a Verdict's evidence spans into a flat, renderable segmentation of the
 * normalized message.
 *
 * This is the demo. A reader should look at the screen once and see *which
 * words* made the system say "scam". Everything else on the card is supporting
 * material.
 *
 * Three things make that harder than a substring replace:
 *
 *  1. Offsets are produced by Python and consumed by JavaScript. Python counts
 *     code points, JS counts UTF-16 units. One emoji anywhere in the message and
 *     every later offset is off by one. Everything here works in code points.
 *
 *  2. Spans overlap. A phrase can be one span for E-family money movement and
 *     another for C-family fake authority, sharing characters. Nested <mark>
 *     elements are a styling and accessibility mess, so the text is cut at every
 *     span boundary into a flat run of segments, each of which knows the full
 *     set of spans covering it.
 *
 *  3. The offsets might be wrong. docs/02_DATA_CONTRACTS.md section 1 states the
 *     invariant normalized[start:end] == text, and that invariant is exactly
 *     what makes the explainability claim testable, so this module checks it
 *     rather than assuming it. A span that fails is re-anchored by searching for
 *     its own text; one that cannot be found at all is reported separately
 *     instead of being drawn over innocent characters. Highlighting the wrong
 *     words is worse than highlighting none.
 */

import type { EvidenceSpan, Severity, Verdict } from "./types";
import { SEVERITY_ORDER } from "./types";
import { indexOfCodePoints, sliceCodePoints, toCodePoints } from "./normalize";

export type AnchorStatus =
  /** Declared offsets verified against the text. The happy path. */
  | "offset"
  /** Offsets did not verify; the span's text was located by search. */
  | "recovered"
  /** Not present in the normalized text at all. Never drawn inline. */
  | "unanchored";

export interface AnchoredSpan {
  span: EvidenceSpan;
  indicator_id: string;
  severity: Severity;
  /** Verified code-point offsets. Meaningless when status is "unanchored". */
  start: number;
  end: number;
  status: AnchorStatus;
  /** 1-based marker number, assigned in reading order. */
  n: number;
}

export interface Segment {
  text: string;
  /** Code-point bounds of this piece within the normalized text. */
  start: number;
  end: number;
  /** Spans covering this segment. Empty for ordinary text. */
  spans: AnchoredSpan[];
  /** Strongest severity among `spans`, or null. Drives the colour. */
  severity: Severity | null;
}

export interface Highlighted {
  segments: Segment[];
  /** Drawn inline, in reading order. */
  anchored: AnchoredSpan[];
  /** Listed under the text with a warning, not drawn. */
  unanchored: AnchoredSpan[];
  /** True if any span needed rescuing. A signal worth watching in eval. */
  degraded: boolean;
}

function strongest(spans: AnchoredSpan[]): Severity | null {
  let best: Severity | null = null;
  for (const s of spans) {
    if (best === null || SEVERITY_ORDER.indexOf(s.severity) > SEVERITY_ORDER.indexOf(best)) {
      best = s.severity;
    }
  }
  return best;
}

/**
 * Collect every span the verdict offers.
 *
 * The contract carries evidence in two places: the flat `evidence` list and
 * `indicators[].spans`. Take the union, keyed by (indicator, start, end, text),
 * so the card still renders if a backend version populates only one of them.
 * Severity comes from the owning IndicatorHit; evidence-only spans fall back to
 * "medium" rather than claiming a severity nobody asserted.
 */
function collect(verdict: Verdict): { span: EvidenceSpan; severity: Severity }[] {
  const severityOf = new Map<string, Severity>();
  for (const hit of verdict.indicators ?? []) {
    severityOf.set(hit.indicator_id, hit.severity);
  }

  const seen = new Set<string>();
  const out: { span: EvidenceSpan; severity: Severity }[] = [];

  const push = (span: EvidenceSpan) => {
    const key = [span.indicator_id, span.start, span.end, span.text].join("");
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ span, severity: severityOf.get(span.indicator_id) ?? "medium" });
  };

  for (const span of verdict.evidence ?? []) push(span);
  for (const hit of verdict.indicators ?? []) {
    for (const span of hit.spans ?? []) push(span);
  }
  return out;
}

/** Verify a span against the text, and if it does not verify, try to rescue it. */
function anchor(
  cps: string[],
  text: string,
  span: EvidenceSpan,
): { start: number; end: number; status: AnchorStatus } {
  const inRange =
    Number.isInteger(span.start) &&
    Number.isInteger(span.end) &&
    span.start >= 0 &&
    span.end <= cps.length &&
    span.start < span.end;

  // The invariant from docs/02_DATA_CONTRACTS.md section 1.
  if (inRange && sliceCodePoints(cps, span.start, span.end) === span.text) {
    return { start: span.start, end: span.end, status: "offset" };
  }

  // Fall back to content. Prefer the occurrence closest to where the backend
  // said it was, so a whitespace-collapsing difference in normalization shifts
  // the highlight by a few characters rather than to the wrong sentence.
  const target = span.text;
  if (!target) return { start: 0, end: 0, status: "unanchored" };

  const len = toCodePoints(target).length;
  let best: { start: number; distance: number } | null = null;
  for (let from = 0; ; ) {
    const at = indexOfCodePoints(text, target, from);
    if (at === -1) break;
    const distance = Math.abs(at - (span.start ?? 0));
    if (best === null || distance < best.distance) best = { start: at, distance };
    from = at + 1;
  }

  if (best) return { start: best.start, end: best.start + len, status: "recovered" };
  return { start: 0, end: 0, status: "unanchored" };
}

export function highlight(normalizedText: string, verdict: Verdict): Highlighted {
  const cps = toCodePoints(normalizedText);
  const collected = collect(verdict);

  const anchored: AnchoredSpan[] = [];
  const unanchored: AnchoredSpan[] = [];

  for (const { span, severity } of collected) {
    const a = anchor(cps, normalizedText, span);
    const entry: AnchoredSpan = {
      span,
      indicator_id: span.indicator_id,
      severity,
      start: a.start,
      end: a.end,
      status: a.status,
      n: 0,
    };
    (a.status === "unanchored" ? unanchored : anchored).push(entry);
  }

  // Reading order, longest first on a tie so the outer span gets the lower
  // number: it reads more naturally when two markers land together.
  anchored.sort((a, b) => a.start - b.start || b.end - a.end);
  anchored.forEach((s, i) => {
    s.n = i + 1;
  });
  unanchored.forEach((s, i) => {
    s.n = anchored.length + i + 1;
  });

  // Cut at every boundary, then ask which spans cover each piece. Quadratic in
  // principle, but both factors are tiny: a message is capped at 8000
  // characters and a verdict rarely carries more than a dozen spans.
  const boundaries = new Set<number>([0, cps.length]);
  for (const s of anchored) {
    boundaries.add(Math.max(0, Math.min(cps.length, s.start)));
    boundaries.add(Math.max(0, Math.min(cps.length, s.end)));
  }
  const cuts = [...boundaries].sort((a, b) => a - b);

  const segments: Segment[] = [];
  for (let i = 0; i < cuts.length - 1; i++) {
    const from = cuts[i];
    const to = cuts[i + 1];
    if (to <= from) continue;

    const covering = anchored.filter((s) => s.start <= from && s.end >= to);
    const previous = segments[segments.length - 1];
    const sameCover =
      previous !== undefined &&
      previous.spans.length === covering.length &&
      previous.spans.every((s, k) => s === covering[k]);

    if (sameCover) {
      previous.text += sliceCodePoints(cps, from, to);
      previous.end = to;
      continue;
    }
    segments.push({
      text: sliceCodePoints(cps, from, to),
      start: from,
      end: to,
      spans: covering,
      severity: strongest(covering),
    });
  }

  return {
    segments,
    anchored,
    unanchored,
    degraded: unanchored.length > 0 || anchored.some((s) => s.status === "recovered"),
  };
}
