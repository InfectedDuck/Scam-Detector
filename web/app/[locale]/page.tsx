import Link from "next/link";
import { notFound } from "next/navigation";

import { AnalyzeForm } from "@/components/AnalyzeForm";
import { VerdictCard } from "@/components/VerdictCard";
import { LOCALES, LOCALE_NAMES, getMessages, isLocale } from "@/i18n";
import { USING_MOCK, fetchVerdict } from "@/lib/api";
import { SAMPLES, getSample } from "@/mock";
import { analyzeAction } from "./actions";

/**
 * A server component all the way down.
 *
 * `?sample=<id>` renders a finished verdict card in the HTML response, so the
 * demo works before a single byte of JavaScript arrives, and works at all with
 * scripting disabled. The paste box hydrates on top of that.
 */
export default async function HomePage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  const query = await searchParams;
  const requested = typeof query.sample === "string" ? query.sample : undefined;
  const sample = requested ? getSample(requested) : undefined;

  const messages = getMessages(locale);
  const { t } = messages;
  const initial = sample ? await fetchVerdict({ text: sample.text, surface: "web" }) : null;

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col px-4 py-6 sm:px-6 sm:py-10">
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <Link href={`/${locale}`} className="text-lg font-semibold tracking-tight no-underline">
          {t("app.name")}
        </Link>

        <nav aria-label={t("nav.language")} className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
          {LOCALES.map((option) => (
            <Link
              key={option}
              // Keep ?sample= across the switch: reading the same scam in four
              // languages is the fastest way to show the localisation works.
              href={sample ? `/${option}?sample=${sample.id}` : `/${option}`}
              hrefLang={option}
              prefetch={false}
              aria-current={option === locale ? "true" : undefined}
              className={
                option === locale
                  ? "font-semibold text-ink no-underline"
                  : "text-muted no-underline hover:text-ink"
              }
            >
              {LOCALE_NAMES[option]}
            </Link>
          ))}
        </nav>
      </header>

      <main className="mt-8 flex-1">
        <h1 className="text-balance text-2xl font-semibold tracking-tight sm:text-3xl">
          {t("app.tagline")}
        </h1>
        <p className="mt-3 max-w-prose text-pretty text-[0.9375rem] leading-relaxed text-muted">
          {t("home.lead")}
        </p>

        <AnalyzeForm
          // Remounting on sample change resets the uncontrolled textarea and
          // clears any verdict left over from the previous sample.
          key={sample?.id ?? "blank"}
          action={analyzeAction.bind(null, locale)}
          defaultValue={sample?.text ?? ""}
          strings={{
            label: t("form.label"),
            placeholder: t("form.placeholder"),
            submit: t("form.submit"),
            submitting: t("form.submitting"),
            counter: t("form.counter"),
          }}
          fallback={initial ? <VerdictCard result={initial} messages={messages} /> : null}
        />

        <section className="mt-10">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
            {t("form.samples.title")}
          </h2>
          <ul className="mt-3 flex flex-wrap gap-2">
            {SAMPLES.map((entry) => (
              <li key={entry.id}>
                <Link
                  href={`/${locale}?sample=${entry.id}`}
                  prefetch={false}
                  data-band={entry.band}
                  aria-current={entry.id === sample?.id ? "true" : undefined}
                  className="inline-flex min-h-9 items-center rounded-full border px-3.5 py-1.5 text-[0.8125rem] no-underline"
                  style={{
                    borderColor: "var(--band-line)",
                    background: entry.id === sample?.id ? "var(--band-bg)" : "transparent",
                    color: entry.id === sample?.id ? "var(--band-fg)" : "var(--muted)",
                  }}
                >
                  {t(`sample.${entry.id}`)}
                </Link>
              </li>
            ))}
          </ul>
          <p className="mt-2.5 text-[0.8125rem] text-muted">{t("form.samples.hint")}</p>
        </section>
      </main>

      <footer className="mt-12 border-t border-line pt-5 text-[0.8125rem] leading-relaxed text-muted">
        {USING_MOCK && (
          <p className="mb-2 font-medium text-ink">{t("mock.banner")}</p>
        )}
        <p className="max-w-prose">{t("footer.disclaimer")}</p>
      </footer>
    </div>
  );
}
