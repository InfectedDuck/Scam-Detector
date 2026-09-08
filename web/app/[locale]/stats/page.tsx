import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Shell } from "@/components/Shell";
import { LOCALES, LOCALE_TAGS, getMessages, isLocale, type Locale, type T } from "@/i18n";
import { fetchStats } from "@/lib/api";
import { libraryPath, statsPath } from "@/lib/share";
import type { Stats, StatsDay } from "@/lib/types";

/**
 * The public numbers (T304): how much SaqBol has been asked to check, how
 * much of it was a scam, and which scripts are doing the rounds this week.
 * Counts only; no message text exists on this page or in the endpoint behind
 * it.
 *
 * Rendered from `GET /api/v1/stats` through lib/api.ts, which caches for five
 * minutes and returns null when the API is down; that renders as an honest
 * "unavailable" state. With no API configured the page is static and shows the
 * fixture in web/mock/stats.json.
 */

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const { t } = getMessages(locale);

  const title = `${t("stats.title")} — ${t("app.name")}`;
  const description = t("stats.meta.description");
  const configured = process.env.SAQBOL_SITE_URL;

  return {
    title,
    description,
    ...(configured ? { metadataBase: new URL(configured) } : {}),
    alternates: {
      canonical: statsPath(locale),
      languages: Object.fromEntries(LOCALES.map((l) => [LOCALE_TAGS[l], statsPath(l)])),
    },
    openGraph: {
      title,
      description,
      type: "website",
      siteName: t("app.name"),
      locale: LOCALE_TAGS[locale].replace("-", "_"),
      url: statsPath(locale),
    },
  };
}

export default async function StatsPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const messages = getMessages(locale);
  const { t } = messages;
  const stats = await fetchStats();

  return (
    <Shell locale={locale} href={statsPath}>
      <h1 className="text-balance text-2xl font-semibold tracking-tight sm:text-3xl">
        {t("stats.title")}
      </h1>
      <p className="mt-3 max-w-prose text-pretty text-[0.9375rem] leading-relaxed text-muted">
        {t("stats.lead")}
      </p>

      {stats ? (
        <StatsBody stats={stats} locale={locale} t={t} playbookName={messages.playbookName} />
      ) : (
        <p
          role="status"
          className="mt-6 rounded-2xl border border-line bg-surface px-5 py-8 text-center text-[0.9375rem] text-muted"
        >
          {t("stats.unavailable")}
        </p>
      )}
    </Shell>
  );
}

