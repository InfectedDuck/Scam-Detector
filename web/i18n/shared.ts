import "server-only";

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { parse } from "yaml";

import { DEFAULT_LOCALE, LOCALES, type Locale } from "./locales";

/**
 * The web reads the same i18n files as the backend (T301). Every string a
 * verdict shows — band names, indicator labels, stage descriptions, generic
 * advice, hotline names — comes from `src/saqbol/i18n/{locale}.yaml`, and the
 * advice attached to a playbook comes from that playbook's own YAML. Nothing
 * user-facing about a verdict is authored in web/.
 *
 * Both directories are resolved relative to `web/` by default so `next dev`,
 * `next build` and `next start` work from a checkout. A container that copies
 * only `web/` sets SAQBOL_I18N_DIR and SAQBOL_PLAYBOOKS_DIR instead.
 *
 * Gaps: kk.yaml marks untranslated strings as `null` with a `# TODO-kk`
 * comment, and playbooks carry translations for some languages only. The
 * backend falls back to Russian and says so in the card footer, so the loader
 * does the same and reports which keys fell back.
 */

const I18N_DIR =
  process.env.SAQBOL_I18N_DIR ?? path.resolve(process.cwd(), "..", "src", "saqbol", "i18n");
const PLAYBOOKS_DIR =
  process.env.SAQBOL_PLAYBOOKS_DIR ??
  path.resolve(process.cwd(), "..", "src", "saqbol", "playbooks", "data");

/** Values the YAML uses to mean "not translated yet". */
function isMissing(value: unknown): value is null | undefined | "" | "..." {
  return value === null || value === undefined || value === "" || value === "...";
}

/** `{ band: { scam: { label: "x" } } }` → `{ "band.scam.label": "x" }` */
function flatten(node: unknown, prefix: string, out: Map<string, string | null>) {
  if (node !== null && typeof node === "object" && !Array.isArray(node)) {
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      flatten(value, prefix ? `${prefix}.${key}` : key, out);
    }
    return;
  }
  if (isMissing(node)) {
    out.set(prefix, null);
  } else if (typeof node === "string" || typeof node === "number") {
    out.set(prefix, String(node));
  }
}

// -------------------------------------------------------------- i18n yaml --

type Table = Map<string, string | null>;

let tables: Partial<Record<Locale, Table>> | null = null;

function loadTables(): Record<Locale, Table> {
  // Re-read on every request in development so a yaml edit shows up on
  // refresh; cache for the life of the process in production.
  if (tables && process.env.NODE_ENV === "production") return tables as Record<Locale, Table>;

  const loaded: Partial<Record<Locale, Table>> = {};
  for (const locale of LOCALES) {
    const file = path.join(I18N_DIR, `${locale}.yaml`);
    const table: Table = new Map();
    flatten(parse(readFileSync(file, "utf8")), "", table);
    loaded[locale] = table;
  }
  tables = loaded;
  return loaded as Record<Locale, Table>;
}

export interface SharedStrings {
  readonly locale: Locale;
  /** The string in this locale, the Russian one if this locale has a gap, or undefined. */
  get(key: string): string | undefined;
  /** True when `get(key)` had to fall back to Russian. */
  isFallback(key: string): boolean;
}

export function getSharedStrings(locale: Locale): SharedStrings {
  const all = loadTables();
  const own = all[locale];
  const base = all[DEFAULT_LOCALE];

  return {
    locale,
    get(key) {
      const value = own.get(key);
      if (typeof value === "string") return value;
      const fallback = base.get(key);
      return typeof fallback === "string" ? fallback : undefined;
    },
    isFallback(key) {
      return locale !== DEFAULT_LOCALE && typeof own.get(key) !== "string" && base.has(key);
    },
  };
}

// ---------------------------------------------------------- playbook yaml --

export interface PlaybookStrings {
  id: string;
  /** Locale → name, for the locales the playbook has been translated into. */
  name: Partial<Record<Locale, string>>;
  actionKey: string;
  /** Locale → advice, same coverage rule as `name`. */
  action: Partial<Record<Locale, string>>;
  hotline: string;
}

let playbooks: Map<string, PlaybookStrings> | null = null;

function pickLocales(node: unknown): Partial<Record<Locale, string>> {
  const out: Partial<Record<Locale, string>> = {};
  if (node === null || typeof node !== "object") return out;
  for (const locale of LOCALES) {
    const value = (node as Record<string, unknown>)[locale];
    if (!isMissing(value) && typeof value === "string") out[locale] = value;
  }
  return out;
}

export function loadPlaybooks(): Map<string, PlaybookStrings> {
  if (playbooks && process.env.NODE_ENV === "production") return playbooks;

  const loaded = new Map<string, PlaybookStrings>();
  for (const entry of readdirSync(PLAYBOOKS_DIR)) {
    if (!entry.endsWith(".yaml")) continue;
    const doc = parse(readFileSync(path.join(PLAYBOOKS_DIR, entry), "utf8")) as Record<
      string,
      unknown
    >;
    const id = String(doc.id ?? entry.replace(/\.yaml$/, ""));
    const action = (doc.action ?? {}) as Record<string, unknown>;
    loaded.set(id, {
      id,
      name: pickLocales(doc.name),
      actionKey: String(action.key ?? ""),
      action: pickLocales(action),
      hotline: String(doc.hotline ?? ""),
    });
  }
  playbooks = loaded;
  return loaded;
}
