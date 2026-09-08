/**
 * A hook for the stats work, not analytics.
 *
 * `track()` writes one JSON line per event to the server log and does nothing
 * in the browser. It is called from the server action path (a verdict, a
 * refused upload) and from the Open Graph route (a share preview being
 * fetched). Share links carry `?ref=wa|tg|copy`, so the referrer of an
 * arriving visitor is already in the access log; the stats page can join the
 * two without a client-side beacon.
 *
 * Never pass user text. Bands, ids, locales and counts only.
 */

export type TrackProps = Record<string, string | number | boolean | null | undefined>;

export function track(event: string, props: TrackProps = {}): void {
  if (typeof window !== "undefined") return;

  const line = JSON.stringify({ ts: new Date().toISOString(), event, ...props });
  console.log(`[saqbol.track] ${line}`);
}
