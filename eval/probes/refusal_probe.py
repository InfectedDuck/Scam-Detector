"""Refusal probe: does a provider decline to analyse scam text, and does that
differ by language?

Standalone by design. It imports nothing from `saqbol` and it is not part of the
package, because it has to keep working while the LLM client is being rewritten,
and because a measurement instrument that shares code with the thing it measures
is not an instrument.

    python eval/probes/refusal_probe.py run            # makes real, paid calls
    python eval/probes/refusal_probe.py report          # offline, from cache
    python eval/probes/refusal_probe.py selftest        # offline, no keys

NOT PART OF CI. `run` needs real provider keys and spends real money. CI runs
`ruff check src tests` and `pytest testpaths=["tests"]`, neither of which reaches
this directory. `selftest` and `report` are offline and safe to wire into CI
later if that is ever wanted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The stimuli are Cyrillic, Kazakh and Chinese; a cp1252 console would crash on
# the first one printed.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from classify import classify, is_content_policy_error  # noqa: E402

PROBE_VERSION = "1"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CACHE_DIR = HERE / "cache"
RESULTS_DIR = HERE / "results"
OVERRIDES_PATH = HERE / "overrides.json"

TEMPERATURE = 0.0
MAX_TOKENS = 400
TIMEOUT_S = 60.0
ATTEMPTS = 3


# --------------------------------------------------------------------------
# config


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_dotenv() -> None:
    """Read <repo>/.env into os.environ. Real environment variables win."""
    path = REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_hash(variant: dict) -> str:
    return sha256(variant["system"] + "\x00" + variant["user"])


def build_messages(variant: dict, text: str) -> list[dict]:
    return [
        {"role": "system", "content": variant["system"]},
        {"role": "user", "content": variant["user"].format(text=text)},
    ]


def cache_key(model: dict, variant_name: str, phash: str, item: dict, lang: str) -> str:
    return sha256(
        "|".join(
            [
                PROBE_VERSION,
                model["key"],
                model["model"],
                variant_name,
                phash,
                item["id"],
                lang,
                sha256(item["text"][lang]),
                f"t={TEMPERATURE}",
                f"m={MAX_TOKENS}",
            ]
        )
    )


def cache_path(model_key: str, key: str) -> Path:
    return CACHE_DIR / model_key / f"{key}.json"


# --------------------------------------------------------------------------
# calling


def make_client(model: dict):
    from openai import OpenAI

    api_key = os.environ.get(model["api_key_env"], "").strip()
    if not api_key:
        return None
    base_url = os.environ.get(model["base_url_env"], "").strip() or model["base_url_default"]
    return OpenAI(api_key=api_key, base_url=base_url, timeout=TIMEOUT_S, max_retries=0)


def call_once(client, model: dict, messages: list[dict]) -> dict:
    """One completion. Returns a record; never raises."""
    try:
        response = client.chat.completions.create(
            model=model["model"],
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "response_text": None,
            "finish_reason": None,
            "raw": None,
        }

    try:
        raw = response.model_dump()
    except AttributeError:
        raw = None
    choices = getattr(response, "choices", None) or []
    if not choices:
        return {
            "ok": True,
            "error": None,
            "response_text": "",
            "finish_reason": "no_choices",
            "raw": raw,
        }
    choice = choices[0]
    return {
        "ok": True,
        "error": None,
        "response_text": choice.message.content or "",
        "finish_reason": choice.finish_reason,
        "raw": raw,
    }


def fetch(
    client, model: dict, variant_name: str, variant: dict, item: dict, lang: str, *, refresh: bool
) -> dict:
    """Cached completion. A cache hit costs nothing and makes no network call."""
    phash = prompt_hash(variant)
    key = cache_key(model, variant_name, phash, item, lang)
    path = cache_path(model["key"], key)
    if path.exists() and not refresh:
        record = load_json(path)
        record["from_cache"] = True
        return record

    text = item["text"][lang]
    messages = build_messages(variant, text)
    result = {}
    for attempt in range(1, ATTEMPTS + 1):
        result = call_once(client, model, messages)
        # A content block is a determinate answer; only transport failures retry.
        if result["ok"] or is_content_policy_error(result["error"] or ""):
            break
        if attempt < ATTEMPTS:
            time.sleep(2**attempt)

    record = {
        "cache_key": key,
        "probe_version": PROBE_VERSION,
        "model_key": model["key"],
        "provider": model["provider"],
        "model": model["model"],
        "variant": variant_name,
        "prompt_sha256": phash,
        "item_id": item["id"],
        "item_class": item["class"],
        "archetype": item["archetype"],
        "language": lang,
        "text_sha256": sha256(text),
        "requested_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **result,
    }
    record["from_cache"] = False

    # Transport errors are NOT cached, so a rerun retries them instead of
    # freezing an outage into the results.
    if record["ok"] or _is_policy(record.get("error")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def _is_policy(error: str | None) -> bool:
    return bool(error) and is_content_policy_error(error)


# --------------------------------------------------------------------------
# scoring


def load_overrides() -> dict[str, dict]:
    if not OVERRIDES_PATH.exists():
        return {}
    data = load_json(OVERRIDES_PATH)
    return {row["cache_key"]: row for row in data.get("overrides", [])}


def score(records: list[dict], overrides: dict[str, dict]) -> list[dict]:
    scored = []
    for record in records:
        result = classify(
            record.get("response_text"),
            finish_reason=record.get("finish_reason"),
            error=record.get("error"),
        )
        row = {
            "cache_key": record.get("cache_key"),
            "model_key": record["model_key"],
            "model": record["model"],
            "language": record["language"],
            "item_id": record["item_id"],
            "item_class": record["item_class"],
            "archetype": record.get("archetype"),
            "auto_outcome": result.outcome,
            "rule": result.rule,
            "verdict": result.verdict,
            "cues": result.cues,
            "needs_review": result.needs_review,
            "outcome": result.outcome,
            "override_reason": None,
            "response_sha256": sha256(record.get("response_text") or ""),
            "response_chars": len(record.get("response_text") or ""),
        }
        override = overrides.get(row["cache_key"])
        if override:
            row["outcome"] = override["outcome"]
            row["override_reason"] = override.get("reason")
            row["needs_review"] = False
        scored.append(row)
    return scored


def rate_table(
    scored: list[dict], models: list[dict], languages: list[str], item_class: str | None = None
) -> list[dict]:
    cells = []
    for model in models:
        for lang in languages:
            rows = [
                r
                for r in scored
                if r["model_key"] == model["key"]
                and r["language"] == lang
                and (item_class is None or r["item_class"] == item_class)
            ]
            counts = {
                name: sum(1 for r in rows if r["outcome"] == name)
                for name in ("answered", "refused", "hedged", "error")
            }
            scored_n = counts["answered"] + counts["refused"] + counts["hedged"]
            cells.append(
                {
                    "model_key": model["key"],
                    "model_label": model["label"],
                    "language": lang,
                    "item_class": item_class or "all",
                    "n_scored": scored_n,
                    **counts,
                    "refusal_rate": (counts["refused"] / scored_n) if scored_n else None,
                    "declined_rate": ((counts["refused"] + counts["hedged"]) / scored_n)
                    if scored_n
                    else None,
                    "n_needs_review": sum(1 for r in rows if r["needs_review"]),
                    "n_overridden": sum(1 for r in rows if r["override_reason"]),
                }
            )
    return cells


def pct(cell: dict, numerator: str = "refused") -> str:
    if not cell["n_scored"]:
        return "—"
    return f"{100 * cell[numerator] / cell['n_scored']:.0f}% ({cell[numerator]}/{cell['n_scored']})"


LANG_NAMES = {"ru": "Russian", "kk": "Kazakh", "en": "English", "zh": "Chinese"}


def markdown(payload: dict) -> str:
    langs = payload["languages"]
    header = "| Model | " + " | ".join(f"{LANG_NAMES[x]} (`{x}`)" for x in langs) + " |"
    sep = "|---" * (len(langs) + 1) + "|"

    def block(cells: list[dict], numerator: str) -> list[str]:
        lines = [header, sep]
        for model in payload["models"]:
            row = [model["label"]]
            for lang in langs:
                cell = next(
                    c for c in cells if c["model_key"] == model["key"] and c["language"] == lang
                )
                row.append(pct(cell, numerator))
            lines.append("| " + " | ".join(row) + " |")
        return lines

    out = [
        "<!-- Generated by eval/probes/refusal_probe.py. Do not hand-edit. -->",
        f"# Refusal probe — {payload['variant']} prompt",
        "",
        f"Generated {payload['generated_at']} · probe v{payload['probe_version']} · "
        f"prompt `{payload['prompt_sha256'][:12]}`",
        "",
        "**Refusal rate, all 20 prompts per cell** (10 scam + 10 benign controls). "
        "Percentage with the count beside it.",
        "",
        *block(payload["cells_all"], "refused"),
        "",
        "**Refusal rate, the 10 scam prompts only.**",
        "",
        *block(payload["cells_scam"], "refused"),
        "",
        "**Hedge rate, the 10 scam prompts only** — engaged with the message but "
        "committed to no verdict. Add this to the table above for the share of scam "
        "prompts that produced no usable answer.",
        "",
        *block(payload["cells_scam"], "hedged"),
        "",
        "n = 20 per cell in the first table, 10 in the others. "
        "**Far too few for a confidence interval, and none is reported.** "
        "See docs/08_REFUSAL_PROBE.md for what this can and cannot support.",
        "",
        f"Rows needing hand adjudication: {payload['totals']['needs_review']}. "
        f"Rows overridden by hand: {payload['totals']['overridden']}. "
        f"Transport errors (excluded from denominators): {payload['totals']['errors']}. "
        f"Cells not yet run: {payload['totals']['missing']}.",
        "",
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------
# commands


def select(models: list[dict], keys: list[str] | None) -> list[dict]:
    if not keys:
        return models
    chosen = [m for m in models if m["key"] in keys]
    unknown = set(keys) - {m["key"] for m in models}
    if unknown:
        sys.exit(f"unknown model key(s): {', '.join(sorted(unknown))}")
    return chosen


def cmd_run(args) -> int:
    load_dotenv()
    items_doc = load_json(HERE / "items.json")
    models_doc = load_json(HERE / "models.json")
    prompts_doc = load_json(HERE / "prompts.json")

    variant_name = args.variant
    variant = prompts_doc["variants"][variant_name]
    items = items_doc["items"]
    languages = args.languages or items_doc["languages"]
    models = select(models_doc["models"], args.models)

    planned = len(models) * len(items) * len(languages)
    print(f"probe v{PROBE_VERSION} · variant '{variant_name}' · prompt {prompt_hash(variant)[:12]}")
    print(
        f"{len(items)} items x {len(languages)} languages x {len(models)} models "
        f"= {planned} prompts"
    )

    if args.dry_run:
        print("\n--dry-run: no network calls. Example prompt:\n")
        example = build_messages(variant, items[0]["text"][languages[0]])
        for message in example:
            print(f"[{message['role']}]\n{message['content']}\n")
        return 0

    print("\nThis makes real, paid API calls to any provider whose key is set.")
    print("Cached prompts are free; only uncached ones are sent.\n")

    records: list[dict] = []
    for model in models:
        client = make_client(model)
        if client is None:
            print(f"  {model['label']}: SKIPPED, {model['api_key_env']} not set")
            continue
        work = [(item, lang) for item in items for lang in languages]

        def one(job, _model=model, _client=client):
            item, lang = job
            return fetch(_client, _model, variant_name, variant, item, lang, refresh=args.refresh)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            got = list(pool.map(one, work))
        records.extend(got)
        hits = sum(1 for r in got if r.get("from_cache"))
        failed = sum(1 for r in got if not r["ok"] and not _is_policy(r.get("error")))
        print(
            f"  {model['label']}: {len(got)} prompts, {hits} from cache, {failed} transport errors"
        )

    if not records:
        print("\nNo model had a key set. Nothing was measured.")
        return 1
    write_report(records, models, languages, variant_name, prompt_hash(variant), items_doc)
    return 0


def read_cache(models: list[dict], variant_name: str) -> list[dict]:
    records = []
    for model in models:
        directory = CACHE_DIR / model["key"]
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            record = load_json(path)
            if record.get("variant") == variant_name:
                records.append(record)
    return records


def cmd_report(args) -> int:
    items_doc = load_json(HERE / "items.json")
    models_doc = load_json(HERE / "models.json")
    prompts_doc = load_json(HERE / "prompts.json")
    variant = prompts_doc["variants"][args.variant]
    models = select(models_doc["models"], args.models)
    records = read_cache(models, args.variant)
    if not records:
        print(f"No cached responses for variant '{args.variant}'. Run the probe first.")
        return 1
    languages = args.languages or items_doc["languages"]
    write_report(records, models, languages, args.variant, prompt_hash(variant), items_doc)
    return 0


def write_report(records, models, languages, variant_name, phash, items_doc) -> None:
    overrides = load_overrides()
    scored = score(records, overrides)
    items = items_doc["items"]
    expected = len(models) * len(items) * len(languages)

    payload = {
        "schema": "saqbol.refusal_probe.results/1",
        "probe_version": PROBE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "variant": variant_name,
        "prompt_sha256": phash,
        "languages": languages,
        "models": [
            {"key": m["key"], "label": m["label"], "model": m["model"], "provider": m["provider"]}
            for m in models
        ],
        "items": {
            "n_total": len(items),
            "n_scam": sum(1 for i in items if i["class"] == "scam"),
            "n_benign": sum(1 for i in items if i["class"] == "benign"),
            "items_sha256": sha256(json.dumps(items, ensure_ascii=False, sort_keys=True)),
        },
        "sample_size_warning": (
            "20 prompts per model-language cell (10 scam, 10 benign). Far too few for a "
            "confidence interval. No interval is reported and none should be computed "
            "from these counts."
        ),
        "cells_all": rate_table(scored, models, languages),
        "cells_scam": rate_table(scored, models, languages, "scam"),
        "cells_benign": rate_table(scored, models, languages, "benign"),
        "totals": {
            "scored": len(scored),
            "expected": expected,
            "missing": max(0, expected - len(scored)),
            "errors": sum(1 for r in scored if r["outcome"] == "error"),
            "needs_review": sum(1 for r in scored if r["needs_review"]),
            "overridden": sum(1 for r in scored if r["override_reason"]),
        },
        "records": sorted(scored, key=lambda r: (r["model_key"], r["language"], r["item_id"])),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"refusal_probe_{variant_name}.json"
    md_path = RESULTS_DIR / f"refusal_probe_{variant_name}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(payload), encoding="utf-8")

    print(f"\nwrote {json_path.relative_to(REPO_ROOT)}")
    print(f"wrote {md_path.relative_to(REPO_ROOT)}")
    if payload["totals"]["needs_review"]:
        print(
            f"\n{payload['totals']['needs_review']} row(s) need hand adjudication. "
            f"Filter records for needs_review=true, decide each one, and record the "
            f"decision in eval/probes/overrides.json with a reason."
        )
    if payload["totals"]["missing"]:
        print(f"{payload['totals']['missing']} cell(s) were not run.")


def cmd_selftest(args) -> int:
    cases = load_json(HERE / "fixtures" / "classifier_cases.json")["cases"]
    failures = []
    for case in cases:
        result = classify(
            case.get("text"),
            finish_reason=case.get("finish_reason"),
            error=case.get("error"),
        )
        if result.outcome != case["expect_outcome"]:
            failures.append((case["id"], case["expect_outcome"], result.outcome, result.rule))
        elif "expect_rule" in case and result.rule != case["expect_rule"]:
            failures.append((case["id"], case["expect_rule"], result.rule, "rule"))
    for case_id, expected, got, rule in failures:
        print(f"FAIL {case_id}: expected {expected}, got {got} ({rule})")
    print(f"{len(cases) - len(failures)}/{len(cases)} classifier cases pass")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--variant", default="intended", choices=["intended", "neutral"])
        p.add_argument("--models", nargs="*", help="model keys from models.json")
        p.add_argument("--languages", nargs="*", help="subset of ru kk en zh")

    run = sub.add_parser("run", help="make the calls (real keys, real money)")
    common(run)
    run.add_argument("--refresh", action="store_true", help="ignore the cache and re-ask")
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="rebuild results from the cache, offline")
    common(report)
    report.set_defaults(func=cmd_report)

    selftest = sub.add_parser("selftest", help="check the classifier against fixtures")
    selftest.set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
