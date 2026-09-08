import "server-only";

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { parse } from "yaml";

import { LOCALES, getMessages, isKnownHotline, type Locale } from "@/i18n";
import { loadPlaybooks } from "@/i18n/shared";
import type { Band, Stage } from "./types";
import { BANDS, isBand } from "./share";

/**
 * What a share page, and the library, say about a playbook.
 *
 * Names, advice and the hotline come through the same loader the verdict card
 * uses (i18n/shared.ts and `getMessages`), so a share page and the card that
 * linked to it can never disagree on what a scenario is called. The loader
 * does not keep the red flags, the summary, the stages, the sources or the
 * hotline list, because no verdict shows them; this module reads those blocks
 * from the same YAML files, with the same directory rule and the same Russian
 * fallback.
 */

const PLAYBOOKS_DIR =
  process.env.SAQBOL_PLAYBOOKS_DIR ??
  path.resolve(process.cwd(), "..", "src", "saqbol", "playbooks", "data");

/** The two audiences the library is grouped by, in display order. */
export const REGIONS = ["KZ", "CN"] as const;
export type Region = (typeof REGIONS)[number];

/** Contracts §3: the order a script unfolds in. Only the stages present are shown. */
export const STAGE_ORDER: readonly Stage[] = [
  "contact",
  "hook",
  "trust",
  "pressure",
  "extraction",
  "cashout",
];

interface Extras {
  region: Region;
  family: string;
  summary: Partial<Record<Locale, string>>;
  redFlags: Partial<Record<Locale, string[]>>;
  stages: Partial<Record<Stage, Partial<Record<Locale, string>>>>;
  sources: string[];
  hotlines: { name: string; number: string }[];
}

let extras: Map<string, Extras> | null = null;

function loadExtras(): Map<string, Extras> {
  if (extras && process.env.NODE_ENV === "production") return extras;

  const loaded = new Map<string, Extras>();
  for (const entry of readdirSync(PLAYBOOKS_DIR)) {
    if (!entry.endsWith(".yaml")) continue;
    const doc = parse(readFileSync(path.join(PLAYBOOKS_DIR, entry), "utf8")) as Record<
      string,
      unknown
    >;
    const id = String(doc.id ?? entry.replace(/\.yaml$/, ""));

    const summary: Partial<Record<Locale, string>> = {};
    const redFlags: Partial<Record<Locale, string[]>> = {};
    const summaryNode = asRecord(doc.summary);
    const flagsNode = asRecord(doc.red_flags);
    for (const locale of LOCALES) {
      const s = summaryNode[locale];
      if (typeof s === "string" && s.trim() && s !== "...") summary[locale] = s;
      const f = flagsNode[locale];
      if (Array.isArray(f)) {
        const lines = f.filter((x): x is string => typeof x === "string" && x.trim().length > 0);
        if (lines.length > 0) redFlags[locale] = lines;
      }
    }

    const stages: Extras["stages"] = {};
    const stagesNode = asRecord(doc.stages);
    for (const stage of STAGE_ORDER) {
      const texts: Partial<Record<Locale, string>> = {};
      const node = asRecord(stagesNode[stage]);
      for (const locale of LOCALES) {
        const value = node[locale];
        if (typeof value === "string" && value.trim() && value !== "...") texts[locale] = value;
      }
      if (Object.keys(texts).length > 0) stages[stage] = texts;
    }

    const sources = (Array.isArray(doc.sources) ? doc.sources : []).filter(
      (x): x is string => typeof x === "string" && /^https?:\/\//.test(x),
    );

    const hotlines = (Array.isArray(doc.hotlines) ? doc.hotlines : []).flatMap((x) => {
      const node = asRecord(x);
      const name = typeof node.name === "string" ? node.name.trim() : "";
      const number = typeof node.number === "string" ? node.number.trim() : "";
      return number ? [{ name, number }] : [];
    });

    loaded.set(id, {
      // The schema allows two regions; anything else lands with Kazakhstan.
      region: doc.region === "CN" ? "CN" : "KZ",
      family: String(doc.family ?? ""),
      summary,
      redFlags,
      stages,
      sources,
      hotlines,
    });
  }
  extras = loaded;
  return loaded;
}

function asRecord(node: unknown): Record<string, unknown> {
  return node !== null && typeof node === "object" && !Array.isArray(node)
    ? (node as Record<string, unknown>)
    : {};
}

/** Every id a share page exists for: each playbook, then each band as the fallback. */
export function listShareIds(): string[] {
  return [...loadPlaybooks().keys(), ...BANDS];
}

/** Every playbook id, for the library. */
export function listPlaybookIds(): string[] {
  return [...loadPlaybooks().keys()];
}

