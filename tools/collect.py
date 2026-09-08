#!/usr/bin/env python3
"""Collection helper for the KazScam corpus (T403).

Turns a source URL plus verbatim message text into a corpus row in the exact
shape ``tools/annotate.html`` consumes, and refuses rows that duplicate text
already in the corpus.

Why the duplicate check matters: a single police or bank warning is reprinted
across a dozen news sites, so naive collection lands the same message under
several URLs. If those copies land in different splits, the leakage tests in
``docs/05_EVAL_PROTOCOL.md`` fire and the whole release is suspect. So every
row is checked twice, exact on a normalized form and fuzzy on character
shingles, before it is written.

This module deliberately does not scrub PII. T405 owns scrubbing. What it does
is *flag* rows containing a phone number, an IIN, a card number or an email, so
the scrubber gets a checklist instead of a haystack.

Stdlib only, so it runs without the project venv.

Usage
-----
  # one row
  python tools/collect.py add --url https://example.kz/news/1 \
      --text-file msg.txt --lang ru --provenance press \
      --label scam --channel sms --batch official-01

  # many rows from a staging file (a list of draft objects)
  python tools/collect.py ingest staging.json --batch press-01

  # validation and duplicate sweep over everything collected so far
  python tools/collect.py check --stats

  # paste-ready block for the labelling tool's import box
  python tools/collect.py paste --batch press-01
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "data" / "corpus"

# `provenance` answers "how did this row reach us", which is the question a
# release reviewer asks. `source` on the emitted item mirrors it, because
# annotate.html renders item.source as the chip an annotator sees.
PROVENANCE = ("press", "official_warning", "donated")
LABELS = ("scam", "legit")
LANGS = ("kk", "ru", "kk-ru", "en")
CHANNELS = (
    "sms",
    "call",
    "whatsapp",
    "telegram",
    "instagram",
    "email",
    "push",
    "web",
    "marketplace",
    "unknown",
)

# Kazakhstani sources very often quote a scam's *cue phrase* ("картаңыз
# бұғатталды") rather than the whole message. Those quotes are real and
# sourced, but a three-word stub is not a message and must never sit in a
# message split, so it is carried as a separate kind and filtered on export.
TEXT_KINDS = ("message", "phrase_fragment")

NEAR_DUP_THRESHOLD = 0.85
SHINGLE = 5

# ---------------------------------------------------------------------------
# normalization and hashing
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"https?://\S+|(?:www\.)?[a-z0-9-]+\.(?:kz|com|ru|info|site|top|xyz|net|org)\b/?\S*",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Fold a message down to what is left when formatting stops mattering.

    Case, punctuation, URL spelling and whitespace all vary between reprints of
    the same warning, so none of them may participate in identity.
    """
    s = unicodedata.normalize("NFKC", text).lower()
    s = _URL_RE.sub(" url ", s)
    s = _NONWORD_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def _shingles(norm: str, n: int = SHINGLE) -> set[str]:
    packed = norm.replace(" ", "")
    if len(packed) < n:
        return {packed} if packed else set()
    return {packed[i : i + n] for i in range(len(packed) - n + 1)}


def similarity(a: str, b: str) -> float:
    """Jaccard over character shingles of the normalized texts."""
    sa, sb = _shingles(normalize_text(a)), _shingles(normalize_text(b))
    if not sa or not sb:
        return 1.0 if sa == sb else 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------------------
# PII flagging (flag only, never scrub -- T405 owns scrubbing)
# ---------------------------------------------------------------------------

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    # +7 700 000 00 00 / 8(701)0000000 / 87010000000
    "phone": re.compile(r"(?:\+7|\b8)[\s\-()]*7\d{2}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b"),
    "short_code": re.compile(r"\b(?:1414|1408|141\d)\b"),
    # IIN / BIN: exactly 12 digits standing alone
    "iin": re.compile(r"(?<!\d)\d{12}(?!\d)"),
    "card": re.compile(r"(?<!\d)(?:\d{4}[\s\-]?){3}\d{4}(?!\d)"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
    "handle": re.compile(r"(?<![\w/])@[A-Za-z][A-Za-z0-9_]{3,}\b"),
    "iban": re.compile(r"\bKZ\d{2}[A-Z0-9]{16}\b"),
}


def flag_pii(text: str) -> list[str]:
    """Return the PII kinds present, sorted. Never modifies the text."""
    return sorted(k for k, pat in PII_PATTERNS.items() if pat.search(text))


# ---------------------------------------------------------------------------
# corpus io
# ---------------------------------------------------------------------------


def batch_path(batch: str) -> Path:
    return CORPUS_DIR / f"batch-{batch}.json"