function StatsBody({
  stats,
  locale,
  t,
  playbookName,
}: {
  stats: Stats;
  locale: Locale;
  t: T;
  playbookName: (id: string) => { text: string } | undefined;
}) {
  const tag = LOCALE_TAGS[locale];
  const number = new Intl.NumberFormat(tag);
  const percent = new Intl.NumberFormat(tag, { style: "percent", maximumFractionDigits: 0 });

  const unsure = stats.days.reduce((n, day) => n + day.unsure_count, 0);
  const empty = stats.total_checks === 0 && stats.days.every((day) => day.checks === 0);
  const top = topPlaybooks(stats.days.slice(-7));
  const updated = formatUpdated(stats.updated_at, tag);

  return (
    <>
      <dl className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile
          label={t("stats.total")}
          value={number.format(stats.total_checks)}
          hint={t("stats.total.hint")}
        />
        <Tile
          label={t("stats.devices")}
          value={number.format(stats.unique_users)}
          hint={t("stats.devices.hint")}
        />
        <Tile
          label={t("stats.scam_share")}
          value={percent.format(Math.min(1, Math.max(0, stats.scam_share)))}
          hint={t("stats.scam_share.hint")}
        />
        <Tile label={t("stats.unsure")} value={number.format(unsure)} hint={t("stats.unsure.hint")} />
      </dl>
      <p className="mt-2.5 max-w-prose text-[0.75rem] leading-relaxed text-muted">
        {t("stats.devices.note")}
      </p>

      <section className="mt-8 rounded-2xl border border-line bg-surface px-5 py-5 sm:px-6">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
            {t("stats.chart.title")}
          </h2>
          <span className="text-[0.75rem] text-muted">{t("stats.chart.hint")}</span>
        </div>
        {empty || stats.days.length === 0 ? (
          <p className="mt-4 py-8 text-center text-[0.9375rem] text-muted">{t("stats.empty")}</p>
        ) : (
          <DailyChart days={stats.days} tag={tag} t={t} />
        )}
      </section>

      <section className="mt-6 rounded-2xl border border-line bg-surface px-5 py-5 sm:px-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
          {t("stats.top.title")}
        </h2>
        {top.length === 0 ? (
          <p className="mt-3 text-[0.9375rem] text-muted">{t("stats.top.empty")}</p>
        ) : (
          <ol className="mt-2 divide-y divide-line">
            {top.map(({ id, days }, i) => (
              <li key={id} className="flex items-baseline gap-3 py-3">
                <span className="w-4 shrink-0 text-[0.8125rem] tabular-nums text-muted">
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <Link
                    href={libraryPath(locale, id)}
                    prefetch={false}
                    className="text-[0.9375rem] font-medium text-ink underline underline-offset-4"
                  >
                    {playbookName(id)?.text ?? <span className="font-mono">{id}</span>}
                  </Link>
                  <p className="mt-0.5 text-[0.8125rem] tabular-nums text-muted">
                    {t("stats.top.days", { n: days })}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      {updated && (
        <p className="mt-6 text-[0.8125rem] tabular-nums text-muted">
          {t("stats.updated", { when: updated })}
        </p>
      )}
    </>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-4 py-4">
      <dt className="text-[0.8125rem] font-medium text-muted">{label}</dt>
      <dd className="mt-1 text-3xl font-semibold tracking-tight tabular-nums text-ink">{value}</dd>
      <dd className="mt-1 text-[0.75rem] leading-snug text-muted">{hint}</dd>
    </div>
  );
}

/**
 * Thirty bars, no library. Each bar is the day's checks; the darker segment
 * inside it is how many of those were flagged as scam. Colours are the page's
 * own tokens, so the chart follows dark mode with everything else.
 */
function DailyChart({ days, tag, t }: { days: StatsDay[]; tag: string; t: T }) {
  const BAR = 12;
  const GAP = 4;
  const H = 100;
  const width = days.length * (BAR + GAP) - GAP;
  const max = Math.max(1, ...days.map((day) => day.checks));
  const first = days[0];
  const last = days[days.length - 1];

  return (
    <>
      <svg
        viewBox={`0 0 ${width} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={t("stats.chart.title")}
        className="mt-4 block h-36 w-full"
      >
        {days.map((day, i) => {
          const x = i * (BAR + GAP);
          const h = round2((day.checks / max) * H);
          const s = round2((Math.min(day.scam_count, day.checks) / max) * H);
          return (
            <g key={day.day}>
              <title>
                {t("stats.chart.bar", {
                  day: formatDay(day.day, tag),
                  checks: day.checks,
                  scam: day.scam_count,
                })}
              </title>
              {h > 0 && (
                <rect x={x} y={H - h} width={BAR} height={h} fill="var(--muted)" fillOpacity={0.35} />
              )}
              {s > 0 && <rect x={x} y={H - s} width={BAR} height={s} fill="var(--band-scam-fg)" />}
            </g>
          );
        })}
        <line
          x1={0}
          x2={width}
          y1={H}
          y2={H}
          stroke="var(--line)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="mt-1.5 flex justify-between text-[0.75rem] tabular-nums text-muted">
        <span>{formatDay(first.day, tag)}</span>
        <span>{formatDay(last.day, tag)}</span>
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[0.75rem] text-muted">
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: "var(--muted)", opacity: 0.35 }}
          />
          {t("stats.chart.legend.checks")}
        </li>
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: "var(--band-scam-fg)" }}
          />
          {t("stats.chart.legend.scam")}
        </li>
      </ul>
    </>
  );
}

const round2 = (n: number) => Math.round(n * 100) / 100;

/** Which playbook led on the most of the given days, most recent first on ties. */
function topPlaybooks(days: StatsDay[]): { id: string; days: number }[] {
  const counts = new Map<string, number>();
  for (const day of [...days].reverse()) {
    if (day.top_playbook) counts.set(day.top_playbook, (counts.get(day.top_playbook) ?? 0) + 1);
  }
  return [...counts]
    .map(([id, n]) => ({ id, days: n }))
    .sort((a, b) => b.days - a.days)
    .slice(0, 5);
}

/** "2026-09-08" → "8 Sep", in the locale, without a time zone shifting the day. */
function formatDay(day: string, tag: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return day;
  return new Intl.DateTimeFormat(tag, { day: "numeric", month: "short", timeZone: "UTC" }).format(
    date,
  );
}

function formatUpdated(iso: string, tag: string): string | undefined {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return undefined;
  return new Intl.DateTimeFormat(tag, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(date);
}
