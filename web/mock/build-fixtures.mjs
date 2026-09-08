/**
 * Generates web/mock/*.json from the sample messages below.
 *
 * Offsets are computed, never typed. docs/02_DATA_CONTRACTS.md section 1 makes
 * normalized[start:end] == text an invariant, and a fixture that violates it
 * would quietly test the anchoring fallback instead of the happy path. The
 * script computes offsets in Unicode CODE POINTS, the way Python slices, and
 * refuses to write a file whose spans do not verify.
 *
 * Indicator ids and severities are the ones in docs/03_INDICATORS.md, and the
 * playbook ids, action keys and hotlines are the ones in
 * src/saqbol/playbooks/data/, so every label the card shows resolves against
 * the backend's own i18n files.
 *
 * Run: npm run fixtures
 */

import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

// Kept in step with lib/normalize.ts, which is itself a mirror of
// src/saqbol/core/normalize.py.
const INVISIBLE = /[\u00AD\u180E\u200B-\u200F\u2060-\u2064\uFEFF]/g;
const normalize = (raw) =>
  raw.normalize("NFKC").replace(/\r\n?/g, "\n").replace(INVISIBLE, "").trim();

const SEVERITY_WEIGHT = { critical: 40, high: 25, medium: 12, low: 5 };

/**
 * Each sample names its evidence by phrase. The script resolves phrase -> offsets.
 * `nth` picks a later occurrence when a phrase repeats.
 */
