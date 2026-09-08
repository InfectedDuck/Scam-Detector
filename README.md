# SaqBol — Сақ бол

**Explainable multilingual scam triage for Kazakhstan.** Paste a suspicious message or drop in a screenshot and get back which known scam script it matches, the exact words that gave it away, what stage the scam is at, and who to call. In Russian, Kazakh, English or Chinese.

> Status: week 1 of a four-week build, September 2026. The engine, the Telegram bot, the HTTP API and the web app run end to end offline. The leaderboard and the dataset release are scheduled for weeks 3 and 4. Nothing here is deployed yet.

Backed by **KazScam**, the first openly released scam-annotated Kazakh and Russian corpus, and a public leaderboard measuring how current language models handle Kazakh and code-switched scam text.

<!-- T606: sixty-second demo recording goes here once the web app is deployed. -->

---

## Why

Kazakhstan's anti-fraud centre logs tens of thousands of cases a year. Existing consumer tools are English- or Chinese-first, and the messages people actually receive are in Russian, Kazakh, or a mix of both. There is no open dataset for that text, so there is no way to measure whether a model is any good at it.

SaqBol is two things at once: a free tool that answers "is this a scam" in the user's own language, and the evaluation artifact that shows how well the underlying models really do.

## What it does

```
> Здравствуйте, служба безопасности Kaspi. На ваше имя оформляют кредит.
> Продиктуйте код из СМС и переведите деньги на безопасный счёт.

  SCAM · risk 1.00 · kz.bank_security_call · Звонок «службы безопасности банка»
  Evidence:  служба безопасности · Продиктуйте код · код из СМС · безопасный счёт
  Do now:    Положите трубку. Перезвоните в банк сами — по номеру на обороте
             карты или через приложение, а не по тому номеру, который вам назвали.
  Call:      1414 (eGov) · 102 (police) · 9999 (Kaspi)
```

That is the real rules-only output for that message, with no model and no network. With a provider key the model adds a playbook confidence, a stage estimate and its own quoted evidence, every quote verified against the text before it is shown.

Every highlighted phrase is a verified character span in the message. The advice and the phone number come from a reviewed playbook file, never from the model.

## How it works

A hybrid pipeline. A deterministic indicator engine runs first, with no network and no model. Retrieved scam playbooks then ground a language model that classifies into a closed set. The two are fused, and the system answers `unsure` when they disagree.

```
normalize → perceive → extract entities → [indicators ‖ retrieve playbooks] → judge → fuse → render
```

| Stage | What it does | Where |
|---|---|---|
| Normalize | NFKC, zero-width and bidi stripping, script-mix detection, language ID | `core/normalize.py` |
| Perceive | Screenshot to transcript with speaker turns through a vision model; bytes discarded | `core/perceive.py` |
| Extract | URLs, phones, cards (masked on sight), IIN, amounts, crypto, remote-access apps | `core/extract.py` |
| Indicators | 50 rules in ten families, Russian and Kazakh patterns, severity-weighted | `core/indicators/` |
| Retrieve | Lexical retrieval over 13 playbooks; dense retrieval is an ablation | `core/retrieval.py` |
| Judge | Structured output, confined to retrieved candidates, quotes verified against the text | `core/graph.py` |
| Fuse | Weighted risk, disagreement and self-consistency overrides, four bands | `core/fuse.py` |
| Render | Localized card from `i18n/{ru,kk,en,zh}.yaml`; identical key sets enforced by a test | `core/render.py` |

The rules-only baseline is published as its own row on the leaderboard, so the contribution of the model is measured rather than assumed. Full design in [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md), and the reasoning behind each choice in [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md).

## Surfaces

| Surface | Entry point | Notes |
|---|---|---|
| Telegram bot | `python -m saqbol.bot.main` | Consent on `/start`, text, forwards, screenshots, feedback buttons, dataset opt-in |
| HTTP API | `uvicorn saqbol.api.main:app` | `POST /api/v1/analyze`, feedback, public stats, playbook library, `/healthz` |
| Web app | `cd web && npm run dev` | Analyze page with inline highlighting, share pages with Open Graph images, public stats, a playbook library in four languages |

All three run with nothing configured: no database means an in-memory store, no provider key means the rules-only pipeline, no vision key means screenshots are declined rather than faked.

## Run it

One command, four containers, no internet needed after the images are built:

```bash
cp .env.example .env          # fill in what you have; blanks are fine
docker compose up --build
# web  → http://127.0.0.1:3000
# api  → http://127.0.0.1:8000/docs
```

