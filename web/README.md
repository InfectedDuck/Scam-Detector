# SaqBol web

Next.js 15 App Router, TypeScript, Tailwind 4. One page, four locales, one client
component.

```
npm install
npm run dev          # http://localhost:3000 → redirects to /ru, /kk, /en or /zh
npm run test         # React form and screenshot regression tests (Node 24)
npm run typecheck
npm run build && npm start
npm run test:smoke   # after build: sample pages against a failing local API
npm run fixtures     # regenerate web/mock/*.json from mock/build-fixtures.mjs
```

The app runs from a repo checkout: it reads `../src/saqbol/i18n/*.yaml` and
`../src/saqbol/playbooks/data/*.yaml` at build and request time. A container
that copies only `web/` must set `SAQBOL_I18N_DIR` and `SAQBOL_PLAYBOOKS_DIR`.

## What is where

| Path | Role |
|---|---|
| `app/[locale]/layout.tsx` | Root layout. Lives inside the segment so `<html lang>` is right; there is no `app/layout.tsx`. |
| `app/[locale]/page.tsx` | The analyze page. Server component. `?sample=<id>` renders a labelled saved example in the HTML, without calling the API or spending a check. |
| `app/[locale]/actions.tsx` | The server action behind the paste box. Returns the rendered card, not data. Forwards the visitor's address to the API and gates the fourth check in a session behind Turnstile. |
| `app/[locale]/stats/page.tsx` | Public numbers from `GET /api/v1/stats`: checks, devices, scam share, top scenarios, a 30-day chart. |
| `app/[locale]/playbooks/` | The scenario library: an index grouped by region and one static page per playbook. |
| `app/[locale]/share/[playbook_id]/page.tsx` | The page a share link lands on. Static per playbook and per band. |
| `components/Shell.tsx` | Header, language switcher and footer shared by every page. |
| `components/Scenario.tsx` | The scenario building blocks the share page and the library both render. |
| `middleware.ts` | `/` → `/{locale}` from `Accept-Language`, default `ru`. |
| `components/AnalyzeForm.tsx` | The only `"use client"` file: textarea, counter, pending state, and the Turnstile widget once a session has used its free checks. |
| `components/VerdictCard.tsx` | The card. Band, evidence, advice, hotline, then the fusion breakdown. |
| `components/HighlightedMessage.tsx` | Paints the evidence marks. |
| `lib/highlight.ts` | Offsets → verified, flattened, overlap-aware segments. **The demo.** |
| `lib/normalize.ts` | Stage-0 mirror (NFKC, invisible characters) and code-point helpers. |
| `lib/api.ts` | `fetchVerdict()` and `fetchStats()`. The one seam to the backend. Mock until `SAQBOL_API_BASE` is set. |
| `lib/playbooks.ts` | Reads the playbook YAML for the share pages and the library: summary, red flags, stages, hotlines, sources. |
| `lib/turnstile.ts` | The session check counter and the Turnstile verification. Inert without keys. |
| `lib/types.ts` | TypeScript mirror of the `Verdict` contract. |
| `i18n/shared.ts` | Loader for the backend's i18n and playbook YAML. Russian fallback for gaps. |
| `i18n/ui.*.json` | Page chrome only. Nothing about a verdict is authored here. |
| `mock/build-fixtures.mjs` | Generates the fixtures with computed, verified offsets. |
| `mock/verdict.json` | The canonical fixture: a `scam` verdict, seven evidence spans. |
| `tests/` | React form retries, screenshot selection races, and production sample-page smoke checks. |

## Strings

Everything a verdict says — band names, indicator labels, stage descriptions,
generic advice, hotline names, the fallback notice — comes from
`src/saqbol/i18n/{ru,kk,en,zh}.yaml`. The advice for a matched playbook comes
from that playbook's `action` block, looked up by `Verdict.action_key`, and the
playbook's display name from its `name` block. `web/i18n/ui.*.json` holds only
the page chrome.

A `null` in `kk.yaml`, or a playbook without a translation for the locale, falls
back to Russian and the card ends with the backend's own `footer.fallback` line,
the same way the bot does.