/** The hotline a band-only share page shows. The KZ single window, or the CN anti-fraud line. */
const DEFAULT_HOTLINE: Record<Locale, string> = { ru: "1414", kk: "1414", en: "1414", zh: "96110" };

export interface SharePage {
  kind: "playbook" | "band";
  id: string;
  /** Colours the page and the Open Graph image. A playbook is a scam scenario by definition. */
  band: Band;
  title: string;
  summary: string | undefined;
  redFlags: string[];
  action: string;
  hotline: string;
  hotlineLabel: string | undefined;
  /** Something above had to be shown in Russian. */
  fellBack: boolean;
}

export function getSharePage(id: string, locale: Locale): SharePage | undefined {
  const messages = getMessages(locale);
  const { t } = messages;

  const playbook = loadPlaybooks().get(id);
  if (playbook) {
    const name = messages.playbookName(id);
    if (!name) return undefined;
    const action = messages.actionText(playbook.actionKey, "scam");
    const own = loadExtras().get(id);

    const summary = own?.summary[locale] ?? own?.summary.ru;
    const redFlags = own?.redFlags[locale] ?? own?.redFlags.ru ?? [];
    const extrasFellBack =
      locale !== "ru" &&
      ((own?.summary[locale] === undefined && own?.summary.ru !== undefined) ||
        (own?.redFlags[locale] === undefined && own?.redFlags.ru !== undefined));

    return {
      kind: "playbook",
      id,
      band: "scam",
      title: name.text,
      summary,
      redFlags,
      action: action.text,
      hotline: playbook.hotline,
      hotlineLabel: messages.hotlineLabel(playbook.hotline),
      fellBack: name.fellBack || action.fellBack || extrasFellBack,
    };
  }

  if (isBand(id)) {
    const action = messages.actionText(`action.generic.${id}`, id);
    const hotline = DEFAULT_HOTLINE[locale];
    return {
      kind: "band",
      id,
      band: id,
      title: t(`band.${id}.title`),
      summary: t(`band.${id}.summary`),
      redFlags: [],
      action: action.text,
      hotline,
      hotlineLabel: messages.hotlineLabel(hotline),
      fellBack:
        messages.isFallback(`band.${id}.title`) ||
        messages.isFallback(`band.${id}.summary`) ||
        action.fellBack,
    };
  }

  return undefined;
}

// ---------------------------------------------------------------- library --

export interface LibraryStage {
  key: Stage;
  /** "contact", "hook" … from the shared table, in this locale. */
  label: string;
  text: string;
  /** The text, or its label, is in Russian because this locale has no translation. */
  fellBack: boolean;
}

export interface LibraryHotline {
  number: string;
  /** As written in the YAML: "Kaspi Bank", "Полиция", a bilingual consulate line. */
  name: string;
  /** The shared table's name for the line, where it has one: "Police", "eGov contact centre". */
  label: string | undefined;
}

/** A share page plus everything the library shows that a share page does not. */
export interface LibraryEntry extends SharePage {
  kind: "playbook";
  region: Region;
  family: string;
  /** In script order, only the stages this playbook describes. */
  stages: LibraryStage[];
  sources: string[];
  hotlines: LibraryHotline[];
}

export function getLibraryEntry(id: string, locale: Locale): LibraryEntry | undefined {
  const page = getSharePage(id, locale);
  if (!page || page.kind !== "playbook") return undefined;
  const own = loadExtras().get(id);
  if (!own) return undefined;
  const messages = getMessages(locale);

  const stages: LibraryStage[] = [];
  for (const key of STAGE_ORDER) {
    const texts = own.stages[key];
    if (!texts) continue;
    const text = texts[locale] ?? texts.ru;
    if (!text) continue;
    const labelKey = `stage.${key}.label`;
    stages.push({
      key,
      label: messages.t(labelKey),
      text,
      fellBack:
        (locale !== "ru" && texts[locale] === undefined) || messages.isFallback(labelKey),
    });
  }

  const hotlines: LibraryHotline[] = own.hotlines.map(({ name, number }) => ({
    number,
    name,
    label: isKnownHotline(number) ? messages.hotlineLabel(number) : undefined,
  }));

  return {
    ...page,
    kind: "playbook",
    region: own.region,
    family: own.family,
    stages,
    sources: own.sources,
    hotlines,
    fellBack: page.fellBack || stages.some((stage) => stage.fellBack),
  };
}

/** Every playbook, Kazakhstan first, in the loader's (filename) order within a region. */
export function listLibrary(locale: Locale): LibraryEntry[] {
  const entries = listPlaybookIds().flatMap((id) => {
    const entry = getLibraryEntry(id, locale);
    return entry ? [entry] : [];
  });
  return REGIONS.flatMap((region) => entries.filter((entry) => entry.region === region));
}
