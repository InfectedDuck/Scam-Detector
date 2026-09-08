import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Shell } from "@/components/Shell";
import { LOCALES, LOCALE_TAGS, getMessages, isLocale } from "@/i18n";
import { REGIONS, listLibrary } from "@/lib/playbooks";
import { libraryPath } from "@/lib/share";

/**
 * The scenario library (T305): every playbook, grouped by who it targets,
 * each linking to its own page. Static in all four languages; a new playbook
 * needs a rebuild, the same as the share pages.
 */

export const dynamicParams = false;

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const { t } = getMessages(locale);

  const title = `${t("library.title")} — ${t("app.name")}`;
  const description = t("library.meta.description");
  const configured = process.env.SAQBOL_SITE_URL;

  return {
    title,
    description,
    ...(configured ? { metadataBase: new URL(configured) } : {}),
    alternates: {
      canonical: libraryPath(locale),
      languages: Object.fromEntries(LOCALES.map((l) => [LOCALE_TAGS[l], libraryPath(l)])),
    },
    openGraph: {
      title,
      description,
      type: "website",
      siteName: t("app.name"),
      locale: LOCALE_TAGS[locale].replace("-", "_"),
      url: libraryPath(locale),
    },
  };
}

export default async function LibraryPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const { t } = getMessages(locale);
  const entries = listLibrary(locale);

  return (
    <Shell locale={locale} href={libraryPath}>
      <h1 className="text-balance text-2xl font-semibold tracking-tight sm:text-3xl">
        {t("library.title")}
      </h1>
      <p className="mt-3 max-w-prose text-pretty text-[0.9375rem] leading-relaxed text-muted">
        {t("library.lead")}
      </p>

      {REGIONS.map((region) => {
        const group = entries.filter((entry) => entry.region === region);
        if (group.length === 0) return null;
        return (
          <section key={region} className="mt-10">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
              {t(`library.region.${region}`)}
            </h2>
            <ul className="mt-3 grid gap-3">
              {group.map((entry) => (
                <li key={entry.id} data-band={entry.band}>
                  <Link
                    href={libraryPath(locale, entry.id)}
                    prefetch={false}
                    className="block rounded-2xl border border-line bg-surface px-5 py-4 no-underline"
                    style={{ borderLeft: "4px solid var(--band-fg)" }}
                  >
                    <span className="block text-[1.0625rem] font-semibold leading-snug text-ink">
                      {entry.title}
                    </span>
                    {entry.summary && (
                      <span className="mt-1.5 block text-pretty text-[0.875rem] leading-relaxed text-muted">
                        {entry.summary}
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        );
      })}

      <section className="mt-10 rounded-2xl border border-line bg-raised px-5 py-5 sm:px-6">
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
    </Shell>
  );
}
