import Link from "next/link";
import { notFound } from "next/navigation";

import { AnalyzeForm } from "@/components/AnalyzeForm";
import { CopyLinkScript } from "@/components/ShareBar";
import { Shell } from "@/components/Shell";
import { VerdictCard } from "@/components/VerdictCard";
import { getMessages, isLocale } from "@/i18n";
import { USING_MOCK } from "@/lib/api";
import { normalize } from "@/lib/normalize";
import { siteOrigin } from "@/lib/site";
import { TURNSTILE_SITE_KEY, challengeRequired, readCheckCount } from "@/lib/turnstile";
import { FIXTURES, SAMPLES, getSample } from "@/mock";
import { analyzeAction } from "./actions";

/**
 * A server component all the way down.
 *
 * `?sample=<id>` renders a finished verdict card in the HTML response, so the
 * demo works before a single byte of JavaScript arrives, and works at all with
 * scripting disabled. Samples use saved fixtures and never spend a live API
 * check. The paste box hydrates on top of that.
 *
 * This is the one page rendered per request: it reads `searchParams`, the
 * request origin for share links, and the session cookie that decides
 * whether the form must carry a Turnstile widget. The share, library and
 * stats pages stay static.
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
  const initial = sample
    ? { verdict: FIXTURES[sample.id], normalized_text: normalize(sample.text) }
    : null;
  const origin = await siteOrigin();
  const turnstileSiteKey = challengeRequired(await readCheckCount()) ? TURNSTILE_SITE_KEY : undefined;

  return (
    <Shell
      locale={locale}
      // Keep ?sample= across the switch: reading the same scam in four
      // languages is the fastest way to show the localisation works.
      href={(option) => (sample ? `/${option}?sample=${sample.id}` : `/${option}`)}
      note={USING_MOCK ? t("mock.banner") : undefined}
    >
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
        turnstileSiteKey={turnstileSiteKey}
        strings={{
          label: t("form.label"),
          placeholder: t("form.placeholder"),
          submit: t("form.submit"),
          submitting: t("form.submitting"),
          counter: t("form.counter"),
          turnstileHint: t("form.turnstile.hint"),
          image: {
            label: t("form.image.label"),
            hint: t("form.image.hint"),
            browse: t("form.image.browse"),
            preview: t("form.image.preview"),
            remove: t("form.image.remove"),
            preparing: t("form.image.preparing"),
            tooLarge: t("form.image.too_large"),
            wrongType: t("form.image.wrong_type"),
          },
        }}
        fallback={
          initial ? (
            <>
              <p className="mb-3 text-[0.8125rem] leading-relaxed text-muted">
                {t("form.samples.result")}
              </p>
              <VerdictCard result={initial} messages={messages} origin={origin} />
            </>
          ) : null
        }
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

      {/* One delegated listener for every copy-link control, now and later. */}
      <CopyLinkScript />
    </Shell>
  );
}
