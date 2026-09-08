import "server-only";

import { headers } from "next/headers";

/**
 * The absolute origin of this deployment, for share links that leave the page.
 *
 * `SAQBOL_SITE_URL` wins when set; the share page also uses it as
 * `metadataBase` for its Open Graph image, which has no request to read
 * headers from. Otherwise the origin comes from the request, honouring the
 * `x-forwarded-*` headers a reverse proxy sets.
 */
export async function siteOrigin(): Promise<string> {
  const configured = process.env.SAQBOL_SITE_URL;
  if (configured) return configured.replace(/\/+$/, "");

  try {
    const h = await headers();
    const host = h.get("x-forwarded-host") ?? h.get("host");
    if (host) {
      const forwardedProto = h.get("x-forwarded-proto")?.split(",")[0]?.trim();
      const local = /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(host);
      const proto = forwardedProto ?? (local ? "http" : "https");
      return `${proto}://${host}`;
    }
  } catch {
    // Outside a request (a static render): fall through to the default.
  }
  return "http://localhost:3000";
}
