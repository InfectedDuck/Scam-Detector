"""T501 — the evaluation harness, end to end and offline.

Every test here runs without a provider key and without a network. The smoke
matrix is the offline baseline over the twelve-row fixture split; the cells
that need a model are proven to skip with a recorded reason, never to fail.
The one metric test computes every number by hand in a comment, in the same
spirit as `test_metrics.py`: the harness assembles numbers from `metrics.py`,
and the assembly is what has to be checked.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from saqbol.core.types import LLMJudgement, Stage
from saqbol.eval.__main__ import main
from saqbol.eval.config import EvalConfig, config_hash, load_config
from saqbol.eval.leaderboard import render_leaderboard, write_leaderboard
from saqbol.eval.results import read_results
from saqbol.eval.run import CellSkipped, DatasetRow, load_split, run, score_cell
from saqbol.eval.systems import Prediction, ZeroShotJudgement

REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_CONFIG = REPO_ROOT / "eval" / "configs" / "smoke.yaml"
FULL_CONFIG = REPO_ROOT / "eval" / "configs" / "v0.1.yaml"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "eval" / "smoke.jsonl"

#: Contract section 7: the keys every results row carries.
CONTRACT_ROW_KEYS = {
    "system",
    "model",
    "split",
    "lang",
    "ablation",
    "macro_f1",
    "ci95",
    "n",
    "fpr_hard_negative",
    "abstain_rate",
}

#: No key, no network: every run in this file looks providers up in here.
NO_KEYS: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _repo_root(monkeypatch):
    """Split paths in the configs are relative to the repository root."""
    monkeypatch.chdir(REPO_ROOT)


def smoke_config(**overrides) -> EvalConfig:
    base = load_config(SMOKE_CONFIG).model_dump()
    base.update(overrides)
    return EvalConfig.model_validate(base)


# ---------------------------------------------------------------------------
# The fixture split
# ---------------------------------------------------------------------------


def test_the_fixture_split_covers_what_the_harness_needs():
    rows = load_split(FIXTURE)
    assert len(rows) == 12
    assert {r.lang for r in rows} == {"ru", "kk"}
    playbooks = {r.playbook_id for r in rows if r.label == "scam"}
    assert len(playbooks) >= 3
    assert sum(1 for r in rows if r.hard_negative) == 3
    assert all(r.label == "legit" for r in rows if r.hard_negative)
    assert any(r.label == "ambiguous" for r in rows)
    assert any(r.stage for r in rows)


def test_a_hard_negative_labelled_scam_is_a_dataset_error(tmp_path):
    split = tmp_path / "bad.jsonl"
    row = {"id": "x-1", "text": "…", "label": "scam", "lang": "ru", "hard_negative": True}
    split.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.jsonl:1"):
        load_split(split)


# ---------------------------------------------------------------------------
# The smoke run
# ---------------------------------------------------------------------------


def test_the_smoke_config_runs_offline_and_writes_the_contract_shape(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="smoke")

    assert outcome.results_path == tmp_path / "smoke" / "results.json"
    payload = json.loads(outcome.results_path.read_text(encoding="utf-8"))
    assert {"run_id", "dataset_version", "n_bootstrap", "rows"} <= set(payload)
    assert payload["n_bootstrap"] == 10_000
    assert len(payload["rows"]) == 3  # rules_only x test_press x {all, ru, kk} x none
    for row in payload["rows"]:
        assert set(row) >= CONTRACT_ROW_KEYS
        assert row["system"] == "rules_only"
        assert row["model"] == "none"
        lo, hi = row["ci95"]
        assert 0.0 <= lo <= row["macro_f1"] <= hi <= 1.0
        assert row["seed"] == 20260908
    assert not outcome.skipped
    # The file is the record: it reads back through the contract reader, with
    # the floats rounded the way results.py writes them.
    read_back = read_results(outcome.results_path)
    assert [(r.system, r.lang, r.n) for r in read_back.rows] == [
        (r.system, r.lang, r.n) for r in outcome.results.rows
    ]
    assert [r.macro_f1 for r in read_back.rows] == pytest.approx(
        [r.macro_f1 for r in outcome.results.rows], abs=1e-6
    )


def test_the_manifest_records_provenance_counts_and_skips(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="m")
    manifest = json.loads(outcome.manifest_path.read_text(encoding="utf-8"))

    assert manifest["config_hash"] == config_hash(load_config(SMOKE_CONFIG))
    assert manifest["config_hash"].startswith("sha256:")
    assert "git_commit" in manifest and "timestamp" in manifest
    assert manifest["seed"] == 20260908
    split = manifest["splits"]["test_press"]
    assert split["exists"] is True
    assert split["n_rows"] == 12
    assert split["by_lang"] == {"kk": 5, "ru": 7}
    assert split["n_hard_negative"] == 3
    assert manifest["cells"] == {"planned": 3, "executed": 3, "skipped": 0}
    assert manifest["skipped"] == []
    # Every executed row is traceable: one prediction line per row per cell.
    lines = outcome.predictions_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 12 + 7 + 5


def test_language_filtering_uses_the_rows_lang_field(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="lang")
    by_lang = {row.lang: row for row in outcome.results.rows}
    assert by_lang["all"].n_rows == 12
    assert by_lang["ru"].n_rows == 7
    assert by_lang["kk"].n_rows == 5
    # The one ambiguous row is Kazakh and has no place in a scam/legit F1.
    assert by_lang["kk"].n_ambiguous == 1
    assert by_lang["kk"].n == 4


def test_two_runs_give_identical_numbers(tmp_path):
    config = load_config(SMOKE_CONFIG)
    first = run(config, out_dir=tmp_path / "a", env=NO_KEYS, run_id="same")
    second = run(config, out_dir=tmp_path / "b", env=NO_KEYS, run_id="same")
    assert first.results.rows == second.results.rows
    assert first.results_path.read_bytes() == second.results_path.read_bytes()
    assert first.predictions_path.read_bytes() == second.predictions_path.read_bytes()


def test_limit_caps_the_rows_in_every_cell(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="lim", limit=4)
    assert {row.n_rows for row in outcome.results.rows} == {4}


# ---------------------------------------------------------------------------
# Cells that cannot run
# ---------------------------------------------------------------------------


def test_a_cell_that_needs_a_provider_key_is_skipped_with_a_reason(tmp_path):
    config = smoke_config(
        systems=["rules_only", "llm_zeroshot", "hybrid"],
        models=["deepseek-chat"],
        languages=["all"],
    )
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="keys")

    assert [row.system for row in outcome.results.rows] == ["rules_only"]
    skipped = {(s.cell.system, s.cell.model): s.reason for s in outcome.skipped}
    assert set(skipped) == {("llm_zeroshot", "deepseek-chat"), ("hybrid", "deepseek-chat")}
    for reason in skipped.values():
        assert "DEEPSEEK_API_KEY" in reason
    manifest = json.loads(outcome.manifest_path.read_text(encoding="utf-8"))
    assert manifest["cells"] == {"planned": 3, "executed": 1, "skipped": 2}
    assert {s["reason"] for s in manifest["skipped"]} == set(skipped.values())


def test_a_missing_split_file_is_reported_not_raised(tmp_path):
    # The full matrix, pointed at split files that do not exist.
    base = load_config(FULL_CONFIG).model_dump()
    base["splits"] = {
        split: (tmp_path / "absent" / f"{split}.jsonl").as_posix() for split in base["splits"]
    }
    config = EvalConfig.model_validate(base)
    for path in config.splits.values():
        assert not Path(path).exists()

    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="missing")

    assert outcome.results.rows == []
    assert len(outcome.skipped) == len(outcome.manifest["skipped"]) > 0
    assert all(s.reason.startswith("split file missing: ") for s in outcome.skipped)
    assert all(not entry["exists"] for entry in outcome.manifest["splits"].values())
    assert outcome.results_path.is_file()


def test_ablations_run_or_skip_for_the_reason_the_split_gives(tmp_path):
    config = smoke_config(
        languages=["all"],
        ablations=["none", "cue_masked", "no_playbook_context", "translated"],
    )
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="abl")

    executed = {row.ablation for row in outcome.results.rows}
    assert executed == {"none", "cue_masked"}
    reasons = {s.cell.ablation: s.reason for s in outcome.skipped}
    assert "no retrieval" in reasons["no_playbook_context"]
    assert "no translations" in reasons["translated"]
    # Masking changes the input, so the masked cell scored different text.
    lines = [
        json.loads(line)
        for line in outcome.predictions_path.read_text(encoding="utf-8").splitlines()
    ]
    assert sum(1 for line in lines if line["ablation"] == "cue_masked") == 12


def test_the_translated_ablation_runs_on_the_rows_that_carry_a_translation(tmp_path):
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    for row in rows[:5]:
        row["text_translated"] = row["text"]
    split = tmp_path / "translated.jsonl"
    split.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    config = smoke_config(
        splits={"test_press": str(split)}, languages=["all"], ablations=["translated"]
    )
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="tr")
    assert not outcome.skipped
    (row,) = outcome.results.rows
    assert row.ablation == "translated"
    assert row.n_rows == 5


# ---------------------------------------------------------------------------
# Scoring, by hand
# ---------------------------------------------------------------------------


def _row(n: int, label: str, **kwargs) -> DatasetRow:
    return DatasetRow(id=f"r{n}", text=f"text {n}", label=label, lang="ru", **kwargs)


def test_score_cell_matches_hand_computation():
    a, b = "kz.bank_security_call", "kz.delivery_link"
    rows = [
        _row(1, "scam", playbook_id=a, stage="hook"),
        _row(2, "scam", playbook_id=a, stage="pressure"),
        _row(3, "scam", playbook_id=b),
        _row(4, "scam", playbook_id=b, stage="hook"),
        _row(5, "legit", hard_negative=True),
        _row(6, "legit", hard_negative=True),
        _row(7, "legit", hard_negative=True),
        _row(8, "legit"),
        _row(9, "ambiguous"),
    ]
    predictions = [
        Prediction(band="scam", playbook_id=a, stage="hook"),
        Prediction(band="scam", playbook_id=a, stage="contact"),
        Prediction(band="suspicious", playbook_id=b),
        Prediction(band="likely_safe"),
        Prediction(band="scam"),  # a false positive on a hard negative
        Prediction(band="likely_safe"),
        Prediction(band="unsure", error="model call failed"),
        Prediction(band="likely_safe"),
        Prediction(band="suspicious"),
    ]
    score = score_cell(rows, predictions, seed=1, n_bootstrap=200)

    # Binary, over the answered non-ambiguous rows 1-6 and 8 (row 7 abstained,
    # row 9 is ambiguous):
    #   true  scam scam scam scam  legit legit legit
    #   pred  scam scam scam legit scam  legit legit
    #   scam:  tp 3, support_true 4, support_pred 4 -> 6/8 = 0.75
    #   legit: tp 2, support_true 3, support_pred 3 -> 4/6 = 2/3
    assert score.macro_f1.n == 7
    assert score.macro_f1.point == pytest.approx((0.75 + 2 / 3) / 2)
    assert score.extra["per_class_f1"] == pytest.approx({"legit": 2 / 3, "scam": 0.75})
    assert score.extra["selective_risk"] == pytest.approx(2 / 7)
    # One abstention in nine rows.
    assert score.abstain_rate == pytest.approx(1 / 9)
    assert score.extra["coverage"] == pytest.approx(8 / 9)
    assert score.extra["n_rows"] == 9
    assert score.extra["n_answered"] == 8
    assert score.extra["n_ambiguous"] == 1
    # Hard negatives 5, 6, 7: one flagged, one cleared, one abstained -> 1/3,
    # with the abstention kept in the denominator.
    assert score.fpr_hard_negative == pytest.approx(1 / 3)
    assert score.extra["n_hard_negative"] == 3
    # Playbooks over the answered scam rows 1-4: gold A A B B, predicted A A B none.
    #   A: 2*2/(2+2) = 1.0; B: 2*1/(2+1) = 2/3; none: 0/(0+1) = 0 -> mean 5/9
    assert score.extra["playbook_n"] == 4
    assert score.extra["playbook_macro_f1"] == pytest.approx((1.0 + 2 / 3 + 0.0) / 3)
    # Stage: rows 1 and 2 have the right playbook and a gold stage; row 3 has
    # no gold stage, row 4 the wrong playbook. One of the two is right.
    assert score.extra["stage_n_eligible"] == 2
    assert score.extra["stage_n_correct"] == 1
    assert score.extra["stage_accuracy"] == pytest.approx(0.5)
    assert score.extra["n_errors"] == 1


def test_a_system_that_answers_nothing_has_no_macro_f1():
    rows = [_row(1, "scam", playbook_id="kz.fake_store"), _row(2, "legit")]
    predictions = [Prediction(band="unsure"), Prediction(band="unsure")]
    with pytest.raises(CellSkipped, match="answered none of the 2"):
        score_cell(rows, predictions, seed=1, n_bootstrap=10)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_original_is_an_alias_for_the_contract_ablation_none():
    aliased = smoke_config(ablations=["original", "cue_masked"])
    plain = smoke_config(ablations=["none", "cue_masked"])
    assert aliased.ablations == ["none", "cue_masked"]
    assert config_hash(aliased) == config_hash(plain)
    assert config_hash(aliased) != config_hash(smoke_config(seed=1))


def test_a_model_system_without_models_is_rejected_at_load():
    with pytest.raises(ValueError, match="models"):
        smoke_config(systems=["rules_only", "hybrid"], models=[])


# ---------------------------------------------------------------------------
# Leaderboard and CLI
# ---------------------------------------------------------------------------


def test_the_leaderboard_prints_intervals_and_makes_no_ranking_claim(tmp_path):
    config = smoke_config(
        systems=["rules_only", "hybrid"], models=["deepseek-chat"], languages=["all", "kk"]
    )
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="lb")
    text = render_leaderboard(outcome.results, skipped=outcome.manifest["skipped"])

    assert "beats" not in text
    assert "## test_press" in text
    for row in outcome.results.rows:
        lo, hi = row.ci95
        assert f"{row.macro_f1:.3f} [{lo:.3f}, {hi:.3f}]" in text
    assert "## Cells not run" in text
    assert "DEEPSEEK_API_KEY" in text

    written = write_leaderboard(outcome.results_path, tmp_path / "lb" / "leaderboard.md")
    assert written.read_text(encoding="utf-8") == text


def test_the_cli_runs_the_smoke_matrix_and_renders_the_leaderboard(tmp_path, capsys):
    out = tmp_path / "cli"
    assert main(["run", "--config", str(SMOKE_CONFIG), "--out", str(out), "--run-id", "r"]) == 0
    assert (out / "r" / "results.json").is_file()
    assert (out / "r" / "manifest.json").is_file()
    assert "3 of 3 cells executed" in capsys.readouterr().out

    results = out / "r" / "results.json"
    board = out / "r" / "leaderboard.md"
    assert main(["leaderboard", "--results", str(results), "--out", str(board)]) == 0
    assert "beats" not in board.read_text(encoding="utf-8")

    # A system the config does not list is an error, not a silent no-op.
    bad = ["run", "--config", str(SMOKE_CONFIG), "--out", str(out), "--systems", "hybrid"]
    assert main(bad) == 2
    assert "not in the config" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The model path, with a client that never leaves the process
# ---------------------------------------------------------------------------


class StubClient:
    """Answers every model call offline, the way a replay client would."""

    def __init__(self) -> None:
        self.calls = 0

    async def structured(self, *, model, system, user, schema, temperature):
        self.calls += 1
        stats = SimpleNamespace(model=model, latency_ms=1, cached=True)
        scammy = "kaspi" in user.lower()
        if schema is ZeroShotJudgement:
            if scammy:
                judgement = schema(
                    label="scam", playbook_id="kz.bank_security_call", stage=Stage.HOOK
                )
            else:
                judgement = schema(label="legit", confidence=0.8)
            return judgement, stats
        judgement = LLMJudgement(
            playbook_id="kz.bank_security_call" if scammy else None,
            confidence=0.9 if scammy else 0.1,
            stage=Stage.HOOK if scammy else None,
        )
        return judgement, stats


def test_model_systems_run_through_a_supplied_client_without_a_key(tmp_path):
    stub = StubClient()
    config = smoke_config(
        systems=["llm_zeroshot", "hybrid"],
        models=["stub-model"],
        languages=["all"],
        ablations=["none", "no_playbook_context"],
    )
    outcome = run(
        config, out_dir=tmp_path, env=NO_KEYS, run_id="stub", clients={"stub-model": stub}
    )

    cells = {(row.system, row.ablation) for row in outcome.results.rows}
    assert cells == {
        ("llm_zeroshot", "none"),
        ("hybrid", "none"),
        ("hybrid", "no_playbook_context"),
    }
    assert [s.cell.system for s in outcome.skipped] == ["llm_zeroshot"]
    assert "never sees playbook context" in outcome.skipped[0].reason
    assert stub.calls == 3 * 12
    for row in outcome.results.rows:
        assert row.model == "stub-model"
        assert row.prompt_hash.startswith("sha256:")
        assert "n_errors" not in (row.model_extra or {})

    (zeroshot,) = [r for r in outcome.results.rows if r.system == "llm_zeroshot"]
    # The stub never abstains, and names the playbook on the two Kaspi rows,
    # which carry the gold stages hook and pressure; it says hook for both.
    assert zeroshot.abstain_rate == 0.0
    assert zeroshot.stage_n_eligible == 2
    assert zeroshot.stage_n_correct == 1
