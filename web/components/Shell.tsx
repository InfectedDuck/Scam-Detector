import Link from "next/link";
import type { ReactNode } from "react";

import { LOCALES, LOCALE_NAMES, getMessages, type Locale } from "@/i18n";
import { libraryPath, statsPath } from "@/lib/share";

/**
 * The chrome every page shares: the name, the language switcher, the
 * disclaimer, and the two links that lead away from a verdict (the scenario
 * library and the public stats).
 *
 * A server component. `href` maps a locale to this same page in that
 * language, so the switcher never loses its place.
 */
export function Shell({
  locale,
  href,
  note,
  children,
}: {
  locale: Locale;
  /** The same page in another language, for the switcher. */
  href: (locale: Locale) => string;
  /** One emphasised line above the disclaimer, such as the mock-data banner. */
  note?: string;
  children: ReactNode;
}) {
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
              href={href(option)}
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

      <main className="mt-8 flex-1">{children}</main>

      <footer className="mt-12 border-t border-line pt-5 text-[0.8125rem] leading-relaxed text-muted">
        {note && <p className="mb-2 font-medium text-ink">{note}</p>}
        <p className="max-w-prose">{t("footer.disclaimer")}</p>
        <nav aria-label={t("nav.more")} className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
          <Link
            href={libraryPath(locale)}
            prefetch={false}
            className="font-medium text-ink no-underline hover:underline"
          >
            {t("nav.library")}
          </Link>
          <Link
            href={statsPath(locale)}
            prefetch={false}
            className="font-medium text-ink no-underline hover:underline"
          >
            {t("nav.stats")}
          </Link>
        </nav>
      </footer>
    </div>
  );
}
