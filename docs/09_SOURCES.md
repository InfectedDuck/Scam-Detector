# SaqBol — Sources and redistribution basis

Every domain the KazScam corpus draws from, what it is, and whether quoted text
from it can be redistributed in a public release. This table is what makes the
Hugging Face release defensible. A row whose domain is not in this table does
not ship.

Owner: T403/T404. Last updated 2026-09-08.

---

## 1. What the corpus redistributes

The released dataset contains **the scam message text quoted inside a source
article, plus a URL and an access date**. It does not contain the article, the
headline, the journalist's analysis, or any image.

That distinction carries most of the legal weight:

- The scam text is a **third-party criminal artifact**. The publisher who
  quoted it does not own it and did not author it. Quoting a fraudster's SMS
  does not make the newspaper its author.
- What the publisher does own is **the article around the quote**, and the
  corpus redistributes none of that.
- The residual claim — that the *selection and arrangement* of quoted examples
  is itself editorial work — is answered by the statutory quotation right
  below, and by the fact that rows are re-mixed across sources and never
  reproduce any one article's set as a set.

**Statutory basis.** Law of the Republic of Kazakhstan of 10 June 1996 No. 6-I
*On Copyright and Related Rights*, Article 19: use of a lawfully published work
without the author's consent and without royalty is permitted, **with mandatory
attribution of the author and the source**, including citation "in scientific,
research, polemical, critical and informational purposes, in a volume justified
by the purpose of the citation". A single quoted SMS, attributed with a live
URL, is inside that allowance by a wide margin.

**Practical rule.** Attribution is not optional and not a footnote: every row
carries `source_url`, `publisher` and `access_date`, and the release ships this
file. If a rights-holder objects to a specific row, the row is removed and the
domain's status here changes to `withdrawn`.

---

## 2. Domains used in the corpus

Status values: `in use` (rows collected), `no yield` (fetched, quotes nothing
verbatim), `blocked` (refuses automated fetching), `withdrawn` (rights-holder
objection).

| Domain | What it is | Provenance class | Rows | Terms verified? | Redistribution basis |
|---|---|---|---|---|---|
| `fingramota.kz` | Financial-literacy portal operated by the **Agency of the RK for Regulation and Development of the Financial Market (ARDFM)**. Confirmed on its About page: "один из проектов, реализуемых Агентством РК по регулированию и развитию финансового рынка". | `official_warning` | 8 | No published reuse terms found on site | Art. 19 quotation right. State-agency awareness material published for public dissemination; quoting it back for research is squarely within its purpose. **Lowest-risk source in the set.** |
| `zakon.kz` | Private legal-and-news portal, one of the largest in KZ. Russian-language edition. | `press` | 6 | **No** — `/pravila-polzovaniya/` returns 404; no reuse terms located | Art. 19 quotation right only. Attribution + URL mandatory. |
| `kaz.zakon.kz` | Kazakh-language edition of the same publisher. | `press` | 1 | **No** — as above | Art. 19 quotation right only. |
| `stan.kz` | Private Kazakh-language news portal. | `press` | 12 | **No** — not located | Art. 19 quotation right only. All rows from it are `phrase_fragment` (see §4). |
| `turkystan.kz` | Online edition of the newspaper *Türkistan*. | `press` | 1 | **No** — not located | Art. 19 quotation right only. |
| `elordainfo.kz` | Astana city news outlet. | `press` | 1 | **No** — not located | Art. 19 quotation right only. |

**Terms column is honest, not decorative.** For five of six domains I could not
locate a terms-of-use or reuse page at all. That is recorded as "No" rather
than assumed permissive. The release rests on the statutory quotation right,
not on any site's grant. Before the Hugging Face push, someone should attempt
written permission from `zakon.kz` and `stan.kz`, the two heaviest
contributors, because a written grant is strictly better than a statutory
argument when a reviewer asks.

---

## 3. Domains attempted, with outcome

Logged so the next collection session does not repeat the work.

| Domain | What it is | Outcome | Note |
|---|---|---|---|
| `polisia.kz` | MIA official media portal | `no yield` | 4 articles fetched, all describe schemes without quoting message text. Appears to be deliberate editorial policy — not handing criminals a template. |
| `factcheck.kz` | Fact-checking organisation (MediaNet) | `blocked` | HTTP 403 to automated fetch. **Highest-value untapped source**: fact-checks reproduce viral message text verbatim by nature of the format. Needs manual collection in a browser. |
| `baribar.kz` | Kazakh-language news | `blocked` | HTTP 403. Article title suggests it quotes MIA phrasing lists. Worth a manual visit. |
| `egov.kz`, `gov.kz` | Government portals | `no yield` | JavaScript SPAs; automated fetch returns the page shell only. Content exists but needs a browser. |
| `tengrinews.kz` | Major news portal | `no yield` | 4 articles fetched; describes, does not quote. One (`595863`) recounts a victim's story without reproducing the message. |
| `informburo.kz` | News portal | `no yield` | Describes only. |
| `kaspi.kz`, `guide.kaspi.kz` | Bank customer help | `no yield` | States *which* notifications it sends and that Kaspi uses in-app Messages rather than SMS, but never quotes message text. |
| `halykbank.kz` | Bank knowledge base | `no yield` | Halyk dropped SMS notifications entirely in June 2022 in favour of push. |
| `profit.kz` | Tech/business news | `no yield` | Confirms Kazpost sends from short number 1499; quotes no message text. |
| `eubank.kz` | Eurasian Bank blog | `no yield` | Target article 404s. |

