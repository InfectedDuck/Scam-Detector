PROVISIONAL splits, built from collection labels, not annotated: `playbook_id`, `stage` and both annotator fields are null on every row, and these files must be rebuilt after T407 (annotation) lands.

# KazScam v0.1 splits

Built by `python -m saqbol.eval splits --corpus data/corpus --out data/kazscam_v0.1 --seed 20260908` on 2026-09-08T16:55:01Z. One JSONL per split in the shape of docs/02_DATA_CONTRACTS.md section 6, plus `text_sha256` (what the leakage rules key on) and `corpus_id` (the collection record the row came from). `manifest.json` records the seed, the counts and every group of rows that had to travel together.

| Split | Rows | By label | By lang | Hard negatives |
|---|---|---|---|---|
| `train_synthetic` | 0 | none | none | 0 |
| `calibration` | 30 | legit 7, scam 23 | kk 10, ru 20 | 7 |
| `test_press` | 46 | legit 10, scam 36 | kk 18, ru 28 | 10 |
| `test_donated` | 0 | none | none | 0 |

- Calibration is 30 rows: the contract's 150 was capped at 40% of the 76-row press pool (39.5% used).
- 50 `phrase_fragment` rows were excluded; fragments never enter a message split.
- 19 groups of 38 rows (parallel translations, variant groups, near-duplicates) were assigned as units.
- `train_synthetic` is empty: the LLM paraphrases do not exist yet. When generated they must be derived from press rows only, never from test_donated or calibration, with the seed row's released id recorded in `source_row_id` so the second leakage rule (no synthetic row shares a source row with any test row) can be checked.

Leakage checks over these files live in `tests/test_splits.py`.
