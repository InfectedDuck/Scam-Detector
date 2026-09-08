"""`python -m saqbol.eval`: run the matrix, or render the leaderboard.

    python -m saqbol.eval run --config eval/configs/v0.1.yaml [--limit N]
        [--systems rules_only,hybrid] [--out DIR] [--run-id ID]
    python -m saqbol.eval leaderboard --results DIR/results.json --out DIR/leaderboard.md

`run` exits 0 whenever the run completed, however many cells were skipped:
the manifest and the summary printed here say which cells did not run and
why. A non-zero exit means the run itself could not complete — an unreadable
config, a malformed split, a system name the config does not list.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from saqbol.eval.config import load_config
from saqbol.eval.leaderboard import group_skipped, write_leaderboard
from saqbol.eval.run import DEFAULT_OUT_DIR, run


def _say(text: str) -> None:
    """Print without tripping over a console that cannot show the text."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m saqbol.eval", description="KazScam evaluation harness."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    runner = commands.add_parser("run", help="execute an evaluation matrix")
    runner.add_argument("--config", required=True, type=Path, help="matrix YAML file")
    runner.add_argument("--limit", type=int, default=None, help="rows per cell, in file order")
    runner.add_argument(
        "--systems", default=None, help="comma-separated subset of the config's systems"
    )
    runner.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR, help="directory that receives <run_id>/"
    )
    runner.add_argument("--run-id", default=None, help="name of the run directory")

    board = commands.add_parser("leaderboard", help="render leaderboard.md from results.json")
    board.add_argument("--results", required=True, type=Path, help="path to results.json")
    board.add_argument(
        "--out", type=Path, default=None, help="output path (default: beside results.json)"
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    systems = None
    if args.systems:
        systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    outcome = run(
        config,
        out_dir=args.out,
        limit=args.limit,
        systems=systems,
        run_id=args.run_id,
        config_path=args.config,
    )
    counts = outcome.manifest["cells"]
    _say(
        f"run {outcome.run_id}: {counts['executed']} of {counts['planned']} cells executed, "
        f"{counts['skipped']} skipped"
    )
    for reason, count, systems, splits in group_skipped([s.as_dict() for s in outcome.skipped]):
        where = f"{', '.join(systems)} on {', '.join(splits)}"
        _say(f"  {count} cell{'s' if count != 1 else ''} skipped ({where}): {reason}")
    _say(f"wrote {outcome.results_path}")
    _say(f"wrote {outcome.manifest_path}")
    return 0


def _leaderboard(args: argparse.Namespace) -> int:
    out = args.out if args.out is not None else args.results.with_name("leaderboard.md")
    written = write_leaderboard(args.results, out)
    _say(f"wrote {written}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        return _leaderboard(args)
    except (ValueError, OSError) as exc:
        # A config, split or results file the run cannot use. The message
        # names the file and the field; a traceback would add nothing.
        sys.stderr.write(f"error: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
