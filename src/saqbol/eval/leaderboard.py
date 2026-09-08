"""T501 — `leaderboard.md`, generated from `results.json` and never hand-edited.

The table prints numbers with their 95 percent intervals and nothing else. It
makes no ranking claim: rows within a group are ordered by point estimate so
the table is readable, and the header says in so many words that overlapping
intervals support no claim about which system is better. The sentence that
would make such a claim lives in `metrics.compare`, which checks the
intervals first; this module never calls it.

A metric a cell did not measure prints as a dash. That is the reading rule
`metrics.py` sets for an undefined number, and it keeps a cell with no hard
negatives from printing a false-positive rate of zero.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from saqbol.eval.results import ABLATIONS, LANGS, SPLITS, ResultRow, Results, read_results

DASH = "—"

RULE = (
    "Every number is a point estimate with its 95 percent bootstrap interval in brackets. "
    "Two intervals that overlap support no claim about which system is better; rows are "
    "ordered by point estimate within each group only so the table can be read."
)

_COLUMNS = (
    "system",
    "model",
    "lang",
    "ablation",
    "n",
    "macro-F1 [95% CI]",
    "hard-neg FPR [95% CI]",
    "coverage",
    "playbook macro-F1 [95% CI]",
    "stage acc. (correct/eligible)",
)


def _fmt(value: float | None, ndigits: int = 3) -> str:
    if value is None:
        return DASH
    return f"{value:.{ndigits}f}"


def _interval(point: float | None, ci: Sequence[float] | None, ndigits: int = 3) -> str:
    if point is None:
        return DASH
    if ci is None:
        return _fmt(point, ndigits)
    lo, hi = ci
    return f"{point:.{ndigits}f} [{lo:.{ndigits}f}, {hi:.{ndigits}f}]"


def _extra(row: ResultRow, key: str) -> Any:
    return (row.model_extra or {}).get(key)


def _render_row(row: ResultRow) -> str:
    coverage = None if row.abstain_rate is None else 1.0 - row.abstain_rate
    stage = _extra(row, "stage_accuracy")
    if stage is None:
        stage_cell = DASH
    else:
        stage_cell = (
            f"{stage:.3f} ({_extra(row, 'stage_n_correct')}/{_extra(row, 'stage_n_eligible')})"
        )
    cells = (
        row.system,
        row.model,
        row.lang,
        row.ablation,
        str(row.n),
        _interval(row.macro_f1, row.ci95),
        _interval(row.fpr_hard_negative, _extra(row, "fpr_hard_negative_ci95")),
        _fmt(coverage),
        _interval(_extra(row, "playbook_macro_f1"), _extra(row, "playbook_ci95")),
        stage_cell,
    )
    return "| " + " | ".join(cells) + " |"


#: Groups print the whole split first, then each language slice.
_LANG_ORDER: tuple[str, ...] = ("all", *(lang for lang in LANGS if lang != "all"))


def _order(row: ResultRow) -> tuple[int, int, float, str, str]:
    ablation_rank = ABLATIONS.index(row.ablation)
    lang_rank = _LANG_ORDER.index(row.lang) if row.lang in _LANG_ORDER else len(_LANG_ORDER)
    return (ablation_rank, lang_rank, -row.macro_f1, row.system, row.model)


def _table(rows: Sequence[ResultRow]) -> list[str]:
    header = "| " + " | ".join(_COLUMNS) + " |"
    rule = "|" + "|".join("---" for _ in _COLUMNS) + "|"
    return [header, rule, *(_render_row(r) for r in sorted(rows, key=_order))]


def render_leaderboard(results: Results, *, skipped: Sequence[Mapping[str, Any]] = ()) -> str:
    """The markdown leaderboard for one results file.

    `skipped` is the manifest's list of cells that did not run; when given,
    they are listed with their reasons so an absent row is explained rather
    than left to be inferred.
    """
    lines = [
        f"# Leaderboard — {results.dataset_version}",
        "",
        f"Generated from `results.json` for run `{results.run_id}` "
        f"({results.n_bootstrap:,} bootstrap resamples). Do not edit by hand; regenerate "
        "with `python -m saqbol.eval leaderboard`.",
        "",
        RULE,
        "",
        "Macro-F1 is over `scam` / `legit` on the rows the system answered; `coverage` is the "
        "share of rows it answered. The hard-negative FPR keeps abstentions in its denominator. "
        "Playbook macro-F1 is over the scam rows the system answered, with a missing playbook "
        "scored as its own class. A dash marks a metric the cell did not measure.",
        "",
    ]
    present = [s for s in SPLITS if any(r.split == s for r in results.rows)]
    if not present:
        lines += ["No cell of the matrix produced a result.", ""]
    for split in present:
        lines += [f"## {split}", "", *_table([r for r in results.rows if r.split == split]), ""]
    if skipped:
        lines += [
            "## Cells not run",
            "",
            "Grouped by reason; `manifest.json` lists every cell.",
            "",
            "| cells | systems | splits | reason |",
            "|---|---|---|---|",
        ]
        for reason, count, systems, splits in group_skipped(skipped):
            fields = (str(count), ", ".join(systems), ", ".join(splits), reason.replace("|", "\\|"))
            lines.append("| " + " | ".join(fields) + " |")
        lines.append("")
    return "\n".join(lines)


def group_skipped(
    skipped: Sequence[Mapping[str, Any]],
) -> list[tuple[str, int, list[str], list[str]]]:
    """Skipped cells collapsed by reason: `(reason, count, systems, splits)`.

    Reasons keep their first-seen order, which is matrix order, so a split
    that is missing is listed before a model that has no key.
    """
    groups: dict[str, tuple[int, list[str], list[str]]] = {}
    for cell in skipped:
        reason = str(cell.get("reason", ""))
        count, systems, splits = groups.get(reason, (0, [], []))
        system, split = str(cell.get("system", DASH)), str(cell.get("split", DASH))
        if system not in systems:
            systems.append(system)
        if split not in splits:
            splits.append(split)
        groups[reason] = (count + 1, systems, splits)
    return [(reason, count, systems, splits) for reason, (count, systems, splits) in groups.items()]


def _skipped_beside(results_path: Path) -> list[Mapping[str, Any]]:
    manifest = results_path.with_name("manifest.json")
    if not manifest.is_file():
        return []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    skipped = payload.get("skipped") if isinstance(payload, dict) else None
    return [s for s in skipped if isinstance(s, dict)] if isinstance(skipped, list) else []


def write_leaderboard(
    results_path: str | os.PathLike[str], out_path: str | os.PathLike[str]
) -> Path:
    """Render `results_path` to markdown at `out_path`.

    A `manifest.json` beside the results file, if present, supplies the list
    of cells that did not run.
    """
    source = Path(results_path)
    results = read_results(source)
    text = render_leaderboard(results, skipped=_skipped_beside(source))
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8", newline="\n")
    return destination
