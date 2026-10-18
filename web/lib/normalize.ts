/**
 * Stage 0, client-side mirror.
 *
 * The authority is `src/saqbol/core/normalize.py`. This exists only because the
 * `Verdict` contract returns offsets into the normalized string without
 * returning the normalized string itself, so mock fixtures need a local copy.
 * Live API responses provide `normalized_text` and are rendered from it.
 *
 * It is deliberately conservative: NFKC and zero-width removal, the two steps
 * named in docs/01_ARCHITECTURE.md §3. If the Python side does more (collapsing
 * whitespace runs, for example) the two strings drift, and every span is
 * re-anchored by content instead of by offset. See lib/highlight.ts — anchoring
 * never trusts an offset it has not verified.
 */

/** Zero-width and other invisible characters scammers use to break keyword rules. */
const INVISIBLE = new RegExp(
  "[" +
    "\u00AD" + // soft hyphen
    "\u180E" + // mongolian vowel separator
    "\u200B\u200C\u200D" + // zero-width space / non-joiner / joiner
    "\u200E\u200F" + // left-to-right / right-to-left mark
    "\u2060\u2061\u2062\u2063\u2064" + // word joiner, invisible operators
    "\uFEFF" + // byte order mark
    "]",
  "g",
);

export function normalize(raw: string): string {
  return raw
    .normalize("NFKC")
    .replace(/\r\n?/g, "\n")
    .replace(INVISIBLE, "")
    .trim();
}

/**
 * Python string indices count Unicode code points; JavaScript string indices
 * count UTF-16 code units. They agree across Cyrillic, Kazakh and Chinese, and
 * disagree the moment a message contains an emoji — which scam bait routinely
 * does. Every offset that crosses the boundary between Python and this file
 * goes through these helpers.
 */
export function toCodePoints(s: string): string[] {
  return Array.from(s);
}

/** Slice by code point, i.e. the way Python would slice it. */
export function sliceCodePoints(cps: string[], start: number, end: number): string {
  return cps.slice(start, end).join("");
}

/** Length in code points. */
export function codePointLength(s: string): number {
  return toCodePoints(s).length;
}

/** Index of `needle` in `haystack`, both measured in code points. -1 if absent. */
export function indexOfCodePoints(haystack: string, needle: string, from = 0): number {
  const cps = toCodePoints(haystack);
  const target = toCodePoints(needle);
  if (target.length === 0) return -1;
  outer: for (let i = from; i + target.length <= cps.length; i++) {
    for (let j = 0; j < target.length; j++) {
      if (cps[i + j] !== target[j]) continue outer;
    }
    return i;
  }
  return -1;
}
