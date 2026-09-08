# eval/probes

Standalone measurement instruments. Nothing here imports `saqbol`, and nothing in
`saqbol` imports from here. They have to keep working while the pipeline they
measure is being rewritten.

## refusal_probe.py

Does a provider decline to analyse scam text, and does that rate differ by
language? Write-up and interpretation: [`docs/08_REFUSAL_PROBE.md`](../../docs/08_REFUSAL_PROBE.md).

```bash
python eval/probes/refusal_probe.py selftest          # offline, no keys
python eval/probes/refusal_probe.py run --dry-run     # prints the plan and a prompt
python eval/probes/refusal_probe.py run               # REAL KEYS, REAL MONEY
python eval/probes/refusal_probe.py report            # offline, rebuilds from cache
```

**`run` is not part of CI and must never be.** It needs live provider keys and
spends money. CI lints `src tests` and runs pytest with `testpaths = ["tests"]`,
so nothing here is collected. `selftest` and `report` are offline and would be
safe to add to CI if that is ever wanted.

Keys come from the environment, or from `<repo>/.env` (same names as
`.env.example`). A model whose key is missing is skipped and reported as skipped,
not counted as a zero.

### Cost and caching

240 prompts per full run: 20 items x 4 languages x 3 models. Short prompts, 400
max tokens, so a full run is cents, not dollars.

Every response is cached under `cache/<model_key>/<cache_key>.json`, keyed by
probe version, model, prompt variant, prompt hash, item, language and text hash.
**A rerun costs nothing** — only uncached cells are sent. Editing a prompt or a
stimulus changes the key, so stale answers can never be silently reused.
Transport errors are deliberately not cached, so an outage is retried rather than
frozen into the results. `--refresh` re-asks everything.

Commit the cache. It is what makes a published number inspectable: anyone can
read the exact text behind any cell.

### Files

| File | What it is |
|---|---|
| `items.json` | 20 stimuli — 10 scam archetypes, 10 benign controls — each in ru, kk, en, zh |
| `prompts.json` | Two prompt variants: `intended` (production framing) and `neutral` |
| `models.json` | Three providers, one model each, over the OpenAI-compatible API |
| `classify.py` | The answered / refused / hedged / error rule, stated in the docstring |
| `overrides.json` | Hand adjudication of `needs_review` rows, with a reason per row |
| `fixtures/classifier_cases.json` | 24 hand-written responses covering every branch of the rule |
| `cache/` | Raw responses, one JSON per prompt |
| `results/` | `refusal_probe_<variant>.json` and `.md`, both generated |

`results/*.md` is generated and must never be hand-edited. Rerun `report`.
