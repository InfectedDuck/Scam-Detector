"""saqbol.db.repo: the shared store behind the API and the bot."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

pytest.importorskip("sqlalchemy", reason="the persistence layer needs the 'api' extra")
pytest.importorskip("pgvector", reason="the persistence layer needs the 'api' extra")

from sqlalchemy import select

from saqbol.core.types import Band, Components, Lang, Verdict
from saqbol.db.hashing import hash_actor
from saqbol.db.models import STATUS_PENDING, Check, DatasetCandidate, Feedback
from saqbol.db.repo import Store, UnknownCheck, session_for

SECRET = b"t" * 48
ACTOR = hash_actor("123456789", secret=SECRET)
OTHER = hash_actor("987654321", secret=SECRET)

#: Luhn-valid test card, the kind of thing a scam victim pastes.
RAW = "Переведите на карту 4111 1111 1111 1111 срочно, код 1234"


def verdict(band: Band = Band.SCAM, playbook: str | None = "kz.bank_security_call") -> Verdict:
    return Verdict(
        check_id=uuid.uuid4().hex,
        band=band,
        risk=0.91 if band is Band.SCAM else 0.3,
        playbook_id=playbook,
        language=Lang.RU,
        components=Components(rule_norm=0.9, retrieval_sim=0.4, llm_conf=0.8),
        model="deepseek-chat",
        latency_ms=812,
    )


@pytest.fixture
def store() -> Store:
    return Store.in_memory()


class TestRecordCheck:
    def test_stores_scrubbed_text_under_the_verdicts_own_id(self, store: Store) -> None:
        v = verdict()
        cid = store.record_check(v, actor_hash=ACTOR, text=RAW, surface="telegram")

        assert cid == uuid.UUID(v.check_id)
        row = store.get_check(v.check_id)
        assert row is not None
        assert "4111" not in row.text_scrubbed
        assert "<CARD>" in row.text_scrubbed
        assert row.band == "scam"
        assert row.lang == "ru"
        assert row.playbook_id == "kz.bank_security_call"
        assert row.model == "deepseek-chat"
        assert row.verdict["band"] == "scam"
        assert row.consent_dataset is False
        assert len(row.text_sha256) == 64

    def test_rules_only_verdict_gets_a_model_name(self, store: Store) -> None:
        v = verdict()
        v.model = ""
        store.record_check(v, actor_hash=ACTOR, text="hi", surface="web")
        assert store.get_check(v.check_id).model == "rules_only"

    def test_rejects_unknown_surface_and_input_type(self, store: Store) -> None:
        with pytest.raises(ValueError):
            store.record_check(verdict(), actor_hash=ACTOR, text="x", surface="sms")
        with pytest.raises(ValueError):
            store.record_check(
                verdict(), actor_hash=ACTOR, text="x", surface="web", input_type="voice"
            )

    def test_rejects_a_raw_actor_identifier(self, store: Store) -> None:
        with pytest.raises(ValueError):
            store.record_check(verdict(), actor_hash="123456789", text="x", surface="web")


class TestFeedback:
    def test_vote_lands_against_the_check(self, store: Store) -> None:
        v = verdict()
        store.record_check(v, actor_hash=ACTOR, text=RAW, surface="telegram")
        fid = store.record_feedback(v.check_id, was_correct=False, comment="it was my bank")

        with session_for(store) as s:
            row = s.get(Feedback, fid)
            assert row.check_id == uuid.UUID(v.check_id)
            assert row.was_correct is False
            assert row.comment == "it was my bank"

    def test_unknown_or_malformed_id_is_refused(self, store: Store) -> None:
        with pytest.raises(UnknownCheck):
            store.record_feedback(uuid.uuid4().hex, was_correct=True)
        with pytest.raises(UnknownCheck):
            store.record_feedback("not-an-id", was_correct=True)


class TestDatasetCandidates:
    def test_submission_is_pending_and_uses_the_stored_scrubbed_text(self, store: Store) -> None:
        v = verdict()
        store.record_check(v, actor_hash=ACTOR, text=RAW, surface="telegram")
        cand_id = store.submit_candidate(v.check_id)

        with session_for(store) as s:
            cand = s.get(DatasetCandidate, cand_id)
            assert cand.status == STATUS_PENDING
            assert cand.source == "donated"
            assert "<CARD>" in cand.text_scrubbed
            assert "4111" not in cand.text_scrubbed
            assert s.get(Check, uuid.UUID(v.check_id)).consent_dataset is True

    def test_unknown_check_is_refused(self, store: Store) -> None:
        with pytest.raises(UnknownCheck):
            store.submit_candidate(uuid.uuid4().hex)


class TestRateLimit:
    def test_limit_is_per_actor_per_day(self, store: Store) -> None:
        today = date(2026, 9, 8)
        results = [store.spend_check(ACTOR, limit=3, day=today) for _ in range(4)]
        assert results == [True, True, True, False]
        assert store.count_today(ACTOR, day=today) == 3

        assert store.spend_check(OTHER, limit=3, day=today) is True
        assert store.spend_check(ACTOR, limit=3, day=today + timedelta(days=1)) is True
        assert store.count_today(ACTOR, day=today) == 3


class TestStats:
    def test_daily_counts_and_public_shape(self, store: Store) -> None:
        store.record_check(verdict(), actor_hash=ACTOR, text=RAW, surface="telegram")
        store.record_check(verdict(), actor_hash=OTHER, text="second", surface="web")
        store.record_check(
            verdict(Band.UNSURE, playbook="kz.delivery_link"),
            actor_hash=ACTOR,
            text="third",
            surface="web",
        )
        today = datetime.now(UTC).date()
        day = store.materialize_day(today)

        assert (day.checks, day.unique_actors, day.scam_count, day.unsure_count) == (3, 2, 2, 1)
        assert day.top_playbook == "kz.bank_security_call"

        summary = store.stats_summary(days=7).as_dict()
        assert set(summary) == {"total_checks", "unique_users", "scam_share", "days", "updated_at"}
        assert summary["total_checks"] == 3
        assert summary["scam_share"] == pytest.approx(2 / 3, abs=1e-3)
        assert summary["days"][-1]["day"] == today.isoformat()
        assert not any("text" in key for entry in summary["days"] for key in entry)

    def test_materialize_is_idempotent(self, store: Store) -> None:
        store.record_check(verdict(), actor_hash=ACTOR, text=RAW, surface="telegram")
        today = datetime.now(UTC).date()
        store.materialize_day(today)
        store.materialize_day(today)
        with session_for(store) as s:
            from saqbol.db.models import StatsDaily

            rows = s.execute(select(StatsDaily)).scalars().all()
        assert len(rows) == 1 and rows[0].checks == 1
