"""Offline checks for the standalone refusal probe's cache and spend guard."""

from argparse import Namespace

from eval.probes import refusal_probe as probe


def test_report_reads_only_cassettes_for_current_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "CACHE_DIR", tmp_path)
    model = {"key": "sample", "model": "sample-v2"}
    variant = {"system": "system", "user": "Read {text}"}
    item = {"id": "one", "text": {"en": "new text"}}
    old_item = {"id": "one", "text": {"en": "old text"}}
    old_key = probe.cache_key(model, "intended", probe.prompt_hash(variant), old_item, "en")
    old_path = probe.cache_path(model["key"], old_key)
    old_path.parent.mkdir(parents=True)
    old_path.write_text('{"cache_key": "' + old_key + '", "model": "sample-v2"}', encoding="utf-8")

    assert probe.read_cache([model], "intended", variant, [item], ["en"]) == []

    key = probe.cache_key(model, "intended", probe.prompt_hash(variant), item, "en")
    path = probe.cache_path(model["key"], key)
    path.write_text('{"cache_key": "' + key + '", "model": "sample-v2"}', encoding="utf-8")
    assert len(probe.read_cache([model], "intended", variant, [item], ["en"])) == 1


def test_live_probe_rejects_over_budget_before_creating_client(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(probe, "load_dotenv", lambda: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-placeholder")
    monkeypatch.setattr(
        probe, "make_client", lambda model: (_ for _ in ()).throw(AssertionError("live client"))
    )
    args = Namespace(
        variant="intended",
        models=["deepseek-flash"],
        languages=["en"],
        dry_run=False,
        max_new_cells=1,
        refresh=False,
    )

    assert probe.cmd_run(args) == 2
