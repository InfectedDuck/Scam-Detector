import "server-only";

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

import { track } from "./track";

/**
 * Cloudflare Turnstile after the third check in a session (T307).
 *
 * Off unless BOTH `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` are set.
 * With either missing nothing about the form changes and the action verifies
 * nothing: the counter below still ticks, signed with a per-process random
 * key, but nothing reads it. That keeps a checkout with no Cloudflare account
 * working exactly as before.
 *
 * The session counter is an httpOnly, SameSite=Lax cookie holding
 * `<count>.<hmac>`, where the HMAC is SHA-256 over the count keyed with the
 * Turnstile secret. A tampered, malformed or missing cookie reads as 0, which
 * is the same as a fresh session: the API's own per-address daily limit is
 * the backstop, this is only the friction that keeps a script from burning
 * through it. No expiry is set, so the count lives as long as the browser
 * session.
 */

const SITE_KEY = process.env.TURNSTILE_SITE_KEY;
const SECRET_KEY = process.env.TURNSTILE_SECRET_KEY;

export const TURNSTILE_ENABLED = Boolean(SITE_KEY && SECRET_KEY);

/** The public site key, only when the widget should ever be shown. */
export const TURNSTILE_SITE_KEY = TURNSTILE_ENABLED ? SITE_KEY : undefined;

/** Checks a session gets before it is asked to prove it is human. */
export const FREE_CHECKS = 3;

const COOKIE = "saqbol_n";
const VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

const HMAC_KEY = SECRET_KEY ?? randomBytes(32).toString("hex");

function sign(count: number): string {
  return createHmac("sha256", HMAC_KEY).update(String(count)).digest("hex");
}

/** `<count>.<hmac>` → count, or 0 for anything that does not verify. */
export function parseCount(raw: string | undefined): number {
  if (!raw) return 0;
  const match = /^(\d{1,6})\.([0-9a-f]{64})$/.exec(raw);
  if (!match) return 0;
  const count = Number(match[1]);
  const expected = Buffer.from(sign(count), "hex");
  const given = Buffer.from(match[2], "hex");
  return expected.length === given.length && timingSafeEqual(expected, given) ? count : 0;
}

/** How many checks this session has made, from the cookie. */
export async function readCheckCount(): Promise<number> {
  const jar = await cookies();
  return parseCount(jar.get(COOKIE)?.value);
}

/** Record one more successful check. Only a server action may call this. */
export async function bumpCheckCount(secure: boolean): Promise<void> {
  const jar = await cookies();
  const count = Math.min(parseCount(jar.get(COOKIE)?.value) + 1, 999999);
  jar.set(COOKIE, `${count}.${sign(count)}`, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
  });
}

/** Whether a session with this many checks behind it must pass the widget. */
export function challengeRequired(count: number): boolean {
  return TURNSTILE_ENABLED && count >= FREE_CHECKS;
}

/**
 * Ask Cloudflare whether the token the form posted is good.
 *
 * Fails closed: a missing token, a rejected one and a network error all
 * return false. Each is tracked with a reason, none with the token or the
 * address.
 */
export async function verifyTurnstile(
  token: FormDataEntryValue | null,
  ip: string | undefined,
): Promise<boolean> {
  if (!SECRET_KEY) return true;
  if (typeof token !== "string" || token.length === 0 || token.length > 4096) {
    track("turnstile_failed", { reason: "missing" });
    return false;
  }

  const body = new URLSearchParams({ secret: SECRET_KEY, response: token });
  if (ip) body.set("remoteip", ip);

  try {
    const response = await fetch(VERIFY_URL, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    const result = (await response.json()) as { success?: boolean; "error-codes"?: string[] };
    if (result.success === true) return true;
    track("turnstile_failed", {
      reason: "rejected",
      codes: (result["error-codes"] ?? []).join(",") || null,
    });
    return false;
  } catch {
    track("turnstile_failed", { reason: "network" });
    return false;
  }
}
