"""Scrub personal data out of every corpus batch, in place.

Usage::

    python tools/scrub_corpus.py              # rewrite data/corpus/*.json
    python tools/scrub_corpus.py --check      # report rows that still carry PII
    python tools/scrub_corpus.py --corpus DIR # another directory of batches

Every ``*.json`` file under the corpus directory is a batch in the shape
``tools/collect.py`` writes: ``{"batch", "created_at", "items": [...],
"updated_at"}``. A bare list of rows is accepted too. For each row the
``text`` field is passed through ``saqbol.core.privacy.scrub``; the result
replaces the original, ``scrub_applied`` is set to ``true`` and the
placeholder types present in the scrubbed text are recorded, sorted, in
``scrub_placeholders``. Running the tool twice changes nothing the second time.
Every other field is left exactly as it was, including ``text_hash`` (it is
the hash of the verbatim text, and keeping it lets ``collect.py`` still
recognise a re-collected duplicate) and ``pii_flags`` (the collector's own
checklist, kept for comparison).

Files are written back the way ``collect.py`` writes them: UTF-8,
``ensure_ascii=False``, ``indent=2``, a trailing newline. A file whose
content would not change is not rewritten.

``--check`` writes nothing. It prints every row whose text still contains
unmasked PII, one per line, and exits with status 1 if there is any.

Regular expressions are the whole mechanism. Presidio is an optional second
pass to consider before a public release, not a requirement.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = ROOT / "data" / "corpus"
TEXT_FIELDS = ("text",)

try:
    from saqbol.core.privacy import PLACEHOLDER, find_pii, scrub
except ImportError:  # running from a checkout without the package installed
    sys.path.insert(0, str(ROOT / "src"))
    from saqbol.core.privacy import PLACEHOLDER, find_pii, scrub


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def rows_of(data: Any) -> list[dict[str, Any]]:
    """The rows in a batch file, whichever of the two accepted shapes it has."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [r for r in data.get("items", []) if isinstance(r, dict)]
    return []


def scrub_row(row: dict[str, Any]) -> list[str]:
    """Scrub the text fields of one row in place. Returns the types used.

    The record is read off the scrubbed text rather than off this run's
    result, so a row scrubbed on an earlier run keeps its record instead of
    having it reset to nothing.
    """
    used: set[str] = set()
    for key in TEXT_FIELDS:
        value = row.get(key)
        if isinstance(value, str):
            row[key] = scrub(value).text
            used.update(label for label, token in PLACEHOLDER.items() if token in row[key])
    record(row, sorted(used))
    return row["scrub_placeholders"]


def record(row: dict[str, Any], used: list[str]) -> None:
    """Set the two scrub fields, keeping them next to each other in the row."""
    row["scrub_applied"] = True
    if "scrub_placeholders" in row:
        row["scrub_placeholders"] = used
        return
    fields = list(row.items())
    row.clear()
    for key, value in fields:
        row[key] = value
        if key == "scrub_applied":
            row["scrub_placeholders"] = used


def unmasked_in(row: dict[str, Any]) -> list[str]:
    """Placeholder types that would still be needed, empty when the row is clean."""
    labels: set[str] = set()
    for key in TEXT_FIELDS:
        value = row.get(key)
        if isinstance(value, str):
            labels.update(span.label for span in find_pii(value))
    return sorted(labels)


def batch_files(corpus: Path) -> list[Path]:
    return sorted(p for p in corpus.glob("*.json") if p.is_file())


def check(corpus: Path) -> int:
    offending = 0
    scanned = 0
    for path in batch_files(corpus):
        for row in rows_of(load(path)):
            scanned += 1
            labels = unmasked_in(row)
            if labels:
                offending += 1
                print(f"{path.name} {row.get('id', '?')}: {', '.join(labels)}")
    if offending:
        print(f"{offending} of {scanned} rows still carry unmasked PII")
        return 1
    print(f"{scanned} rows checked, no unmasked PII")
    return 0


def rewrite(corpus: Path) -> int:
    scanned = 0
    changed_rows = 0
    rewritten = 0
    for path in batch_files(corpus):
        original = path.read_text(encoding="utf-8")
        data = json.loads(original)
        for row in rows_of(data):
            scanned += 1
            before = {key: row.get(key) for key in TEXT_FIELDS}
            labels = scrub_row(row)
            if any(row.get(key) != before[key] for key in TEXT_FIELDS):
                changed_rows += 1
                print(f"{path.name} {row.get('id', '?')}: {', '.join(labels)}")
        out = dumps(data)
        if out != original:
            path.write_text(out, encoding="utf-8", newline="\n")
            rewritten += 1
    print(
        f"{scanned} rows scanned, {changed_rows} texts changed, "
        f"{rewritten} of {len(batch_files(corpus))} files rewritten"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS,
        help="directory of batch files (default: data/corpus)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; list rows with unmasked PII and exit 1 if any",
    )
    args = parser.parse_args(argv)
    if not args.corpus.is_dir():
        print(f"not a directory: {args.corpus}", file=sys.stderr)
        return 2
    return check(args.corpus) if args.check else rewrite(args.corpus)


if __name__ == "__main__":
    sys.exit(main())
