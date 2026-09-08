import type { ReactNode } from "react";

import type { T } from "@/i18n";

/**
 * The pieces of a scenario page, shared by the share page and the library so
 * the two cannot drift apart visually. All server components; the band colours
 * come from the `data-band` attribute on the enclosing article.
 */

export function ScenarioHeader({
  kicker,
  title,
  summary,
}: {
  kicker: string;
  title: string;
  summary: string | undefined;
}) {
  return (
    <header
      className="border-b px-5 py-5 sm:px-6"
      style={{ background: "var(--band-bg)", borderColor: "var(--band-line)" }}
    >
      <span
        className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide"
        style={{ borderColor: "var(--band-line)", color: "var(--band-fg)" }}
      >
        {kicker}
      </span>
      <h1
        className="mt-2 text-balance text-2xl font-semibold tracking-tight sm:text-3xl"
        style={{ color: "var(--band-fg)" }}
      >
        {title}
      </h1>
      {summary && (
        <p className="mt-2 max-w-prose text-pretty text-[0.9375rem] leading-relaxed text-ink/85">
          {summary}
        </p>
      )}
    </header>
  );
}

export function RedFlags({ title, flags }: { title: string; flags: string[] }) {
  if (flags.length === 0) return null;
  return (
    <div className="px-5 py-5 sm:px-6">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h2>
      <ul className="mt-3 space-y-2.5">
        {flags.map((flag, i) => (
          <li key={i} className="flex gap-3 text-[0.9375rem] leading-snug text-ink">
            <span
              aria-hidden="true"
              className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full"
              style={{ background: "var(--band-fg)" }}
            />
            <span className="min-w-0 text-pretty">{flag}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The advice and the number to call. `children` renders under the call button, inside the tint. */
export function ActionBlock({
  t,
  action,
  hotline,
  hotlineLabel,
  children,
}: {
  t: T;
  action: string;
  hotline: string;
  hotlineLabel: string | undefined;
  children?: ReactNode;
}) {
  return (
    <div
      className="border-t px-5 py-5 sm:px-6"
      style={{ borderColor: "var(--band-line)", background: "var(--band-bg)" }}
    >
      <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--band-fg)" }}>
        {t("card.action")}
      </h2>
      <p className="mt-2 max-w-prose text-pretty text-[1.0625rem] leading-relaxed text-ink">
        {action}
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <a
          href={`tel:${telHref(hotline)}`}
          className="inline-flex min-h-11 items-center rounded-xl px-5 py-2.5 text-base font-semibold text-bg no-underline"
          style={{ background: "var(--band-fg)" }}
        >
          {t("card.call", { hotline })}
        </a>
        {hotlineLabel && <span className="text-[0.875rem] text-muted">{hotlineLabel}</span>}
      </div>
      {children}
    </div>
  );
}

export function FallbackNote({ text }: { text: string }) {
  return (
    <p className="border-t border-line px-5 py-2.5 text-[0.75rem] text-muted sm:px-6">{text}</p>
  );
}

/** "+86 10 6532 3382" → "+861065323382", so the link dials on a phone. */
export function telHref(number: string): string {
  return number.replace(/[^\d+]/g, "");
}
