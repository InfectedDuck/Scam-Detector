import assert from "node:assert/strict";
import { test } from "node:test";

import { highlight } from "../lib/highlight";
import { normalize } from "../lib/normalize";
import type { Verdict } from "../lib/types";

function verdictWithCode(start: number, end: number): Verdict {
  const evidence = { indicator_id: "A1.otp_request", start, end, text: "код" };
  return {
    check_id: "unicode-fixture",
    band: "scam",
    risk: 1,
    language: "ru",
    indicators: [{ indicator_id: "A1.otp_request", severity: "critical", spans: [evidence], detail: {} }],
    evidence: [evidence],
    playbook_id: "kz.bank_security_call",
    playbook_confidence: 1,
    action_key: "action.hang_up_call_bank",
    hotline: "1414",
    stage: null,
    abstained_because: null,
    components: { rule_norm: 1, retrieval_sim: 1, llm_conf: 0, self_consistency: null },
    model: "rules_only",
    latency_ms: 0,
    cached: false,
  };
}

test("highlights a code-point span in the exact normalized Unicode text", () => {
  // Full-width Latin, a zero-width space, and an emoji all change the raw
  // string's UTF-16 indexing. A live API response supplies this normalized
  // text, so the highlight must use code-point rather than code-unit offsets.
  const normalized = normalize("  📱Ｂank\u200b asks for код  ");
  assert.equal(normalized, "📱Bank asks for код");

  const start = Array.from(normalized).indexOf("к");
  const rendered = highlight(normalized, verdictWithCode(start, start + 3));

  assert.equal(rendered.degraded, false);
  assert.equal(rendered.anchored.length, 1);
  assert.equal(rendered.anchored[0].status, "offset");
  assert.equal(rendered.segments.find((segment) => segment.spans.length > 0)?.text, "код");
});