---

## 4. Collection rules applied

**Verbatim only.** `tools/collect.py` rejects any row marked non-verbatim. No
row was written from a search-result summary; every row came from a fetch of
the cited page, and every fetch was asked to return `NO_VERBATIM` rather than
paraphrase when the page quoted nothing. Roughly two thirds of fetches returned
exactly that, and those produced no rows.

**`message` vs `phrase_fragment`.** Kazakhstani sources very often quote a
scam's *cue phrase* ("картаңыз бұғатталды") rather than a whole message. Those
quotes are real and sourced, but a three-word stub is not a message and would
poison a message-classification split. The rule applied:

- `message` — a complete utterance a target would actually receive: a full
  sentence carrying a claim, and usually an instruction.
- `phrase_fragment` — a cue phrase quoted to illustrate wording.

`collect.py paste` emits only `message` rows unless `--include-fragments` is
passed, so fragments cannot reach annotators by accident. **Fragments must not
enter a released message split.** They are useful as an indicator lexicon for
the rules engine, and that is what they are for.

Three items quoted by `stan.kz` were dropped rather than recorded: "делдал",
"қаржы кеңесшісі" and "брондау керек" are role labels and generic vocabulary,
not quoted message wording. Recording them would have been padding.

**Duplicate check.** Exact-on-normalized plus character-shingle Jaccard at
0.85. It earned its keep immediately: `elordainfo.kz` and `turkystan.kz`
published the same quoted phrase on the same day, and the second copy was
rejected on ingest. That is the reprint pattern the leakage tests exist to
catch, observed on the first real batch.

**Parallel translations.** `fingramota.kz` publishes its vishing page in both
Russian and Kazakh, and the four scripts are translations of each other. All
eight rows carry a `parallel pair key` in `notes`. These pairs are matched
content across languages, which is exactly what the `translated` ablation in
`docs/05_EVAL_PROTOCOL.md` §6 needs — and they are also a **split hazard**: a
pair split across train and test is cross-language leakage. Pairs must move
together.

**PII.** Not scrubbed here; T405 owns that. Rows carry `pii_flags` and
`needs_scrub`. Zero of the 29 rows flagged, which is expected — publishers
redact phone numbers before quoting.

---

## 5. Honest state of the collection

29 rows, of which **12 are messages** and 17 are phrase fragments. Zero hard
negatives. The session target was 60–80 sourced rows plus 20 hard negatives.

The shortfall is structural, not effort. Kazakhstani official and press
coverage of fraud overwhelmingly **describes** schemes instead of reproducing
message text. Of roughly 25 pages fetched across police, ministry, bank and
press domains, about two thirds quoted nothing verbatim at all. The sources
that do reproduce text are financial-literacy portals and fact-checkers — and
the best of the fact-checkers (`factcheck.kz`) blocks automated fetching.

**Hard negatives are not available from the open web at all.** Genuine bank,
delivery and government messages are not published verbatim by anyone: banks
document *which* notifications they send, never their wording, and Kaspi and
Halyk have both moved to in-app push, so the messages do not exist as
quotable SMS. This matches what `docs/05_EVAL_PROTOCOL.md` §2 already assumed
— hard negatives come from donation, not from collection — and it means the
never-cut set depends entirely on the donation path.

### What actually gets the corpus to target

1. **Donation, started now.** The largest remaining source for both hard
   negatives and real scam texts. Per §2 of the eval protocol this is a week-1
   task with an external dependency on other people, and it is the only path to
   hard negatives.
2. **Manual collection from `factcheck.kz` and `baribar.kz`.** Blocked to
   automation, open in a browser. Fact-check articles quote viral text verbatim
   by design; this is the densest untapped seam.
3. **Kazakh-language sources are richer than expected.** 19 of 29 rows are
   Kazakh, against an expectation that Kazakh would be the scarce half. Worth
   noting before H1 is interpreted: if Kazakh material is easier to source than
   Russian, the released language balance is a property of collection, not of
   the threat landscape, and the report must say so.

---

## 6. Adding a domain

1. Fetch the page and confirm it quotes message text verbatim.
2. Add a row to §2 with what the domain is and its terms status. Do not write
   "permits redistribution" without a located, quoted clause.
3. Collect with `tools/collect.py ingest`, which enforces provenance, URL and
   access date.
4. Run `python tools/collect.py check --stats` before committing.
