import "server-only";

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { parse } from "yaml";

import { LOCALES, getMessages, type Locale } from "@/i18n";
import { loadPlaybooks } from "@/i18n/shared";
import type { Band } from "./types";
import { BANDS, isBand } from "./share";

/**
 * What a share page says about a playbook.
 *
 * Names, advice and the hotline come through the same loader the verdict card
 * uses (i18n/shared.ts and `getMessages`), so a share page and the card that
 * linked to it can never disagree on what a scenario is called. The loader
 * does not keep the red flags or the summary, because no verdict shows them;
 * this module reads those two blocks from the same YAML files, with the same
 * directory rule and the same Russian fallback.
 */

const PLAYBOOKS_DIR =
  process.env.SAQBOL_PLAYBOOKS_DIR ??
  path.resolve(process.cwd(), "..", "src", "saqbol", "playbooks", "data");

interface Extras {
  summary: Partial<Record<Locale, string>>;
  redFlags: Partial<Record<Locale, string[]>>;
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
    loaded.set(id, { summary, redFlags });
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