def load_batch(batch: str) -> dict[str, Any]:
    path = batch_path(batch)
    if not path.exists():
        return {"batch": batch, "created_at": _now(), "items": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_batch(data: dict[str, Any]) -> Path:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    path = batch_path(data["batch"])
    data["updated_at"] = _now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_all_rows(exclude: str | None = None) -> list[dict[str, Any]]:
    """Every row already collected, across every batch. The dedupe universe."""
    rows: list[dict[str, Any]] = []
    if not CORPUS_DIR.exists():
        return rows
    for path in sorted(CORPUS_DIR.glob("batch-*.json")):
        if exclude and path == batch_path(exclude):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            print(f"  ! {path.name}: unreadable ({err})", file=sys.stderr)
            continue
        for item in data.get("items", []):
            item["_batch"] = data.get("batch", path.stem)
            rows.append(item)
    return rows


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# row construction
# ---------------------------------------------------------------------------


class RowError(ValueError):
    """A draft that must not become a row."""


def make_row(
    *,
    text: str,
    source_url: str,
    provenance: str,
    lang: str,
    label: str,
    access_date: str,
    channel: str = "unknown",
    publisher: str = "",
    source_title: str = "",
    hard_negative: bool = False,
    is_code_switched: bool | None = None,
    verbatim: bool = True,
    text_kind: str = "message",
    notes: str = "",
    row_id: str = "",
) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise RowError("empty text")
    if text_kind not in TEXT_KINDS:
        raise RowError(f"text_kind must be one of {TEXT_KINDS}, got {text_kind!r}")
    if provenance not in PROVENANCE:
        raise RowError(f"provenance must be one of {PROVENANCE}, got {provenance!r}")
    if lang not in LANGS:
        raise RowError(f"lang must be one of {LANGS}, got {lang!r}")
    if label not in LABELS:
        raise RowError(f"label must be one of {LABELS}, got {label!r}")
    if channel not in CHANNELS:
        raise RowError(f"channel must be one of {CHANNELS}, got {channel!r}")
    if not verbatim:
        raise RowError("only verbatim text may enter the corpus")
    # Provenance is the whole point of the release: a donated row has no URL,
    # everything else must have one.
    if provenance != "donated" and not source_url.startswith("http"):
        raise RowError(f"{provenance} rows need a source_url, got {source_url!r}")
    try:
        date.fromisoformat(access_date)
    except ValueError as err:
        raise RowError(f"access_date must be ISO yyyy-mm-dd: {err}") from err

    pii = flag_pii(text)
    code_switched = bool(is_code_switched) if is_code_switched is not None else lang == "kk-ru"
    return {
        "id": row_id or "",
        "text": text,
        # annotate.html shows item.source as a chip; keep it equal to
        # provenance so an annotator can see where the row came from.
        "source": provenance,
        "provenance": provenance,
        "source_url": source_url,
        "source_title": source_title,
        "publisher": publisher or _domain(source_url),
        "access_date": access_date,
        "lang": lang,
        "is_code_switched": code_switched,
        "label": label,
        "hard_negative": bool(hard_negative),
        "channel": channel,
        "verbatim": True,
        "text_kind": text_kind,
        "pii_flags": pii,
        "needs_scrub": bool(pii),
        "scrub_applied": [],
        "text_hash": text_hash(text),
        "collected_at": _now(),
        "notes": notes,
    }


def _domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1).lower() if m else ""


def assign_ids(data: dict[str, Any]) -> None:
    """Stable ids: ks-<batch>-NNN in insertion order."""
    for i, item in enumerate(data["items"], start=1):
        if not item.get("id"):
            item["id"] = f"ks-{data['batch']}-{i:03d}"


# ---------------------------------------------------------------------------
# duplicate detection
# ---------------------------------------------------------------------------


