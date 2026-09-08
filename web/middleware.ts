import { NextResponse, type NextRequest } from "next/server";

import { isLocale, negotiateLocale } from "@/i18n/locales";

/**
 * Every page lives under /{locale}. A request without one is redirected to the
 * best match from Accept-Language, defaulting to Russian.
 *
 * Imports come from i18n/locales.ts rather than i18n/index.ts so the four
 * dictionaries stay out of the edge bundle.
 */
export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const first = pathname.split("/")[1];
  if (isLocale(first)) return NextResponse.next();

  const locale = negotiateLocale(request.headers.get("accept-language"));
  const url = request.nextUrl.clone();
  url.pathname = `/${locale}${pathname === "/" ? "" : pathname}`;
  url.search = search;
  return NextResponse.redirect(url);
}

export const config = {
  // Everything except Next internals and anything that looks like a file.
  matcher: ["/((?!_next/|api/|favicon\\.ico|robots\\.txt|.*\\.[^/]+$).*)"],
};