const SAMPLES = [
  {
    id: "bank_call",
    file: "verdict.json", // the canonical fixture
    lang: "ru",
    text:
      "Здравствуйте! Вас беспокоит служба безопасности Kaspi Bank. " +
      "С вашего счёта прямо сейчас пытаются списать 480 000 тенге в пользу неизвестного получателя. " +
      "Чтобы отменить операцию, я должен убедиться, что говорю с владельцем счёта — " +
      "назовите код из СМС, который вам сейчас придёт. " +
      "Не кладите трубку и никому не сообщайте о нашем разговоре, идёт расследование. " +
      "Для защиты средств переведите остаток на резервный счёт.",
    indicators: [
      {
        indicator_id: "C1.bank_security",
        severity: "high",
        phrases: ["служба безопасности Kaspi Bank"],
        detail: { claimed_brand: "Kaspi Bank" },
      },
      {
        indicator_id: "B1.urgency",
        severity: "medium",
        phrases: ["прямо сейчас"],
        detail: {},
      },
      {
        indicator_id: "B4.money_at_risk",
        severity: "medium",
        phrases: ["пытаются списать 480 000 тенге"],
        detail: { amount: "480 000 тенге" },
      },
      {
        indicator_id: "A1.otp_request",
        severity: "critical",
        phrases: ["назовите код из СМС"],
        detail: { credential: "otp" },
      },
      {
        indicator_id: "D3.dont_hang_up",
        severity: "high",
        phrases: ["Не кладите трубку"],
        detail: {},
      },
      {
        indicator_id: "J1.secrecy",
        severity: "high",
        phrases: ["никому не сообщайте"],
        detail: {},
      },
      {
        indicator_id: "E1.safe_account",
        severity: "critical",
        phrases: ["переведите остаток на резервный счёт"],
        detail: {},
      },
    ],
    verdict: {
      check_id: "chk_01K4Q7YB3M2P8ZV0",
      band: "scam",
      risk: 0.95,
      playbook_id: "kz.bank_security_call",
      playbook_confidence: 0.91,
      // Stage is only set for multi-message threads (contracts §1). Every
      // sample here is a single message, so it stays null throughout.
      stage: null,
      action_key: "action.hang_up_call_bank",
      hotline: "1414",
      language: "ru",
      components: {
        rule_norm: 1.0,
        retrieval_sim: 0.87,
        llm_conf: 0.94,
        // risk 0.95 is outside the [0.30, 0.75] self-consistency window
        // (docs/01_ARCHITECTURE.md §3), so only one call was made.
        self_consistency: null,
      },
      abstained_because: null,
      model: "deepseek-v3",
      latency_ms: 1840,
      cached: false,
    },
  },

  {
    id: "parcel_fee",
    file: "verdict.parcel.json",
    lang: "ru",
    // The emoji is deliberate: it pushes every following offset apart in UTF-16
    // but not in code points, so this fixture fails loudly if the renderer ever
    // starts indexing the JS way.
    text:
      "📦 Ваша посылка задержана на таможенном складе. " +
      "Оплатите таможенный сбор 1 490 тг по ссылке: https://kaspi-kz.pay-secure.top/track?id=88214 " +
      "Срок хранения истекает через 24 часа, после чего посылка будет возвращена отправителю.",
    indicators: [
      {
        indicator_id: "C6.courier_post",
        severity: "medium",
        phrases: ["задержана на таможенном складе"],
        detail: {},
      },
      {
        indicator_id: "E7.upfront_fee",
        severity: "high",
        phrases: ["Оплатите таможенный сбор"],
        detail: { amount: "1 490 тг" },
      },
      {
        indicator_id: "G5.brand_mismatch",
        severity: "high",
        phrases: ["https://kaspi-kz.pay-secure.top/track?id=88214"],
        detail: { brand: "kaspi", registrable_domain: "pay-secure.top" },
      },
      {
        // Overlaps G5 on purpose. Two indicators, one stretch of characters:
        // the segmentation has to cope without nesting <mark> elements.
        indicator_id: "G6.fresh_domain",
        severity: "low",
        phrases: ["pay-secure.top"],
        detail: { registered_days_ago: 9 },
      },
      {
        indicator_id: "B1.urgency",
        severity: "medium",
        phrases: ["истекает через 24 часа"],
        detail: {},
      },
    ],
    verdict: {
      check_id: "chk_01K4Q81F6D4T2WX7",
      band: "suspicious",
      risk: 0.69,
      playbook_id: "kz.delivery_link",
      playbook_confidence: 0.74,
      stage: null,
      action_key: "action.check_tracking_on_official_site",
      hotline: "102",
      language: "ru",
      components: {
        rule_norm: 0.79,
        retrieval_sim: 0.71,
        llm_conf: 0.55,
        self_consistency: 0.8,
      },
      abstained_because: null,
      model: "deepseek-v3",
      latency_ms: 3120,
      cached: false,
    },
  },

  {
    id: "job_offer",
    file: "verdict.unsure.json",
    lang: "kk",
    text:
      "Сәлеметсіз бе! Сізге қашықтан жұмыс ұсынамыз: күніне 2 сағат, айына 350 000 теңге. " +
      "Тәжірибе қажет емес, оқытамыз. " +
      "Толық ақпарат алу үшін менеджерге Telegram арқылы жазыңыз: @hr_kazwork_2026",
    indicators: [
      {
        indicator_id: "H1.guaranteed_returns",
        severity: "high",
        phrases: ["айына 350 000 теңге"],
        detail: { amount: "350 000 теңге", hours_claimed: "2" },
      },
      {
        indicator_id: "H4.easy_job",
        severity: "medium",
        phrases: ["Тәжірибе қажет емес"],
        detail: {},
      },
      {
        indicator_id: "D1.move_to_messenger",
        severity: "medium",
        phrases: ["Telegram арқылы жазыңыз"],
        detail: { channel: "telegram", handle: "@hr_kazwork_2026" },
      },
    ],
    verdict: {
      check_id: "chk_01K4Q8B0S9H5N3RC",
      band: "unsure",
      risk: 0.67,
      // Nothing in the library matched well enough, so no playbook, and the
      // advice comes from action.generic.unsure in the shared i18n table.
      playbook_id: null,
      playbook_confidence: 0.41,
      stage: null,
      action_key: "action.generic.unsure",
      hotline: "1414",
      language: "kk",
      components: {
        rule_norm: 0.49,
        // The model is far more certain than the rules are. |0.49 - 0.91| = 0.42,
        // over the 0.40 threshold, so stage 5 overrides the band to unsure.
        // This fixture exists to make the abstention path visible in the UI.
        retrieval_sim: 0.66,
        llm_conf: 0.91,
        self_consistency: 0.8,
      },
      abstained_because: "disagreement",
      model: "deepseek-v3",
      latency_ms: 4870,
      cached: false,
    },
  },

  {
    id: "real_notification",
    file: "verdict.safe.json",
    lang: "ru",
    // A hard negative: a genuine card notification. No evidence spans at all,
    // which is the empty state the card has to render without looking broken.
    text:
      "Kaspi Gold *1290: покупка 4 990 ₸, MAGNUM SATPAEVA, 08.09.2026 19:42. " +
      "Доступно 214 300 ₸. Если операция не ваша, позвоните в банк по номеру на обороте карты.",
    indicators: [],
    verdict: {
      check_id: "chk_01K4Q8HN7E1J6YD4",
      band: "likely_safe",
      risk: 0.1,
      playbook_id: null,
      playbook_confidence: 0.0,
      stage: null,
      action_key: "action.generic.likely_safe",
      hotline: "1414",
      language: "ru",
      components: {
        rule_norm: 0.0,
        retrieval_sim: 0.34,
        llm_conf: 0.08,
        self_consistency: null,
      },
      abstained_because: null,
      model: "deepseek-v3",
      latency_ms: 42,
      cached: true,
    },
  },

  {
    id: "police_impersonation",
    file: "verdict.police.json",
    lang: "zh",
    text:
      "您好，这里是深圳市公安局反诈中心。您的身份信息涉嫌一起特大洗钱案件，请立即配合调查。" +
      "为核实资金来源，请将账户余额转入我们指定的安全账户，并全程保持通话，" +
      "不得向任何人透露案情，否则将以妨碍司法论处。",
    indicators: [
      {
        indicator_id: "C2.police_prosecutor",
        severity: "high",
        phrases: ["深圳市公安局反诈中心"],
        detail: { claimed_authority: "public_security", jurisdiction: "cn" },
      },
      {
        indicator_id: "B1.urgency",
        severity: "medium",
        phrases: ["请立即配合调查"],
        detail: {},
      },
      {
        indicator_id: "E1.safe_account",
        severity: "critical",
        phrases: ["转入我们指定的安全账户"],
        detail: {},
      },
      {
        indicator_id: "D3.dont_hang_up",
        severity: "high",
        phrases: ["全程保持通话"],
        detail: {},
      },
      {
        indicator_id: "J1.secrecy",
        severity: "high",
        phrases: ["不得向任何人透露案情"],
        detail: {},
      },
      {
        indicator_id: "B3.criminal_threat",
        severity: "high",
        phrases: ["否则将以妨碍司法论处"],
        detail: {},
      },
    ],
    verdict: {
      check_id: "chk_01K4Q8T2V8A9M1QF",
      band: "scam",
      risk: 0.95,
      playbook_id: "cn.fake_police_deposit",
      playbook_confidence: 0.93,
      stage: null,
      action_key: "action.hang_up_dial_96110",
      hotline: "96110",
      language: "zh",
      components: {
        rule_norm: 1.0,
        retrieval_sim: 0.83,
        llm_conf: 0.96,
        self_consistency: null,
      },
      abstained_because: null,
      model: "qwen3-max",
      latency_ms: 1610,
      cached: false,
    },
  },
];