def find_duplicate(
    text: str, rows: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], float] | None:
    """Exact-on-normalized first, then fuzzy. Returns (kind, row, score)."""
    h = text_hash(text)
    for row in rows:
        if row.get("text_hash") == h:
            return ("exact", row, 1.0)
    best: tuple[dict[str, Any], float] | None = None
    for row in rows:
        score = similarity(text, row.get("text", ""))
        if score >= NEAR_DUP_THRESHOLD and (best is None or score > best[1]):
            best = (row, score)
    if best:
        return ("near", best[0], best[1])
    return None


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_add(args: argparse.Namespace) -> int:
    text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else (args.text or "")
    row = make_row(
        text=text,
        source_url=args.url,
        provenance=args.provenance,
        lang=args.lang,
        label=args.label,
        access_date=args.access_date,
        channel=args.channel,
        publisher=args.publisher,
        source_title=args.title,
        hard_negative=args.hard_negative,
        verbatim=not args.paraphrase,
        text_kind=args.text_kind,
        notes=args.notes,
    )
    data = load_batch(args.batch)
    universe = load_all_rows(exclude=args.batch) + data["items"]
    dup = find_duplicate(row["text"], universe)
    if dup and not args.allow_dup:
        kind, other, score = dup
        print(
            f"rejected: {kind} duplicate of {other.get('id')} "
            f"({other.get('_batch', args.batch)}, score {score:.2f})\n"
            f"  existing source: {other.get('source_url')}",
            file=sys.stderr,
        )
        return 2
    data["items"].append(row)
    assign_ids(data)
    path = save_batch(data)
    flags = ",".join(row["pii_flags"]) or "none"
    print(f"added {row['id']} -> {path.relative_to(ROOT)}  [pii: {flags}]")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest a staging file: a JSON list of drafts, or {"items": [...]}.

    Each draft carries the keys ``make_row`` takes. Batch-level defaults may be
    set under ``defaults`` so a run of rows from one article does not repeat the
    URL and access date on every line.
    """
    raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
    defaults: dict[str, Any] = {}
    if isinstance(raw, dict):
        defaults = raw.get("defaults", {})
        drafts = raw.get("items", [])
    else:
        drafts = raw

    data = load_batch(args.batch)
    universe = load_all_rows(exclude=args.batch) + data["items"]
    added = rejected = failed = 0
    for i, draft in enumerate(drafts, start=1):
        merged = {**defaults, **draft}
        try:
            row = make_row(
                text=merged.get("text", ""),
                source_url=merged.get("source_url", ""),
                provenance=merged.get("provenance", ""),
                lang=merged.get("lang", ""),
                label=merged.get("label", ""),
                access_date=merged.get("access_date", ""),
                channel=merged.get("channel", "unknown"),
                publisher=merged.get("publisher", ""),
                source_title=merged.get("source_title", ""),
                hard_negative=merged.get("hard_negative", False),
                is_code_switched=merged.get("is_code_switched"),
                verbatim=merged.get("verbatim", True),
                text_kind=merged.get("text_kind", "message"),
                notes=merged.get("notes", ""),
            )
        except RowError as err:
            print(f"  ! draft {i}: {err}", file=sys.stderr)
            failed += 1
            continue
        dup = find_duplicate(row["text"], universe)
        if dup:
            kind, other, score = dup
            print(
                f"  - draft {i}: {kind} duplicate of {other.get('id') or '(pending)'} "
                f"({score:.2f}) -- skipped",
                file=sys.stderr,
            )
            rejected += 1
            continue
        data["items"].append(row)
        universe.append(row)
        added += 1

    assign_ids(data)
    if added:
        path = save_batch(data)
        print(f"{added} added -> {path.relative_to(ROOT)}")
    print(f"summary: added={added} duplicates={rejected} invalid={failed}")
    return 0 if failed == 0 else 1


def cmd_check(args: argparse.Namespace) -> int:
    """Validation and duplicate sweep over the whole corpus."""
    rows = load_all_rows()
    if not rows:
        print("corpus is empty")
        return 0

    problems = 0
    seen_ids: dict[str, str] = {}
    for row in rows:
        rid = row.get("id", "")
        where = row.get("_batch", "?")
        if rid in seen_ids:
            print(f"  ! duplicate id {rid} in {where} and {seen_ids[rid]}")
            problems += 1
        seen_ids[rid] = where
        for key in ("text", "provenance", "access_date", "lang", "label"):
            if not row.get(key):
                print(f"  ! {rid}: missing {key}")
                problems += 1
        if row.get("provenance") != "donated" and not row.get("source_url"):
            print(f"  ! {rid}: no source_url")
            problems += 1
        if "synthetic_seed" in (row.get("source", ""), row.get("provenance", "")):
            print(f"  ! {rid}: synthetic_seed must not appear in the corpus")
            problems += 1
        # tools/scrub_corpus.py keeps text_hash as the hash of the verbatim
        # text on purpose, so a re-collected copy is still caught as a
        # duplicate; a row whose text was changed by scrubbing is expected
        # to differ. A row scrubbed to no change must still match.
        scrubbed = bool(row.get("scrub_applied")) and bool(row.get("scrub_placeholders"))
        if not scrubbed and row.get("text_hash") != text_hash(row.get("text", "")):
            print(f"  ! {rid}: text_hash does not match text")
            problems += 1

    # pairwise near-duplicate sweep
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            score = similarity(rows[i].get("text", ""), rows[j].get("text", ""))
            if score >= NEAR_DUP_THRESHOLD:
                print(
                    f"  ! near-duplicate {score:.2f}: "
                    f"{rows[i].get('id')} ({rows[i].get('_batch')}) ~ "
                    f"{rows[j].get('id')} ({rows[j].get('_batch')})"
                )
                problems += 1

    n_pii = sum(1 for r in rows if r.get("needs_scrub"))
    print(f"\n{len(rows)} rows, {problems} problems, {n_pii} flagged for T405 scrubbing")
    if args.stats:
        _print_stats(rows)
    return 0 if problems == 0 else 1


def _print_stats(rows: list[dict[str, Any]]) -> None:
    def tally(key: str) -> str:
        counts: dict[str, int] = {}
        for r in rows:
            counts[str(r.get(key))] = counts.get(str(r.get(key)), 0) + 1
        return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))

    print(f"  label:      {tally('label')}")
    print(f"  lang:       {tally('lang')}")
    print(f"  provenance: {tally('provenance')}")
    print(f"  channel:    {tally('channel')}")
    print(f"  text_kind:  {tally('text_kind')}")
    print(f"  hard_neg:   {sum(1 for r in rows if r.get('hard_negative'))}")
    domains: dict[str, int] = {}
    for r in rows:
        domains[r.get("publisher") or "(donated)"] = (
            domains.get(r.get("publisher") or "(donated)", 0) + 1
        )
    print("  domains:")
    for d, n in sorted(domains.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {n:>3}  {d}")
    flags: dict[str, int] = {}
    for r in rows:
        for f in r.get("pii_flags", []):
            flags[f] = flags.get(f, 0) + 1
    if flags:
        print("  pii flags:  " + ", ".join(f"{k}={v}" for k, v in sorted(flags.items())))


def cmd_paste(args: argparse.Namespace) -> int:
    """Emit the block the labelling tool's import box accepts.

    annotate.html splits the box on a line containing exactly ``---`` and
    attaches one batch-level source string, so per-row provenance lives in the
    corpus JSON, not in the paste. Import one provenance at a time and set the
    source field to match.
    """
    rows = load_batch(args.batch)["items"] if args.batch else load_all_rows()
    if args.provenance:
        rows = [r for r in rows if r.get("provenance") == args.provenance]
    # Fragments are cue phrases, not messages; they are never sent to
    # annotators unless asked for explicitly.
    if not args.include_fragments:
        rows = [r for r in rows if r.get("text_kind", "message") == "message"]
    if not rows:
        print("no rows match", file=sys.stderr)
        return 1
    out = "\n---\n".join(r["text"].replace("\r\n", "\n").strip() for r in rows)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
        print(f"{len(rows)} rows -> {args.out}", file=sys.stderr)
    else:
        print(out)
    provs = sorted({r.get("provenance", "?") for r in rows})
    print(f"\n[set the import box source field to: {', '.join(provs)}]", file=sys.stderr)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    rows = load_all_rows()
    print(f"{len(rows)} rows in {CORPUS_DIR.relative_to(ROOT)}")
    if rows:
        _print_stats(rows)
    return 0


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="collect.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add one row")
    a.add_argument("--text")
    a.add_argument("--text-file")
    a.add_argument("--url", default="")
    a.add_argument("--publisher", default="")
    a.add_argument("--title", default="")
    a.add_argument("--provenance", required=True, choices=PROVENANCE)
    a.add_argument("--lang", required=True, choices=LANGS)
    a.add_argument("--label", required=True, choices=LABELS)
    a.add_argument("--channel", default="unknown", choices=CHANNELS)
    a.add_argument("--access-date", default=date.today().isoformat())
    a.add_argument("--hard-negative", action="store_true")
    a.add_argument("--text-kind", default="message", choices=TEXT_KINDS)
    a.add_argument(
        "--paraphrase", action="store_true", help="marks text as not verbatim; always rejected"
    )
    a.add_argument("--notes", default="")
    a.add_argument("--batch", required=True)
    a.add_argument("--allow-dup", action="store_true")
    a.set_defaults(func=cmd_add)

    i = sub.add_parser("ingest", help="add many rows from a staging JSON file")
    i.add_argument("file")
    i.add_argument("--batch", required=True)
    i.set_defaults(func=cmd_ingest)

    c = sub.add_parser("check", help="validate and sweep for duplicates")
    c.add_argument("--stats", action="store_true")
    c.set_defaults(func=cmd_check)

    q = sub.add_parser("paste", help="emit an import-box block")
    q.add_argument("--batch", default="")
    q.add_argument("--provenance", default="", choices=("", *PROVENANCE))
    q.add_argument("--out", default="")
    q.add_argument("--include-fragments", action="store_true")
    q.set_defaults(func=cmd_paste)

    s = sub.add_parser("stats", help="corpus composition")
    s.set_defaults(func=cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    # The corpus is Kazakh and Russian, and the default Windows console
    # codepage cannot encode either, so `paste` would die on its own output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except RowError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
