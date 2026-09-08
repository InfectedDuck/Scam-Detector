import type { Locale, T } from "@/i18n";
import type { Band, Verdict } from "./types";

/**
 * The three ways a verdict leaves the page.
 *
 * All of them point at the public share page for the matched playbook, or for
 * the band when nothing matched, and all of them carry a `ref` so an arriving
 * visitor can be attributed to the channel that brought them. None of them
 * carries the user's own message: the text that was checked stays on the
 * device it was pasted on.
 */

export type ShareRef = "wa" | "tg" | "copy";

export interface ShareLinks {
  /** Bare share URL, without a ref. */
  url: string;
  /** What is written into the chat: warning, band, playbook, hotline. */
  message: string;
  whatsapp: string;
  telegram: string;
  /** The URL the copy button puts on the clipboard. */
  copy: string;
}

/** The share page id for a verdict: the playbook, or the band as the fallback. */
export function shareTargetId(verdict: Pick<Verdict, "playbook_id" | "band">): string {
  return verdict.playbook_id ?? verdict.band;
}

export function sharePath(locale: Locale, id: string, ref?: ShareRef): string {
  const base = `/${locale}/share/${encodeURIComponent(id)}`;
  return ref ? `${base}?ref=${ref}` : base;
}

/** The scenario library, or one scenario in it. */
export function libraryPath(locale: Locale, id?: string): string {
  const base = `/${locale}/playbooks`;
  return id ? `${base}/${encodeURIComponent(id)}` : base;
}

export function statsPath(locale: Locale): string {
  return `/${locale}/stats`;
}

/** The Open Graph image for a share page. Ends in .png so it is served as a file. */
export function ogImagePath(id: string, locale: Locale): string {
  return `/og/${encodeURIComponent(id)}.png?locale=${locale}`;
}

export function shareMessage(
  t: T,
  verdict: Pick<Verdict, "band" | "hotline">,
  playbookName: string | undefined,
): string {
  const params = {
    warning: t(`share.warning.${verdict.band}`),
    band: t(`band.${verdict.band}.label`),
    playbook: playbookName ?? "",
    hotline: verdict.hotline,
  };
  return t(playbookName ? "share.message" : "share.message.generic", params);
}

export function shareLinks({
  origin,
  locale,
  verdict,
  playbookName,
  t,
}: {
  origin: string;
  locale: Locale;
  verdict: Pick<Verdict, "playbook_id" | "band" | "hotline">;
  playbookName: string | undefined;
  t: T;
}): ShareLinks {
  const id = shareTargetId(verdict);
  const url = `${origin}${sharePath(locale, id)}`;
  const withRef = (ref: ShareRef) => `${origin}${sharePath(locale, id, ref)}`;
  const message = shareMessage(t, verdict, playbookName);

  return {
    url,
    message,
    whatsapp: `https://wa.me/?text=${encodeURIComponent(`${message}\n${withRef("wa")}`)}`,
    telegram:
      `https://t.me/share/url?url=${encodeURIComponent(withRef("tg"))}` +
      `&text=${encodeURIComponent(message)}`,
    copy: withRef("copy"),
  };
}

export const BANDS: readonly Band[] = ["scam", "suspicious", "unsure", "likely_safe"];

export function isBand(value: string): value is Band {
  return (BANDS as readonly string[]).includes(value);
}
