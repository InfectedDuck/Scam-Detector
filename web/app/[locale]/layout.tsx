import type { Metadata } from "next";
import { notFound } from "next/navigation";

import "../globals.css";
import { LOCALES, LOCALE_TAGS, getMessages, isLocale } from "@/i18n";

/**
 * The root layout lives inside the [locale] segment: every route passes through
 * it, so it is the one place that can put the right `lang` on <html>. There is
 * deliberately no app/layout.tsx above it.
 */

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

/** Only the four locales exist. Anything else 404s instead of rendering. */
export const dynamicParams = false;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const { t } = getMessages(locale);

  return {
    title: `${t("app.name")} — ${t("app.tagline")}`,
    description: t("home.lead"),
    alternates: {
      canonical: `/${locale}`,
      languages: Object.fromEntries(LOCALES.map((l) => [LOCALE_TAGS[l], `/${l}`])),
    },
    // The palette is media-query driven, so declare support for both and let
    // the browser paint the right chrome before the CSS lands.
    other: { "color-scheme": "light dark" },
  };
}

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f5f7" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0c0f" },
  ],
};

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  return (
    <html lang={LOCALE_TAGS[locale]}>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