For development without Docker:

```bash
python -m venv .venv
.venv/Scripts/activate                      # Windows; source .venv/bin/activate elsewhere
pip install -e ".[api,bot,eval,dev]"
pytest                                      # 1,150+ tests, no network, no keys
ruff check src tests

uvicorn saqbol.api.main:app --reload        # API on :8000, rules-only until a key is set
cd web && npm install && npm run dev        # web on :3000, mock verdicts until SAQBOL_API_BASE is set
```

Set `DEEPSEEK_API_KEY` or `DASHSCOPE_API_KEY` in `.env` to switch the pipeline from rules-only to hybrid. Set `DASHSCOPE_API_KEY` to enable screenshots. `SAQBOL_LLM_OFFLINE=1` replays recorded model responses and refuses to call out, which is how CI runs the full pipeline for free.

## Evaluation

```bash
python -m saqbol.eval run --config eval/configs/v0.1.yaml
python -m saqbol.eval leaderboard --results eval/runs/<id>/results.json --out leaderboard.md
```

The matrix is systems × models × splits × languages × ablations. Every number carries a stratified bootstrap confidence interval with 10,000 resamples, and the leaderboard generator refuses to print "beats" where intervals overlap. A thirty-row smoke run executes on every commit in CI.

| System | Models | Splits | Ablations |
|---|---|---|---|
| `rules_only`, `llm_zeroshot`, `hybrid` | DeepSeek-V3, Qwen3, GPT-4o-mini, Llama-3.3-70B | `test_press`, `test_donated` | `translated`, `cue_masked`, `no_playbook_context` |

**Leaderboard: not yet run.** It needs the annotated dataset (week 3) and provider keys. The table lands here, generated and never hand-edited. Protocol in [docs/05_EVAL_PROTOCOL.md](docs/05_EVAL_PROTOCOL.md).

## KazScam dataset

Collected from official warnings and press with a URL and access date on every row, PII-scrubbed with typed placeholders, double-annotated against a two-page guideline with per-class Cohen's kappa reported, and split so that no near-duplicate crosses a boundary. Hard negatives, genuine bank and delivery messages that look like scams, are a never-cut part of the test set.

Collection is in progress. The release goes to Hugging Face with a datasheet. Guideline: [docs/07_ANNOTATION_GUIDELINE.md](docs/07_ANNOTATION_GUIDELINE.md). Sources and redistribution basis: [docs/09_SOURCES.md](docs/09_SOURCES.md).

## Privacy

The tool never asks for a code, a card number, or a phone number. Screenshots are turned into text in memory and the bytes are dropped; a test asserts they reach neither a table nor a log line. Identifiers are HMAC-hashed before they reach the database. Stored text expires after 30 days. Nothing enters the dataset without an explicit per-submission opt-in, and even then it lands in a review queue. Full policy in [PRIVACY.md](PRIVACY.md).

## Limitations

- Text and screenshots only. No voice notes, no APK analysis, no fine-tuned model in v1.
- The Kazakh rule set was written by one person and is marked for native-speaker review in the lexicon file. Until that review, the Kazakh numbers measure the author as much as the language.
- The hybrid pipeline depends on a model provider that is reachable from both Kazakhstan and mainland China. Rules-only is the fallback and is honest about being weaker.
- Stage detection uses only the messages in one conversation window. It says nothing about a scam that spans days.
- No leaderboard number exists yet. Any claim about model quality before it is published is a plan, not a result.

## Documentation

| Document | Contents |
|---|---|
| [docs/00_BUILD_PLAN.md](docs/00_BUILD_PLAN.md) | Milestones, task backlog, progress table |
| [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) | Pipeline, stack, deployment |
| [docs/02_DATA_CONTRACTS.md](docs/02_DATA_CONTRACTS.md) | Every schema |
| [docs/03_INDICATORS.md](docs/03_INDICATORS.md) | The deterministic detection rules |
| [docs/04_PLAYBOOKS.md](docs/04_PLAYBOOKS.md) | The thirteen scam scripts |
| [docs/05_EVAL_PROTOCOL.md](docs/05_EVAL_PROTOCOL.md) | Dataset, annotation, metrics |
| [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md) | Why each choice was made, and what went wrong |
| [docs/08_REFUSAL_PROBE.md](docs/08_REFUSAL_PROBE.md) | Whether providers decline to analyse scam text, by language |

## Contributing

Native Kazakh and Russian speakers are the contributors this project needs most, and no programming is required: see [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## Licence

MIT for the code. The dataset carries its own licence and datasheet, released separately.
