"use server";

import type { ReactNode } from "react";

import { ApiError, fetchVerdict } from "@/lib/api";
import { MAX_TEXT_CHARS } from "@/lib/types";
import { getMessages, isLocale, type Locale } from "@/i18n";
import { VerdictCard } from "@/components/VerdictCard";

/**
 * The action returns rendered output, not data.
 *
 * That keeps VerdictCard, lib/highlight.ts and all four dictionaries on the
 * server: the browser receives the finished card as an RSC payload rather than
 * the JavaScript needed to build one. It is also progressively enhanced, so the
 * form still works with scripting off.
 *
 * If this ever needs to become a data-returning action, the change is local:
 * return `result` instead of the element and render the card in the client
 * component.
 */
export async function analyzeAction(
  locale: Locale,
  _previous: ReactNode,
  formData: FormData,
): Promise<ReactNode> {
  const safeLocale: Locale = isLocale(locale) ? locale : "ru";
  const messages = getMessages(safeLocale);
  const { t } = messages;

  const text = String(formData.get("text") ?? "");

  if (text.trim().length === 0) return <Notice>{t("form.error.empty")}</Notice>;
  if (text.length > MAX_TEXT_CHARS) {
    return <Notice>{t("form.error.too_long", { max: MAX_TEXT_CHARS })}</Notice>;
  }

  try {
    const result = await fetchVerdict({ text, surface: "web" });
    return <VerdictCard result={result} messages={messages} />;
  } catch (error) {
    const key =
      error instanceof ApiError && error.code === "rate_limited"
        ? "form.error.rate_limited"
        : "form.error.failed";
    return <Notice>{t(key)}</Notice>;
  }
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="rounded-xl border border-line bg-surface px-4 py-3 text-[0.9375rem] text-muted"
    >
      {children}
    </p>
  );
}
