"use server";

import type { ReactNode } from "react";

import { ApiError, fetchVerdict } from "@/lib/api";
import { sniffImageType } from "@/lib/image";
import { siteOrigin } from "@/lib/site";
import { track } from "@/lib/track";
import { MAX_IMAGE_BYTES, MAX_TEXT_CHARS, type Verdict } from "@/lib/types";
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
  const hasText = text.trim().length > 0;

  // The screenshot, if any. Checked by size and by its first bytes: the type
  // the browser attached is a hint, not a fact.
  const upload = formData.get("image");
  let image_b64: string | null = null;
  if (upload instanceof Blob && upload.size > 0) {
    if (upload.size > MAX_IMAGE_BYTES) {
      track("image_refused", { locale: safeLocale, reason: "too_large" });
      return <Notice>{t("form.image.too_large")}</Notice>;
    }
    const bytes = new Uint8Array(await upload.arrayBuffer());
    if (!sniffImageType(bytes)) {
      track("image_refused", { locale: safeLocale, reason: "wrong_type" });
      return <Notice>{t("form.image.wrong_type")}</Notice>;
    }
    image_b64 = Buffer.from(bytes).toString("base64");
  }

  if (!hasText && !image_b64) return <Notice>{t("form.error.empty")}</Notice>;
  if (text.length > MAX_TEXT_CHARS) {
    return <Notice>{t("form.error.too_long", { max: MAX_TEXT_CHARS })}</Notice>;
  }

  const origin = await siteOrigin();

  try {
    const result = await fetchVerdict({ text: hasText ? text : null, image_b64, surface: "web" });
    track("verdict", verdictProps(safeLocale, result.verdict, hasText, image_b64 !== null));
    return <VerdictCard result={result} messages={messages} origin={origin} />;
  } catch (error) {
    if (error instanceof ApiError && error.code === "image_not_supported") {
      // Screenshots are not read yet. Say so calmly, and if there was text as
      // well, still answer for the text.
      track("image_unsupported", { locale: safeLocale, with_text: hasText });
      const notice = <Notice tone="info">{t("form.image.unsupported")}</Notice>;
      if (!hasText) return notice;
      try {
        const result = await fetchVerdict({ text, surface: "web" });
        track("verdict", verdictProps(safeLocale, result.verdict, true, false));
        return (
          <>
            {notice}
            <div className="mt-4">
              <VerdictCard result={result} messages={messages} origin={origin} />
            </div>
          </>
        );
      } catch (retryError) {
        return <Notice>{t(failureKey(retryError))}</Notice>;
      }
    }
    track("verdict_failed", {
      locale: safeLocale,
      code: error instanceof ApiError ? error.code : "unknown",
    });
    return <Notice>{t(failureKey(error))}</Notice>;
  }
}

function failureKey(error: unknown): string {
  return error instanceof ApiError && error.code === "rate_limited"
    ? "form.error.rate_limited"
    : "form.error.failed";
}

function verdictProps(locale: Locale, verdict: Verdict, hasText: boolean, hasImage: boolean) {
  return {
    locale,
    surface: "web",
    check_id: verdict.check_id,
    band: verdict.band,
    playbook_id: verdict.playbook_id,
    cached: verdict.cached,
    latency_ms: verdict.latency_ms,
    has_text: hasText,
    has_image: hasImage,
  };
}

function Notice({ children, tone = "error" }: { children: ReactNode; tone?: "error" | "info" }) {
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      className={
        tone === "error"
          ? "rounded-xl border border-line bg-surface px-4 py-3 text-[0.9375rem] text-muted"
          : "rounded-xl border border-line bg-raised px-4 py-3 text-[0.9375rem] leading-relaxed text-ink"
      }
    >
      {children}
    </p>
  );
}
