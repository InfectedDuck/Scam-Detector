import { readFileSync } from "node:fs";
import path from "node:path";
import { ImageResponse } from "next/og";
import type { NextRequest } from "next/server";

import { getMessages, isLocale, type Locale } from "@/i18n";
import { getSharePage } from "@/lib/playbooks";
import { track } from "@/lib/track";
import type { Band } from "@/lib/types";

/**
 * The Open Graph image for a share page: 1200x630, dark, the playbook name,
 * the word SaqBol, the band colour. Requested as
 * `/og/<playbook_id>.png?locale=<locale>`; the `.png` keeps the URL out of the
 * locale redirect and tells a preview fetcher what it is getting.
 *
 * The bundled Noto Sans subset (app/og/fonts, SIL OFL 1.1) covers Latin and
 * Cyrillic, including the Kazakh letters, so Russian, Kazakh and English render
 * with no network. Chinese glyphs are outside the subset; for those the
 * renderer fetches Noto Sans SC from Google Fonts on demand.
 */

/** The dark-scheme band colours from app/globals.css. */
const ACCENT: Record<Band, string> = {
  scam: "#ff9d9d",
  suspicious: "#f6c250",
  unsure: "#c3b0f5",
  likely_safe: "#6ede93",
};

const BG = "#0a0c0f";
const INK = "#e7e9ee";
const MUTED = "#969dab";

let fontCache: { regular: Buffer; bold: Buffer } | null = null;

function fonts() {
  if (fontCache) return fontCache;
  const dir = path.join(process.cwd(), "app", "og", "fonts");
  fontCache = {
    regular: readFileSync(path.join(dir, "NotoSans-Regular.ttf")),
    bold: readFileSync(path.join(dir, "NotoSans-Bold.ttf")),
  };
  return fontCache;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ playbook_id: string }> },
) {
  const { playbook_id } = await params;
  const id = playbook_id.replace(/\.png$/i, "");
  const requested = request.nextUrl.searchParams.get("locale") ?? "ru";
  const locale: Locale = isLocale(requested) ? requested : "ru";

  const page = getSharePage(id, locale);
  if (!page) return new Response("Not found", { status: 404 });

  const { t } = getMessages(locale);
  const accent = ACCENT[page.band];
  const kicker = page.kind === "playbook" ? t("card.playbook") : t(`band.${page.band}.label`);
  const hotline = `${page.hotlineLabel ?? t("hotline.generic")}: ${page.hotline}`;
  const titleSize = page.title.length <= 36 ? 72 : page.title.length <= 64 ? 60 : 50;

  track("og_image", { id: page.id, kind: page.kind, locale });

  const { regular, bold } = fonts();

  return new ImageResponse(
    (
      <div
        style={{
          width: 1200,
          height: 630,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "64px 72px 56px",
          background: BG,
          color: INK,
          fontFamily: "Noto Sans",
          position: "relative",
        }}
      >
        <div
          style={{ position: "absolute", left: 0, top: 0, width: 1200, height: 14, background: accent }}
        />

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ width: 18, height: 18, borderRadius: 999, background: accent }} />
          <div style={{ fontSize: 40, fontWeight: 700, letterSpacing: -0.5 }}>SaqBol</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 26, maxWidth: 1056 }}>
          <div style={{ display: "flex" }}>
            <div
              style={{
                border: `3px solid ${accent}`,
                color: accent,
                borderRadius: 999,
                padding: "8px 24px",
                fontSize: 26,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: 2,
              }}
            >
              {kicker}
            </div>
          </div>
          <div
            style={{
              fontSize: titleSize,
              fontWeight: 700,
              lineHeight: 1.15,
              letterSpacing: -1,
              textWrap: "balance",
            }}
          >
            {page.title}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 28 }}>
          <div style={{ display: "flex", color: INK }}>{hotline}</div>
          <div style={{ display: "flex", color: MUTED, fontSize: 24 }}>{t("app.tagline")}</div>
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
      fonts: [
        { name: "Noto Sans", data: regular, weight: 400, style: "normal" },
        { name: "Noto Sans", data: bold, weight: 700, style: "normal" },
      ],
      headers: {
        "cache-control": "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800",
      },
    },
  );
}