## Highlighting

Evidence offsets index the **normalized** text in **code points** (Python
`str` indices). JavaScript strings index UTF-16 units, which differ the moment a
message contains an emoji, so `lib/highlight.ts` works entirely in code points.
It then:

1. checks the contract invariant `normalized[start:end] == text` for every span;
2. re-anchors a failing span by searching for its text, nearest the declared
   offset first;
3. lists a span it cannot find at all under the message rather than drawing it
   over the wrong characters;
4. cuts the text at every span boundary into flat segments, so overlapping
   spans render as one `<mark>` with a doubled underline instead of nested
   elements.

`mock/verdict.parcel.json` starts with an emoji and has two overlapping spans on
its URL for exactly these reasons.

## Form state

With JavaScript enabled, a completed check keeps the entered message and selected
screenshot, including when the server returns an error notice. Retrying therefore
submits the same content; the character counter and preview still describe the
actual fields. The Remove button explicitly clears the screenshot. Selecting a
different sample resets the form to that example.

Screenshot preparation follows the most recent selection. Replacing or removing
an image invalidates pending work, and old results cannot restore a removed file,
change the current preview, or enable submission while a newer image is preparing.
Preview URLs are released when replaced, removed, or unmounted.

`npm run test` exercises these behaviors using React DOM and jsdom. The smoke
check starts a temporary local API that rejects checks, then verifies all five
sample pages in four locales still render without any analysis requests.

## Evidence-text contract

`POST /api/v1/analyze` returns `normalized_text` alongside the verdict. Every
evidence span indexes that exact normalized string in Unicode code points. The
web app renders live verdicts from it, so it does not need to duplicate the
Python normalizer. `lib/normalize.ts` remains only for saved mock fixtures.

## Performance budget

Page-specific JavaScript is about 2 kB; first load is the React and Next
runtime (~108 kB gzipped) and nothing else. The card, the highlighting and all
dictionaries render on the server and arrive as HTML or RSC payload. The only
client component is the screenshot drop zone. Fonts are the system stack. Dark
mode follows `prefers-color-scheme` with no script and no flash. The `?sample=`
links and the form, including the file input, work with JavaScript disabled.

## Environment

| Variable | Purpose |
|---|---|
| `SAQBOL_API_BASE` | Base URL of the Python API. Unset means mock verdicts. |
| `SAQBOL_SITE_URL` | Public origin, used for absolute share links and `og:image`. Falls back to request headers. |
| `TURNSTILE_SITE_KEY` | Cloudflare Turnstile site key. Together with the secret, turns on the human check after the third check in a session. |
| `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile secret key. Also signs the session counter cookie. |

## Abuse protection

The server action forwards the visitor's address to the API as
`X-Forwarded-For` (first hop of the incoming `x-forwarded-for`, else
`x-real-ip`) with `X-Saqbol-Surface: web`, so the API rate-limits each
visitor rather than the web server as a whole. The API honours the header only
when its own `TRUST_PROXY=1` is set; in docker-compose its port is bound to
127.0.0.1, so only this service can reach it. The address is never logged here.

Turnstile is on only when **both** `TURNSTILE_SITE_KEY` and
`TURNSTILE_SECRET_KEY` are set. With either missing nothing about the form
changes and the action verifies nothing. When on, a signed httpOnly cookie
(`saqbol_n`) counts successful checks per browser session; from the fourth
check the form renders the Cloudflare widget and the action refuses a check
whose token is missing, rejected, or could not be verified (it fails closed).
The widget needs JavaScript, so with scripting off the fourth check is refused
with the same notice. A tampered cookie counts as zero; the API's per-address
daily limit is the backstop.

Share pages under `/[locale]/share/[playbook_id]` and the library under
`/[locale]/playbooks` are prerendered at build time from the playbook YAML, so
a new playbook needs a rebuild. The stats page is never rendered at build
time: with an API configured it renders per request from a five-minute cache,
and shows an "unavailable" state when the API is down.
