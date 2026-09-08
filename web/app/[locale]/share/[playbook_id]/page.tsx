import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { LOCALES, LOCALE_NAMES, LOCALE_TAGS, getMessages, isLocale } from "@/i18n";
import { getSharePage, listShareIds } from "@/lib/playbooks";
import { ogImagePath, sharePath } from "@/lib/share";

/**
 * The page a share link lands on: one scam scenario, explained, with a way to
 * check your own message. Static, in all four languages, for every playbook
 * and for each band as the fallback when a verdict matched no playbook.
 *
 * Everything it says comes from the playbook's own YAML and the shared i18n
 * table, the same files the verdict card reads, so a card and the page it
 * links to cannot drift apart.
 */

export const dynamicParams = false;

export function generateStaticParams() {
  return listShareIds().map((playbook_id) => ({ playbook_id }));
}

type Params = Promise<{ locale: string; playbook_id: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale, playbook_id } = await params;
  if (!isLocale(locale)) return {};
  const page = getSharePage(playbook_id, locale);
  if (!page) return {};
  const { t } = getMessages(locale);

  const title = `${page.title} — ${t("app.name")}`;
  const description = page.summary ?? page.redFlags[0] ?? t("home.lead");
  const image = ogImagePath(page.id, locale);
  const configured = process.env.SAQBOL_SITE_URL;

  return {
    title,
    description,
    ...(configured ? { metadataBase: new URL(configured) } : {}),
    alternates: {
      canonical: sharePath(locale, page.id),
      languages: Object.fromEntries(LOCALES.map((l) => [LOCALE_TAGS[l], sharePath(l, page.id)])),
    },
    openGraph: {
      title,
      description,
      type: "article",
      siteName: t("app.name"),
      locale: LOCALE_TAGS[locale].replace("-", "_"),
      url: sharePath(locale, page.id),
      images: [{ url: image, width: 1200, height: 630, alt: page.title }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [image],
    },
  };
}

export default async function SharePage({ params }: { params: Params }) {
  const { locale, playbook_id } = await params;
  if (!isLocale(locale)) notFound();
  const page = getSharePage(playbook_id, locale);
  if (!page) notFound();
  const { t } = getMessages(locale);

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
              href={sharePath(option, page.id)}
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
        <article
          data-band={page.band}
          className="overflow-hidden rounded-2xl border border-line bg-surface"
        >
          <header
            className="border-b px-5 py-5 sm:px-6"
            style={{ background: "var(--band-bg)", borderColor: "var(--band-line)" }}
          >
            <span
              className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide"
              style={{ borderColor: "var(--band-line)", color: "var(--band-fg)" }}
            >
              {page.kind === "playbook" ? t("card.playbook") : t(`band.${page.band}.label`)}
            </span>
            <h1
              className="mt-2 text-balance text-2xl font-semibold tracking-tight sm:text-3xl"
              style={{ color: "var(--band-fg)" }}
            >
              {page.title}
            </h1>
            {page.summary && (
              <p className="mt-2 max-w-prose text-pretty text-[0.9375rem] leading-relaxed text-ink/85">
                {page.summary}
              </p>
            )}
          </header>

          {page.redFlags.length > 0 && (
            <div className="px-5 py-5 sm:px-6">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
                {t("share.page.red_flags")}
              </h2>
              <ul className="mt-3 space-y-2.5">
                {page.redFlags.map((flag, i) => (
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
          )}

          <div
            className="border-t px-5 py-5 sm:px-6"
            style={{ borderColor: "var(--band-line)", background: "var(--band-bg)" }}
          >
            <h2
              className="text-xs font-semibold uppercase tracking-wider"
              style={{ color: "var(--band-fg)" }}
            >
              {t("card.action")}
            </h2>
            <p className="mt-2 max-w-prose text-pretty text-[1.0625rem] leading-relaxed text-ink">
              {page.action}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
              <a
                href={`tel:${page.hotline}`}
                className="inline-flex min-h-11 items-center rounded-xl px-5 py-2.5 text-base font-semibold text-bg no-underline"
                style={{ background: "var(--band-fg)" }}
              >
                {t("card.call", { hotline: page.hotline })}
              </a>
              {page.hotlineLabel && (
                <span className="text-[0.875rem] text-muted">{page.hotlineLabel}</span>
              )}
            </div>
          </div>

          {page.fellBack && (
            <p className="border-t border-line px-5 py-2.5 text-[0.75rem] text-muted sm:px-6">
              {t("footer.fallback")}
            </p>
          )}
        </article>

        <section className="mt-8 rounded-2xl border border-line bg-raised px-5 py-5 sm:px-6">
          <p className="max-w-prose text-pretty text-[0.9375rem] leading-relaxed text-ink">
            {t("share.page.lead")}
          </p>
          <Link
            href={`/${locale}`}
            className="mt-4 inline-flex min-h-11 items-center rounded-xl bg-ink px-5 py-2.5 text-base font-semibold text-bg no-underline"
          >
            {t("share.page.check")}
          </Link>
        </section>
      </main>

      <footer className="mt-12 border-t border-line pt-5 text-[0.8125rem] leading-relaxed text-muted">
        <p className="max-w-prose">{t("footer.disclaimer")}</p>
      </footer>
    </div>
  );
}
