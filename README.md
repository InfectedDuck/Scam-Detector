# SaqBol — Сақ бол

**Explainable multilingual scam triage for Kazakhstan.** Forward a suspicious message or a screenshot and get back which known scam script it matches, the evidence that triggered the verdict, and who to call.

> Status: in development. Week 1 of a four-week build. Nothing here is production-ready yet.

Backed by **KazScam**, the first openly released scam-annotated Kazakh and Russian corpus, and a public leaderboard measuring how current language models handle Kazakh and code-switched scam text.

---

## Why

Kazakhstan's anti-fraud centre logs tens of thousands of cases a year. Existing consumer tools are English- or Chinese-first, and the messages people actually receive are in Russian, Kazakh, or a mix of both. There is no open dataset for that text, so there is no way to measure whether a model is any good at it.

SaqBol is two things at once: a free tool that answers "is this a scam" in the user's own language, and the evaluation artifact that shows how well the underlying models really do.

## How it works

A hybrid pipeline. A deterministic indicator engine runs first, with no network and no model. Retrieved scam playbooks then ground a language model that classifies into a closed set. The two are fused, and the system answers `unsure` when they disagree.

The rules-only baseline is published as its own row on the leaderboard, so the contribution of the model is measured rather than assumed.

```
normalize → perceive → extract entities → [indicators ‖ retrieve playbooks] → judge → fuse → render
```

Full design in [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md).

## Documentation

| Document | Contents |
|---|---|
| [docs/00_BUILD_PLAN.md](docs/00_BUILD_PLAN.md) | Milestones and the task backlog |
| [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) | Pipeline, stack, deployment |
| [docs/02_DATA_CONTRACTS.md](docs/02_DATA_CONTRACTS.md) | Every schema |
| [docs/03_INDICATORS.md](docs/03_INDICATORS.md) | The deterministic detection rules |
| [docs/04_PLAYBOOKS.md](docs/04_PLAYBOOKS.md) | The thirteen scam scripts |
| [docs/05_EVAL_PROTOCOL.md](docs/05_EVAL_PROTOCOL.md) | Dataset, annotation, metrics |

## Development

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -e ".[dev]"
pytest                        # core suite needs no network and no API keys
ruff check src tests
```

The core package runs on four pure-Python dependencies. Everything under `src/saqbol/core/` is testable offline, which is what keeps the rules-only baseline honest and CI free.

## Privacy

The tool never asks for a code, a card number, or a phone number. Screenshots are discarded immediately after text extraction and are never stored. Identifiers are hashed before they reach the database. Nothing enters the dataset without an explicit per-submission opt-in.

## Licence

MIT for the code. The dataset carries its own licence and datasheet, released separately.
