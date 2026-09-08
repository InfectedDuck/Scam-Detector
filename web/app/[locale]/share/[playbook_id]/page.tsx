import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ActionBlock, FallbackNote, RedFlags, ScenarioHeader } from "@/components/Scenario";
import { Shell } from "@/components/Shell";
import { LOCALES, LOCALE_TAGS, getMessages, isLocale } from "@/i18n";
import { getSharePage, listShareIds } from "@/lib/playbooks";
import { libraryPath, ogImagePath, sharePath } from "@/lib/share";

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
    <Shell locale={locale} href={(option) => sharePath(option, page.id)}>
      <article
        data-band={page.band}
        className="overflow-hidden rounded-2xl border border-line bg-surface"
      >
        <ScenarioHeader
          kicker={page.kind === "playbook" ? t("card.playbook") : t(`band.${page.band}.label`)}
          title={page.title}
          summary={page.summary}
        />

        <RedFlags title={t("share.page.red_flags")} flags={page.redFlags} />

        <ActionBlock
          t={t}
          action={page.action}
          hotline={page.hotline}
          hotlineLabel={page.hotlineLabel}
        />

        {page.fellBack && <FallbackNote text={t("footer.fallback")} />}
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
