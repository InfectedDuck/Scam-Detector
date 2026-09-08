/**
 * Locale constants with no dictionary imports, so `middleware.ts` can use them
 * without pulling four JSON files into the edge bundle.
 */

export const LOCALES = ["ru", "kk", "en", "zh"] as const;
export type Locale = (typeof LOCALES)[number];

/**
 * Russian is the default: it is the language most Kazakhstani scam messages
 * arrive in, and the widest-reach starting point for the people this is for.
 */
export const DEFAULT_LOCALE: Locale = "ru";

/** Endonyms, for the switcher. Never translated. */
export const LOCALE_NAMES: Record<Locale, string> = {
  ru: "Русский",
  kk: "Қазақша",
  en: "English",
  zh: "中文",
};

/** Values for the `lang` attribute. */
export const LOCALE_TAGS: Record<Locale, string> = {
  ru: "ru-RU",
  kk: "kk-KZ",
  en: "en",
  zh: "zh-CN",
};

export function isLocale(value: string | undefined): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

/**
 * Pick a locale from an Accept-Language header.
 *
 * Quality-ordered, matched on the primary subtag so `zh-Hans-CN` and `kk-Cyrl`
 * both land somewhere sensible.
 */
export function negotiateLocale(header: string | null): Locale {
  if (!header) return DEFAULT_LOCALE;

  const ranked = header
    .split(",")
    .map((part) => {
      const [tag, ...params] = part.trim().split(";");
      const q = params.find((p) => p.trim().startsWith("q="));
      return { tag: tag.trim().toLowerCase(), q: q ? Number(q.split("=")[1]) || 0 : 1 };
    })
    .filter((entry) => entry.tag.length > 0)
    .sort((a, b) => b.q - a.q);

  for (const { tag } of ranked) {
    const primary = tag.split("-")[0];
    const match = LOCALES.find((locale) => locale === primary);
    if (match) return match;
  }
  return DEFAULT_LOCALE;
}
