# SaqBol web

Next.js 15 App Router, TypeScript, Tailwind 4. One page, four locales, one client
component.

```
npm install
npm run dev          # http://localhost:3000 → redirects to /ru, /kk, /en or /zh
npm run build && npm start
npm run fixtures     # regenerate web/mock/*.json from mock/build-fixtures.mjs
```

The app runs from a repo checkout: it reads `../src/saqbol/i18n/*.yaml` and
`../src/saqbol/playbooks/data/*.yaml` at build and request time. A container
that copies only `web/` must set `SAQBOL_I18N_DIR` and `SAQBOL_PLAYBOOKS_DIR`.

## What is where

| Path | Role |
|---|---|
| `app/[locale]/layout.tsx` | Root layout. Lives inside the segment so `<html lang>` is right; there is no `app/layout.tsx`. |
| `app/[locale]/page.tsx` | The analyze page. Server component. `?sample=<id>` renders a finished card in the HTML. |
| `app/[locale]/actions.tsx` | The server action behind the paste box. Returns the rendered card, not data. |
| `middleware.ts` | `/` → `/{locale}` from `Accept-Language`, default `ru`. |
| `components/AnalyzeForm.tsx` | The only `"use client"` file: textarea, counter, pending state. |
| `components/VerdictCard.tsx` | The card. Band, evidence, advice, hotline, then the fusion breakdown. |
| `components/HighlightedMessage.tsx` | Paints the evidence marks. |
| `lib/highlight.ts` | Offsets → verified, flattened, overlap-aware segments. **The demo.** |
| `lib/normalize.ts` | Stage-0 mirror (NFKC, invisible characters) and code-point helpers. |
| `lib/api.ts` | `fetchVerdict()`. The one seam to the backend. Mock until `SAQBOL_API_BASE` is set. |
| `lib/types.ts` | TypeScript mirror of the `Verdict` contract. |
| `i18n/shared.ts` | Loader for the backend's i18n and playbook YAML. Russian fallback for gaps. |
| `i18n/ui.*.json` | Page chrome only. Nothing about a verdict is authored here. |
| `mock/build-fixtures.mjs` | Generates the fixtures with computed, verified offsets. |
| `mock/verdict.json` | The canonical fixture: a `scam` verdict, seven evidence spans. |

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

## Contract gap

`Verdict` carries offsets into the normalized text but not the normalized text
itself. Until the backend adds `normalized_text` to the response, `fetchVerdict`
normalizes locally with `lib/normalize.ts` and relies on the verification above.
`lib/api.ts` already prefers `verdict.normalized_text` when present, so adding
the field to the pydantic model is the whole fix.

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

Share pages under `/[locale]/share/[playbook_id]` are prerendered at build
time from the playbook YAML, so a new playbook needs a rebuild.
