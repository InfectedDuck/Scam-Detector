import type { AnalyzeResult, Severity } from "@/lib/types";
import { highlight } from "@/lib/highlight";
import { LOCALE_TAGS, type Messages } from "@/i18n";
import { HighlightedMessage } from "./HighlightedMessage";

/**
 * The answer to all four questions from docs/01_ARCHITECTURE.md section 1, in
 * the order a frightened person needs them: what is it, why do we say so, what
 * do I do, and only then how the machine got there.
 *
 * A server component. None of this, nor the strings it reads, reaches the
 * browser as JavaScript. Every sentence about the verdict — band, indicator
 * labels, the advice, the hotline name — comes from the backend's own i18n and
 * playbook files through `messages`; only page chrome is authored in web/.
 */
export function VerdictCard({ result, messages }: { result: AnalyzeResult; messages: Messages }) {
  const { verdict, normalized_text } = result;
  const { locale, t, isFallback } = messages;
  const marked = highlight(normalized_text, verdict);
  const tag = LOCALE_TAGS[locale];

  const percent = (n: number) => Math.round(Math.min(1, Math.max(0, n)) * 100);
  const ratio = (n: number) =>
    new Intl.NumberFormat(tag, { style: "percent", maximumFractionDigits: 0 }).format(n);

  const playbook = verdict.playbook_id ? messages.playbookName(verdict.playbook_id) : undefined;
  const action = messages.actionText(verdict.action_key, verdict.band);
  const hotlineLabel = messages.hotlineLabel(verdict.hotline);

  // kk.yaml leaves untranslated strings null and the backend shows the Russian
  // text with a note in the footer. Same here: if anything on this card had to
  // fall back, say so once, at the bottom.
  const fellBack =
    [
      `band.${verdict.band}.title`,
      `band.${verdict.band}.summary`,
      verdict.abstained_because ? `abstained.reason.${verdict.abstained_because}` : null,
      verdict.stage ? `stage.${verdict.stage}.description` : null,
      ...marked.anchored.map((s) => `indicator.${s.indicator_id}`),
    ]
      .filter((key): key is string => key !== null)
      .some(isFallback) ||
    Boolean(playbook?.fellBack) ||
    action.fellBack;

  return (
    <section
      data-band={verdict.band}
      aria-labelledby="verdict-title"
      className="overflow-hidden rounded-2xl border border-line bg-surface"
    >
      {/* ---- the answer ---------------------------------------------- */}
      <header
        className="border-b px-5 py-4 sm:px-6"
        style={{ background: "var(--band-bg)", borderColor: "var(--band-line)" }}
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span
            className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide"
            style={{ borderColor: "var(--band-line)", color: "var(--band-fg)" }}
          >
            {t(`band.${verdict.band}.label`)}
          </span>
          <span className="text-sm text-muted">
            {t("footer.risk", { percent: percent(verdict.risk) })}
          </span>
        </div>

        <h2
          id="verdict-title"
          className="mt-2 text-balance text-2xl font-semibold tracking-tight"
          style={{ color: "var(--band-fg)" }}
        >
          {t(`band.${verdict.band}.title`)}
        </h2>

        <p className="mt-1.5 max-w-prose text-pretty text-[0.9375rem] leading-relaxed text-ink/85">
          {t(`band.${verdict.band}.summary`)}
        </p>

        <RiskMeter risk={verdict.risk} label={t("footer.risk", { percent: percent(verdict.risk) })} />

        {(playbook || verdict.stage) && (
          <div className="mt-3 flex flex-col gap-1 text-[0.8125rem] text-muted">
            {playbook && (
              <span>
                {t("card.playbook")}: <span className="text-ink">{playbook.text}</span>{" "}
                <span className="tabular-nums">({ratio(verdict.playbook_confidence)})</span>
              </span>
            )}
            {verdict.stage && (
              <span>
                {t("stage.now", {
                  label: t(`stage.${verdict.stage}.label`),
                  description: t(`stage.${verdict.stage}.description`),
                })}
              </span>
            )}
          </div>
        )}

        {verdict.abstained_because && (
          <p
            className="mt-3 rounded-lg border px-3 py-2 text-[0.875rem] text-ink/85"
            style={{ borderColor: "var(--band-line)" }}
          >
            {t("abstained.line", { reason: t(`abstained.reason.${verdict.abstained_because}`) })}
          </p>
        )}
      </header>

      {/* ---- the evidence, on the message itself ---------------------- */}
      <div className="px-5 py-5 sm:px-6">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">
          {t("card.text.title")}
        </h3>
        <div className="mt-3 rounded-xl bg-raised px-4 py-3.5">
          <HighlightedMessage highlighted={marked} t={t} id="verdict-message" />
        </div>

        <h3 className="mt-6 text-xs font-semibold uppercase tracking-wider text-muted">
          {t("card.evidence")}
        </h3>

        {marked.anchored.length === 0 && marked.unanchored.length === 0 ? (
          <p className="mt-2 text-[0.9375rem] text-muted">{t("evidence.none")}</p>
        ) : (
          <ol className="mt-3 space-y-2.5">
            {marked.anchored.map((span) => (
              <li key={span.n} className="flex gap-3 text-[0.9375rem] leading-snug">
                <a
                  href={`#mark-${span.n}`}
                  className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums no-underline"
                  style={{ background: severityBg(span.severity), color: severityLine(span.severity) }}
                  aria-label={`${span.n}`}
                >
                  {span.n}
                </a>
                <span className="min-w-0">
                  <span className="text-ink">{t(`indicator.${span.indicator_id}`)}</span>
                  <span className="text-muted"> · {t(`severity.${span.severity}`)}</span>
                  <br />
                  <q className="text-muted">{span.span.text}</q>
                </span>
              </li>
            ))}
          </ol>
        )}

        {marked.unanchored.length > 0 && (
          <p className="mt-3 text-[0.8125rem] text-muted">
            {t("card.evidence.unanchored", { n: marked.unanchored.length })}
          </p>
        )}
      </div>

      {/* ---- what to do. The product. -------------------------------- */}
      <div
        className="border-t px-5 py-5 sm:px-6"
        style={{ borderColor: "var(--band-line)", background: "var(--band-bg)" }}
      >
        <h3
          className="text-xs font-semibold uppercase tracking-wider"
          style={{ color: "var(--band-fg)" }}
        >
          {t("card.action")}
        </h3>
        <p className="mt-2 max-w-prose text-pretty text-[1.0625rem] leading-relaxed text-ink">
          {action.text}
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
          <a
            href={`tel:${verdict.hotline}`}
            className="inline-flex min-h-11 items-center rounded-xl px-5 py-2.5 text-base font-semibold text-bg no-underline"
            style={{ background: "var(--band-fg)" }}
          >
            {t("card.call", { hotline: verdict.hotline })}
          </a>
          {hotlineLabel && <span className="text-[0.875rem] text-muted">{hotlineLabel}</span>}
        </div>
      </div>

      {/* ---- how it was decided. Collapsed: this is for us, not them. -- */}
      <details className="border-t border-line px-5 py-3 text-[0.875rem] sm:px-6">
        <summary className="cursor-pointer list-none text-muted marker:content-none">
          {t("card.how")}
        </summary>
        <dl className="mt-3 space-y-2">
          <Component label={t("card.components.rule_norm")} value={verdict.components.rule_norm} format={ratio} />
          <Component label={t("card.components.retrieval_sim")} value={verdict.components.retrieval_sim} format={ratio} />
          <Component label={t("card.components.llm_conf")} value={verdict.components.llm_conf} format={ratio} />
          {verdict.components.self_consistency !== null && (
            <Component
              label={t("card.components.self_consistency")}
              value={verdict.components.self_consistency}
              format={ratio}
            />
          )}
        </dl>
        <p className="mt-3 font-mono text-[0.75rem] text-muted">
          {verdict.model} · {t("card.meta.latency", { ms: verdict.latency_ms })}
          {verdict.cached ? ` · ${t("card.meta.cached")}` : ""} ·{" "}
          {t("footer.check_id", { check_id: verdict.check_id })}
        </p>
      </details>

      {fellBack && (
        <p className="border-t border-line px-5 py-2.5 text-[0.75rem] text-muted sm:px-6">
          {t("footer.fallback")}
        </p>
      )}
    </section>
  );
}

function RiskMeter({ risk, label }: { risk: number; label: string }) {
  return (
    <div
      className="mt-3 h-1.5 w-full overflow-hidden rounded-full"
      style={{ background: "var(--band-line)" }}
      role="img"
      aria-label={label}
    >
      <div
        className="h-full rounded-full"
        style={{
          width: `${Math.round(Math.min(1, Math.max(0, risk)) * 100)}%`,
          background: "var(--band-fg)",
        }}
      />
    </div>
  );
}

function Component({
  label,
  value,
  format,
}: {
  label: string;
  value: number;
  format: (n: number) => string;
}) {
  return (
    <div className="flex items-center gap-3">
      <dt className="w-32 shrink-0 text-muted">{label}</dt>
      <dd className="flex min-w-0 flex-1 items-center gap-2">
        <span className="h-1 flex-1 overflow-hidden rounded-full bg-line">
          <span
            className="block h-full rounded-full bg-muted"
            style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%` }}
          />
        </span>
        <span className="w-10 shrink-0 text-right tabular-nums text-muted">{format(value)}</span>
      </dd>
    </div>
  );
}

const severityBg = (s: Severity) => `var(--mark-${s}-bg)`;
const severityLine = (s: Severity) => `var(--mark-${s}-line)`;