/** Code-point index of `needle` in `haystack`, both in code points. */
function indexOfCodePoints(haystack, needle, from = 0) {
  const cps = Array.from(haystack);
  const target = Array.from(needle);
  outer: for (let i = from; i + target.length <= cps.length; i++) {
    for (let j = 0; j < target.length; j++) {
      if (cps[i + j] !== target[j]) continue outer;
    }
    return i;
  }
  return -1;
}

let failures = 0;
const manifest = [];

for (const sample of SAMPLES) {
  const normalized = normalize(sample.text);
  const cps = Array.from(normalized);

  const indicators = [];
  const evidence = [];

  for (const ind of sample.indicators) {
    const spans = [];
    for (const phrase of ind.phrases) {
      const start = indexOfCodePoints(normalized, phrase);
      if (start === -1) {
        console.error(`  ! ${sample.id}: phrase not found: ${JSON.stringify(phrase)}`);
        failures++;
        continue;
      }
      const end = start + Array.from(phrase).length;
      const span = { start, end, text: phrase, indicator_id: ind.indicator_id };

      // The invariant, checked here so it can never be wrong in a committed file.
      if (cps.slice(start, end).join("") !== span.text) {
        console.error(`  ! ${sample.id}: invariant violated for ${phrase}`);
        failures++;
      }
      spans.push(span);
      evidence.push(span);
    }
    indicators.push({
      indicator_id: ind.indicator_id,
      severity: ind.severity,
      spans,
      detail: ind.detail ?? {},
    });
  }

  evidence.sort((a, b) => a.start - b.start || b.end - a.end);

  // Cross-check the declared rule_norm against the severity weights, so the
  // fixture cannot drift from the formula in docs/01_ARCHITECTURE.md section 3.
  const weightSum = indicators.reduce((n, i) => n + SEVERITY_WEIGHT[i.severity] * i.spans.length, 0);
  const expected = Math.min(1, weightSum / 100);
  const declared = sample.verdict.components.rule_norm;
  if (Math.abs(expected - declared) > 0.02) {
    console.error(
      `  ! ${sample.id}: rule_norm ${declared} but weights give ${expected.toFixed(2)}`,
    );
    failures++;
  }

  const verdict = { ...sample.verdict, indicators, evidence };

  // Field order follows the pydantic model so a diff against a real API
  // response stays readable.
  const ordered = {
    check_id: verdict.check_id,
    band: verdict.band,
    risk: verdict.risk,
    playbook_id: verdict.playbook_id,
    playbook_confidence: verdict.playbook_confidence,
    stage: verdict.stage,
    indicators: verdict.indicators,
    evidence: verdict.evidence,
    action_key: verdict.action_key,
    hotline: verdict.hotline,
    language: verdict.language,
    components: verdict.components,
    abstained_because: verdict.abstained_because,
    model: verdict.model,
    latency_ms: verdict.latency_ms,
    cached: verdict.cached,
  };

  writeFileSync(join(HERE, sample.file), JSON.stringify(ordered, null, 2) + "\n", "utf8");
  manifest.push({
    id: sample.id,
    lang: sample.lang,
    file: sample.file,
    text: sample.text,
    band: verdict.band,
  });
  console.log(
    `  ${sample.file.padEnd(22)} ${verdict.band.padEnd(12)} ${evidence.length} span(s)`,
  );
}

writeFileSync(join(HERE, "samples.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8");
console.log(`  samples.json           ${manifest.length} samples`);

if (failures > 0) {
  console.error(`\n${failures} fixture problem(s). Files above may be wrong.`);
  process.exit(1);
}
console.log("\nAll spans verify against the normalized text.");
