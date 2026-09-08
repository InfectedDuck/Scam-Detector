import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  ActionBlock,
  FallbackNote,
  RedFlags,
  ScenarioHeader,
  telHref,
} from "@/components/Scenario";
import { Shell } from "@/components/Shell";
import { LOCALES, LOCALE_TAGS, getMessages, isLocale } from "@/i18n";
import { getLibraryEntry, listPlaybookIds } from "@/lib/playbooks";
import { libraryPath, ogImagePath } from "@/lib/share";

/**
 * One scenario in full (T305): what the share page says, plus how the script
 * unfolds stage by stage, every number worth calling, and where the
 * description came from. Static for every playbook in every locale; the text
 * is the playbook's own YAML through lib/playbooks.ts, so this page, the
 * share page and the verdict card cannot disagree.
 */

export const dynamicParams = false;

export function generateStaticParams() {
  return listPlaybookIds().map((id) => ({ id }));
}

type Params = Promise<{ locale: string; id: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale, id } = await params;
  if (!isLocale(locale)) return {};
  const entry = getLibraryEntry(id, locale);
  if (!entry) return {};
  const { t } = getMessages(locale);

  const title = `${entry.title} — ${t("app.name")}`;
  const description = entry.summary ?? entry.redFlags[0] ?? t("library.meta.description");
  const image = ogImagePath(entry.id, locale);
  const configured = process.env.SAQBOL_SITE_URL;

  return {
    title,
    description,
    ...(configured ? { metadataBase: new URL(configured) } : {}),
    alternates: {
      canonical: libraryPath(locale, entry.id),
      languages: Object.fromEntries(
        LOCALES.map((l) => [LOCALE_TAGS[l], libraryPath(l, entry.id)]),
      ),
    },
    openGraph: {
      title,
      description,
      type: "article",
      siteName: t("app.name"),
      locale: LOCALE_TAGS[locale].replace("-", "_"),
      url: libraryPath(locale, entry.id),
      images: [{ url: image, width: 1200, height: 630, alt: entry.title }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [image],
    },
  };
}

export default async function PlaybookPage({ params }: { params: Params }) {
  const { locale, id } = await params;
  if (!isLocale(locale)) notFound();
  const entry = getLibraryEntry(id, locale);
  if (!entry) notFound();
  const { t } = getMessages(locale);

  // The headline number is already the button; list the rest.
  const otherHotlines = entry.hotlines.filter((line) => line.number !== entry.hotline);

  return (
    <Shell locale={locale} href={(option) => libraryPath(option, entry.id)}>
      <p className="text-[0.8125rem] text-muted">
        <Link href={libraryPath(locale)} prefetch={false} className="no-underline hover:underline">
          {t("library.title")}
        </Link>
        <span aria-hidden="true"> / </span>
        <span>{t(`library.region.${entry.region}`)}</span>
      </p>

      <article
        data-band={entry.band}
        className="mt-3 overflow-hidden rounded-2xl border border-line bg-surface"
      >
        <ScenarioHeader kicker={t("card.playbook")} title={entry.title} summary={entry.summary} />

        <RedFlags title={t("share.page.red_flags")} flags={entry.redFlags} />

        {entry.stages.length > 0 && (
          <section className="border-t border-line px-5 py-5 sm:px-6">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
              {t("library.stages")}
            </h2>
            <ol className="ms-1.5 mt-4 border-s border-line">
              {entry.stages.map((stage) => (
                <li key={stage.key} className="relative ps-5 pb-5 last:pb-0">
                  <span
                    aria-hidden="true"
                    className="absolute -start-[5px] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-surface"
                    style={{ background: "var(--band-fg)" }}
                  />
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted">
                    {stage.label}
                  </p>
                  <p className="mt-1 max-w-prose text-pretty text-[0.9375rem] leading-relaxed text-ink">
                    {stage.text}
                  </p>
                </li>
              ))}
            </ol>
          </section>
        )}

        <ActionBlock
          t={t}
          action={entry.action}
          hotline={entry.hotline}
          hotlineLabel={entry.hotlineLabel}
        >
          {otherHotlines.length > 0 && (
            <div className="mt-5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">
                {t("library.hotlines")}
              </h3>
              <ul className="mt-2 space-y-1.5">
                {otherHotlines.map((line) => (
                  <li
                    key={`${line.number} ${line.name}`}
                    className="flex flex-wrap items-baseline gap-x-3 text-[0.9375rem] leading-snug"
                  >
                    <a
                      href={`tel:${telHref(line.number)}`}
                      className="font-semibold tabular-nums text-ink no-underline"
                    >
                      {line.number}
                    </a>
                    <span className="min-w-0 text-muted">{line.label ?? line.name}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </ActionBlock>

        {entry.sources.length > 0 && (
          <section className="border-t border-line px-5 py-5 sm:px-6">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
              {t("library.sources")}
            </h2>
            <ul className="mt-3 space-y-2">
              {entry.sources.map((url) => (
                <li key={url} className="text-[0.8125rem] leading-snug">
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="break-all text-muted underline decoration-line underline-offset-4 hover:text-ink"
                  >
                    {url}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        )}

        {entry.fellBack && <FallbackNote text={t("footer.fallback")} />}
      </article>

      <section className="mt-8 rounded-2xl border border-line bg-raised px-5 py-5 sm:px-6">
        <p className="max-w-prose text-pretty text-[0.9375rem] leading-relaxed text-ink">
          {t("share.page.lead")}
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3">
          <Link
            href={`/${locale}`}
            className="inline-flex min-h-11 items-center rounded-xl bg-ink px-5 py-2.5 text-base font-semibold text-bg no-underline"
          >
            {t("share.page.check")}
          </Link>
          <Link
            href={libraryPath(locale)}
            prefetch={false}
            className="text-[0.9375rem] font-medium text-ink underline underline-offset-4"
          >
            {t("library.all")}
          </Link>
        </div>
      </section>
    </Shell>
  );
}
