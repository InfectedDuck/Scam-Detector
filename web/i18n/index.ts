import "server-only";

import uiEn from "./ui.en.json";
import uiRu from "./ui.ru.json";
import uiKk from "./ui.kk.json";
import uiZh from "./ui.zh.json";
import type { Locale } from "./locales";
import { getSharedStrings, loadPlaybooks, type SharedStrings } from "./shared";
import type { Band } from "@/lib/types";

export {
  LOCALES,
  DEFAULT_LOCALE,
  LOCALE_NAMES,
  LOCALE_TAGS,
  isLocale,
  negotiateLocale,
} from "./locales";
export type { Locale } from "./locales";

/**
 * Two layers of strings.
 *
 * `ui.*.json` is page chrome that only the website has: the tagline, the paste
 * box, sample names, the "how this was decided" panel. English is the key
 * source of truth for it, so a key missing from another locale fails to
 * compile.
 *
 * Everything a verdict says comes from the backend's own files through
 * ./shared.ts, so the site, the bot and the API cannot drift apart on what a
 * band is called or what advice a playbook gives. UI keys use prefixes the
 * shared table does not (app, home, form, sample, card, severity, nav, mock),
 * so a lookup falls through cleanly from one layer to the other.
 */
export type UiKey = keyof typeof uiEn;

const UI: Record<Locale, Record<UiKey, string>> = { en: uiEn, ru: uiRu, kk: uiKk, zh: uiZh };

export type T = (key: string, params?: Record<string, string | number>) => string;

export interface Resolved {
  text: string;
  /** The locale had no translation, so this is the Russian text. */
  fellBack: boolean;
}

export interface Messages {
  readonly locale: Locale;
  /**
   * UI layer first, then the shared table, then the key itself. The last is
   * deliberate: an untranslated `indicator.X9.something` on screen is a bug
   * report, whereas an empty span is silence.
   */
  t: T;
  /** Whether a shared key is being shown in Russian because this locale lacks it. */
  isFallback(key: string): boolean;
  playbookName(playbookId: string): Resolved | undefined;
  /**
   * The advice for a verdict. A playbook always brings its own text (contracts
   * §3); the generic per-band text is only for verdicts with no playbook or a
   * key nothing matches.
   */
  actionText(actionKey: string, band: Band): Resolved;
  /** "Полиция", "eGov" … for a hotline number, from the shared table. */
  hotlineLabel(number: string): string | undefined;
}

function interpolate(raw: string, params?: Record<string, string | number>): string {
  if (!params) return raw;
  return raw.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}

export function getMessages(locale: Locale): Messages {
  const ui = UI[locale] as Record<string, string | undefined>;
  const shared: SharedStrings = getSharedStrings(locale);
  const playbooks = loadPlaybooks();

  const t: T = (key, params) => interpolate(ui[key] ?? shared.get(key) ?? key, params);

  const pick = (table: Partial<Record<Locale, string>>): Resolved | undefined => {
    const own = table[locale];
    if (own) return { text: own, fellBack: false };
    const ru = table.ru;
    return ru ? { text: ru, fellBack: locale !== "ru" } : undefined;
  };

  return {
    locale,
    t,
    isFallback: (key) => shared.isFallback(key),

    playbookName(playbookId) {
      const playbook = playbooks.get(playbookId);
      return playbook ? pick(playbook.name) : undefined;
    },

    actionText(actionKey, band) {
      for (const playbook of playbooks.values()) {
        if (playbook.actionKey === actionKey) {
          const resolved = pick(playbook.action);
          if (resolved) return resolved;
        }
      }
      const generic = `action.generic.${band}`;
      return {
        text: shared.get(generic) ?? shared.get(actionKey) ?? actionKey,
        fellBack: shared.isFallback(generic),
      };
    },

    hotlineLabel(number) {
      const kind = HOTLINE_KIND[number];
      return kind ? shared.get(`hotline.${kind}`) : shared.get("hotline.generic");
    },
  };
}

/** Which `hotline.*` label a number gets. Anything else is `hotline.generic`. */
const HOTLINE_KIND: Record<string, string> = {
  "102": "police",
  "110": "police",
  "1414": "egov",
  "96110": "cn_police",
};
