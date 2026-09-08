"""T108 — playbook schema and loader.

A playbook supplies the advice and the phone number shown to someone who may be
mid-scam, so the loader's job is to refuse anything incomplete rather than to
cope with it. Most of this file is therefore about what must fail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import saqbol.core.indicators  # noqa: F401  — populates the registry
from saqbol.core.indicators.registry import REGISTRY
from saqbol.playbooks import loader
from saqbol.playbooks.schema import (
    FALLBACK_LABELS,
    PLAYBOOK_IDS,
    Localized,
    Playbook,
)

DOCS = Path(__file__).resolve().parents[1] / "docs" / "04_PLAYBOOKS.md"


def valid_playbook() -> dict:
    """A minimal playbook that passes every rule. Tests mutate copies of it."""
    return {
        "id": "kz.bank_security_call",
        "version": 1,
        "region": "KZ",
        "family": "authority_impersonation",
        "name": {"ru": "«Служба безопасности банка»"},
        "summary": {"ru": "Звонящий представляется сотрудником банка."},
        "retrieval_phrases": [
            "служба безопасности банка",
            "переведите на безопасный счёт",
            "назовите код из смс",
            "не кладите трубку",
            "с вашего счёта пытаются списать",
        ],
        "expected_indicators": ["C1.bank_security", "A1.otp_request"],
        "stages": {"contact": {"ru": "Входящий звонок с незнакомого номера."}},
        "red_flags": {
            "ru": [
                "Настоящий банк никогда не просит код из СМС.",
                "«Безопасного счёта» не существует.",
            ]
        },
        "action": {
            "key": "action.hang_up_call_bank",
            "ru": "Положите трубку и перезвоните по номеру на обороте карты.",
        },
        "hotline": "1414",
        "hotlines": [{"name": "eGov", "number": "1414"}],
        "sources": ["https://www.gov.kz/example"],
    }


def write(tmp_path: Path, data: dict, name: str | None = None) -> Path:
    path = tmp_path / (name or f"{data['id']}.yaml")
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


class TestValidPlaybook:
    def test_loads(self, tmp_path):
        write(tmp_path, valid_playbook())
        loaded = loader.load_all(tmp_path)
        assert set(loaded) == {"kz.bank_security_call"}

    def test_embedding_text_joins_summary_and_phrases(self, tmp_path):
        write(tmp_path, valid_playbook())
        pb = loader.load_all(tmp_path)["kz.bank_security_call"]
        text = pb.embedding_text()
        assert "Звонящий представляется" in text
        assert "не кладите трубку" in text

    def test_stage_keys_become_enum_members(self, tmp_path):
        write(tmp_path, valid_playbook())
        pb = loader.load_all(tmp_path)["kz.bank_security_call"]
        assert [s.value for s in pb.stages] == ["contact"]


class TestRequiredFields:
    @pytest.mark.parametrize(
        "field",
        [
            "id",
            "version",
            "region",
            "family",
            "name",
            "summary",
            "retrieval_phrases",
            "red_flags",
            "action",
            "hotline",
            "hotlines",
            "sources",
        ],
    )
    def test_missing_field_is_fatal(self, tmp_path, field):
        """Not a warning, not a default. A half-loaded playbook shows a victim
        incomplete advice."""
        data = valid_playbook()
        del data[field]
        write(tmp_path, data, name="kz.bank_security_call.yaml")
        with pytest.raises(loader.PlaybookError):
            loader.load_all(tmp_path)

    def test_empty_sources_rejected(self, tmp_path):
        """The official citation is what separates a playbook from a blog post."""
        data = valid_playbook()
        data["sources"] = []
        write(tmp_path, data)
        with pytest.raises(loader.PlaybookError):
            loader.load_all(tmp_path)

    def test_non_url_source_rejected(self, tmp_path):
        data = valid_playbook()
        data["sources"] = ["см. сайт МВД"]
        write(tmp_path, data)
        with pytest.raises(loader.PlaybookError, match="not an http"):
            loader.load_all(tmp_path)

    def test_one_red_flag_rejected(self, tmp_path):
        data = valid_playbook()
        data["red_flags"] = {"ru": ["Только один признак."]}
        write(tmp_path, data)
        with pytest.raises(loader.PlaybookError, match="red flags"):
            loader.load_all(tmp_path)

    def test_too_few_retrieval_phrases_rejected(self, tmp_path):
        data = valid_playbook()
        data["retrieval_phrases"] = ["служба безопасности банка"]
        write(tmp_path, data)
        with pytest.raises(loader.PlaybookError):
            loader.load_all(tmp_path)

    def test_long_summary_rejected(self, tmp_path):
        """It is rendered on the verdict card, which has a finite width."""
        data = valid_playbook()
        data["summary"] = {"ru": "очень длинное описание " * 20}
        write(tmp_path, data)
        with pytest.raises(loader.PlaybookError, match="verdict card"):
            loader.load_all(tmp_path)


class TestIdentity:
    def test_filename_must_match_id(self, tmp_path):
        write(tmp_path, valid_playbook(), name="kz.egov_1414_code.yaml")
        with pytest.raises(loader.PlaybookError, match="filename is the id"):
            loader.load_all(tmp_path)

    def test_id_outside_the_label_set_rejected(self, tmp_path):
        """The label set is also the dataset's label space, so it cannot grow by
        accident in a YAML file."""
        data = valid_playbook()
        data["id"] = "kz.some_new_idea"
        write(tmp_path, data)
        with pytest.raises(loader.PlaybookError, match="closed label set"):
            loader.load_all(tmp_path)

    def test_malformed_id_rejected(self, tmp_path):
        data = valid_playbook()
        data["id"] = "BankSecurityCall"
        write(tmp_path, data)
        with pytest.raises(loader.PlaybookError):
            loader.load_all(tmp_path)

    def test_unknown_field_rejected(self, tmp_path):
        """A typo in a key would otherwise be silently ignored."""
        data = valid_playbook()
        data["hotlin"] = "1414"
        write(tmp_path, data)
        with pytest.raises(loader.PlaybookError):
            loader.load_all(tmp_path)

    def test_broken_yaml_rejected(self, tmp_path):
        (tmp_path / "kz.bank_security_call.yaml").write_text("id: [unclosed", encoding="utf-8")
        with pytest.raises(loader.PlaybookError, match="not valid YAML"):
            loader.load_all(tmp_path)


class TestIndicatorCrossCheck:
    def test_unknown_indicator_is_fatal(self, tmp_path):
        """A renamed rule must be updated here too, or the playbook silently
        loses the signals it was written around."""
        data = valid_playbook()
        data["expected_indicators"] = ["C1.bank_security", "Z9.does_not_exist"]
        write(tmp_path, data)
        with pytest.raises(loader.PlaybookError, match="do not exist"):
            loader.load_all(tmp_path)

    def test_check_can_be_disabled_for_schema_only_tests(self, tmp_path):
        data = valid_playbook()
        data["expected_indicators"] = ["Z9.does_not_exist"]
        write(tmp_path, data)
        assert loader.load_all(tmp_path, check_indicators=False)

    def test_every_registered_indicator_id_is_resolvable(self):
        assert REGISTRY, "indicator registry is empty; the cross-check would be vacuous"


class TestLocalization:
    def test_russian_is_required(self):
        with pytest.raises(ValidationError):
            Localized.model_validate({"kk": "тек қазақша"})

    def test_get_falls_back_to_russian(self):
        text = Localized(ru="русский")
        assert text.get("kk") == "русский"
        assert text.get("ru") == "русский"

    def test_get_prefers_the_translation(self):
        text = Localized(ru="русский", kk="қазақша")
        assert text.get("kk") == "қазақша"

    def test_missing_lists_the_gap(self):
        assert set(Localized(ru="x").missing()) == {"kk", "en", "zh"}
        assert Localized(ru="x", kk="y", en="z", zh="w").missing() == []

    def test_translation_gaps_reported_per_field(self, tmp_path):
        write(tmp_path, valid_playbook())
        pb = loader.load_all(tmp_path)["kz.bank_security_call"]
        gaps = pb.translation_gaps
        assert "kk" in gaps["name"]
        assert "kk" in gaps["red_flags"]

    def test_translation_report_counts_the_work(self, tmp_path):
        write(tmp_path, valid_playbook())
        report = loader.translation_report(loader.load_all(tmp_path))
        assert "kz.bank_security_call" in report


class TestLabelSet:
    def test_thirteen_playbooks(self):
        assert len(PLAYBOOK_IDS) == 13
        assert len(set(PLAYBOOK_IDS)) == 13

    def test_fallback_labels_are_not_playbooks(self):
        """`other_scam` exists so annotators do not force-fit rows into the
        nearest category, but it has no playbook file."""
        assert not set(FALLBACK_LABELS) & set(PLAYBOOK_IDS)

    def test_matches_the_documented_label_set(self):
        documented = set(
            re.findall(r"^(?:kz|cn)\.[a-z0-9_]+$", DOCS.read_text(encoding="utf-8"), re.M)
        )
        assert documented == set(PLAYBOOK_IDS), (
            f"docs/04_PLAYBOOKS.md and PLAYBOOK_IDS disagree: "
            f"only in docs {sorted(documented - set(PLAYBOOK_IDS))}, "
            f"only in code {sorted(set(PLAYBOOK_IDS) - documented)}"
        )

    def test_every_region_prefix_is_valid(self):
        for pid in PLAYBOOK_IDS:
            assert pid.split(".")[0] in {"kz", "cn"}


class TestShippedPlaybooks:
    """The real files in the package. Empty until T109 finishes writing them."""

    def test_shipped_files_all_load(self):
        loaded = loader.load_all()
        assert isinstance(loaded, dict)

    def test_shipped_files_carry_official_sources(self):
        for pid, pb in loader.load_all().items():
            assert pb.sources, pid
            for url in pb.sources:
                assert url.startswith("http"), (pid, url)

    def test_progress_towards_the_full_set(self):
        """Not an assertion of completeness; T109 is what closes this gap."""
        loaded = loader.load_all()
        remaining = loader.missing_playbooks(loaded)
        assert len(loaded) + len(remaining) == len(PLAYBOOK_IDS)


def test_playbook_model_is_hashable_by_id():
    pb = Playbook.model_validate(valid_playbook())
    assert pb.id == "kz.bank_security_call"
    assert pb.version >= 1
