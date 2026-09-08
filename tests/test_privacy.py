"""T405 — the PII scrubber, and the guarantee over the committed corpus.

Positive cases cover every format that occurs in Kazakhstan and China.
Negative cases are the detection signals the scrubber must leave alone:
short codes, tenge amounts, dates. The corpus test at the end is the task's
acceptance criterion: no phone number, identification number or card number
survives in any row of any batch under data/corpus.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from saqbol.core.privacy import PLACEHOLDER, contains_unmasked_pii, find_pii, scrub

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
TOOL = ROOT / "tools" / "scrub_corpus.py"

# Luhn-valid numbers from the standard test-card sets. Not real accounts.
TEST_CARD = "4242 4242 4242 4242"
TEST_AMEX = "3782 822463 10005"
# Same layout, checksum deliberately broken: a mistyped card is still a card.
BROKEN_CARD = "4400 4301 2345 6780"
# Reserved-range identification number: born 1 January 2000, century digit 5.
TEST_IIN = "000101500123"
# Structure of a Kazakhstani account, not an issued one.
TEST_IBAN = "KZ86125KZT5004100100"


def labels(text: str) -> list[str]:
    return [span.label for span in find_pii(text)]


def masked(text: str) -> str:
    return scrub(text).text


# --- telephone numbers -----------------------------------------------------


KZ_PHONES = [
    "+7 707 123 45 67",
    "+7-707-123-45-67",
    "+7.707.123.45.67",
    "+7 (707) 123-45-67",
    "+7(707)1234567",
    "+77071234567",
    "8 707 123 45 67",
    "8 (707) 123-45-67",
    "8-707-123-45-67",
    "87071234567",
    "8 (727) 330-00-00",
    "+7 916 123 45 67",
]
CN_PHONES = ["+86 138 0013 8000", "+86 13800138000", "+8613800138000", "13800138000"]


class TestPhones:
    @pytest.mark.parametrize("raw", KZ_PHONES + CN_PHONES)
    def test_in_context(self, raw):
        result = scrub(f"Звоните {raw} сейчас")
        assert result.text == "Звоните <PHONE> сейчас"
        assert result.applied == ["phone"]

    @pytest.mark.parametrize("raw", KZ_PHONES + CN_PHONES)
    def test_bare(self, raw):
        assert masked(raw) == "<PHONE>"

    @pytest.mark.parametrize(
        "raw",
        [
            "+7 707 123 45 67",  # no-break spaces
            "+7 707 123‑45‑67",  # non-breaking hyphens
            "+7 707 123–45–67",  # en dashes
        ],
    )
    def test_typographic_separators(self, raw):
        assert masked(f"тел {raw}.") == "тел <PHONE>."

    def test_unicode_outside_the_span_is_untouched(self):
        assert masked("Тел: +7 707 123 45 67 — срочно") == "Тел: <PHONE> — срочно"

    @pytest.mark.parametrize("sep", [" ", "\n", ", ", " / "])
    def test_two_numbers(self, sep):
        text = f"87071234567{sep}87071234568"
        assert masked(text) == f"<PHONE>{sep}<PHONE>"

    def test_two_formatted_numbers(self):
        assert masked("+7 707 123 45 67 8 707 765 43 21") == "<PHONE> <PHONE>"

    def test_glued_to_a_word(self):
        assert masked("WhatsApp+77071234567") == "WhatsApp+<PHONE>"

    def test_number_before_a_short_code(self):
        assert masked("Звоните 8 707 123 45 67 или 1414") == "Звоните <PHONE> или 1414"
        assert masked("+7 707 123 45 67 1414") == "<PHONE> 1414"

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("87071234567 5000 тг", "<PHONE> 5000 тг"),
            ("+7 707 123 45 67 500 тг", "<PHONE> 500 тг"),
            ("Kaspi 87071234567 350 000 тг", "Kaspi <PHONE> 350 000 тг"),
        ],
    )
    def test_number_before_an_amount(self, text, expected):
        """The amount next to the phone must not reserve the phone's digits."""
        assert masked(text) == expected

    def test_unknown_format_is_still_masked(self):
        assert masked("call +44 20 7946 0958 now") == "call <PHONE> now"

    def test_too_short_is_not_a_phone(self):
        assert labels("Дом 12345") == []


# --- identification and card numbers --------------------------------------


class TestIdentifiers:
    @pytest.mark.parametrize("prefix", ["ИИН", "БИН", "ЖСН", "IIN"])
    def test_iin(self, prefix):
        result = scrub(f"{prefix} {TEST_IIN} подтверждён")
        assert result.text == f"{prefix} <IIN> подтверждён"
        assert result.applied == ["iin"]

    def test_iin_is_not_also_a_phone(self):
        assert labels(f"ИИН {TEST_IIN}") == ["iin"]

    def test_eleven_and_thirteen_digits_are_not_iins(self):
        assert "iin" not in labels("87071234567")
        assert "iin" not in labels("8613800138000")

    @pytest.mark.parametrize(
        "raw",
        [
            TEST_CARD,
            "4242-4242-4242-4242",
            "4242424242424242",
            "4242.4242.4242.4242",
            "4242  4242  4242  4242",
            "4242\n4242\n4242\n4242",
            "5555 5555 5555 4444",
            TEST_AMEX,
            "6221 2612 3456 7890 129",  # nineteen digits, Luhn-valid
            "6221261234567890129",
            BROKEN_CARD,
            "4400430123456780",
            "6221 2612 3456 7890 123",  # nineteen digits, checksum broken
        ],
    )
    def test_card(self, raw):
        result = scrub(f"Карта {raw} для перевода")
        assert result.text == "Карта <CARD> для перевода"
        assert result.applied == ["card"]

    def test_card_before_a_short_code(self):
        assert masked(f"{TEST_CARD} 1414") == "<CARD> 1414"

    def test_card_is_not_reported_as_phone_or_short_codes(self):
        assert labels(TEST_CARD) == ["card"]
        assert labels(TEST_AMEX) == ["card"]

    def test_card_with_typographic_spaces(self):
        assert masked(TEST_CARD.replace(" ", " ")) == "<CARD>"


# --- contact identifiers ---------------------------------------------------


class TestContacts:
    @pytest.mark.parametrize(
        "raw", ["victim@example.com", "a@b.kz", "user.name+tag@mail.ru", "87071234567@mail.ru"]
    )
    def test_email(self, raw):
        result = scrub(f"почта {raw}")
        assert result.text == "почта <EMAIL>"
        assert result.applied == ["email"]

    def test_email_keeps_its_full_stop(self):
        assert masked("Пишите на victim@example.com.") == "Пишите на <EMAIL>."

    @pytest.mark.parametrize("raw", ["@scammer_bot", "@kaspi_support", "@Ivanov2024"])
    def test_handle(self, raw):
        result = scrub(f"Пишите {raw} в Telegram")
        assert result.text == "Пишите <HANDLE> в Telegram"
        assert result.applied == ["handle"]

    def test_email_is_not_also_a_handle(self):
        assert labels("victim@example.com") == ["email"]

    @pytest.mark.parametrize(
        "raw",
        [
            TEST_IBAN,
            "KZ86 125K ZT50 0410 0100",
            TEST_IBAN.lower(),
        ],
    )
    def test_iban(self, raw):
        result = scrub(f"Счёт {raw} для оплаты")
        assert result.text == "Счёт <IBAN> для оплаты"
        assert result.applied == ["iban"]

    def test_iban_digits_are_not_a_phone(self):
        assert labels(TEST_IBAN) == ["iban"]

    def test_currency_code_is_not_an_iban(self):
        assert labels("KZT 5 000 000 000 000 000") == []


# --- detection signals that must survive -----------------------------------


class TestSignalsSurvive:
    @pytest.mark.parametrize("code", ["1414", "9999", "505", "7111"])
    def test_short_codes(self, code):
        text = f"Код придёт с номера {code}. Никому не сообщайте"
        result = scrub(text)
        assert result.text == text
        assert result.applied == []

    @pytest.mark.parametrize(
        "amount",
        [
            "350 000",
            "350 000 тг",
            "1 500 000 тг",
            "1 500 000 теңге",
            "1 500 000",
            "1.500.000",
            "480 000 тенге",
            "8 700 000 000 тг",
            "700 000 000",
            "$500",
            "5000₸",
            "1200 юаней",
            "1500-2000 тг",
            "500 000 - 1 500 000",
            "12 500,50 тг",
        ],
    )
    def test_amounts(self, amount):
        text = f"Спишется {amount} сегодня"
        result = scrub(text)
        assert result.text == text
        assert result.applied == []

    @pytest.mark.parametrize(
        "date",
        [
            "12.03.2025",
            "12.03.25",
            "2025-03-12",
            "12/03/2025",
            "31.12.2025",
            "12.03.2025 14:30",
            "12.03.2025 в 14:30",
            "2025-03-12 09:05",
            "2025-2026",
            "14:30",
        ],
    )
    def test_dates_and_times(self, date):
        text = f"Оплата до {date}, иначе счёт закроют"
        result = scrub(text)
        assert result.text == text
        assert result.applied == []

    def test_date_range(self):
        text = "с 01.09.2025 по 30.09.2025"
        assert masked(text) == text

    def test_brands_and_amounts_together(self):
        result = scrub("Kaspi спишет 480 000 тенге")
        assert result.text == "Kaspi спишет 480 000 тенге"
        assert result.applied == []

    def test_tracking_code_and_url_survive(self):
        text = "Отследить: https://post.kz/track/AB123456789KZ"
        assert masked(text) == text

    def test_realistic_message(self):
        text = (
            "Здравствуйте! Это служба безопасности Kaspi. "
            "С вашего счёта пытаются списать 480 000 тг 12.03.2025. "
            f"Переведите на карту {TEST_CARD} или на номер +7 707 123 45 67, "
            f"ИИН {TEST_IIN}, код придёт с номера 1414."
        )
        result = scrub(text)
        assert result.text == (
            "Здравствуйте! Это служба безопасности Kaspi. "
            "С вашего счёта пытаются списать 480 000 тг 12.03.2025. "
            "Переведите на карту <CARD> или на номер <PHONE>, "
            "ИИН <IIN>, код придёт с номера 1414."
        )
        assert result.applied == ["card", "iin", "phone"]


# --- the contract of scrub and contains_unmasked_pii -----------------------


ALL_CLASSES = (
    f"Карта {TEST_CARD}, ИИН {TEST_IIN}, счёт {TEST_IBAN}, "
    "тел +7 707 123 45 67, почта a@b.kz, телеграм @scammer_bot"
)


class TestScrubContract:
    def test_applied_lists_every_placeholder_type(self):
        result = scrub(ALL_CLASSES)
        assert result.applied == sorted(PLACEHOLDER)
        for token in PLACEHOLDER.values():
            assert token in result.text

    def test_applied_is_sorted_and_unique(self):
        result = scrub("+7 707 123 45 67 и 8 707 765 43 21, a@b.kz и c@d.kz")
        assert result.applied == ["email", "phone"]

    def test_empty_text(self):
        assert scrub("") == scrub("")
        assert scrub("").text == ""
        assert scrub("").applied == []
        assert contains_unmasked_pii("") is False

    def test_idempotent(self):
        once = scrub(ALL_CLASSES)
        twice = scrub(once.text)
        assert twice.text == once.text
        assert twice.applied == []

    @pytest.mark.parametrize(
        "text",
        [
            ALL_CLASSES,
            "Спишется 480 000 тенге",
            "Код 1414, оплата до 12.03.2025",
            "87071234567 5000 тг",
            "победитель получит 1 500 000",
        ],
    )
    def test_contains_unmasked_pii_agrees_with_scrub(self, text):
        assert contains_unmasked_pii(text) is (scrub(text).text != text)
        assert contains_unmasked_pii(scrub(text).text) is False

    def test_nothing_recoverable_survives(self):
        blob = scrub(ALL_CLASSES).text.replace(" ", "")
        assert TEST_CARD.replace(" ", "") not in blob
        assert TEST_IIN not in blob
        assert TEST_IBAN not in blob
        assert "7071234567" not in blob
        assert "a@b.kz" not in blob
        assert "scammer_bot" not in blob


# --- the committed corpus ----------------------------------------------------


def corpus_rows() -> list[tuple[str, dict]]:
    rows = []
    for path in sorted(CORPUS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", [])
        rows.extend((f"{path.name}:{row.get('id', '?')}", row) for row in items)
    return rows


class TestCorpus:
    def test_corpus_is_present(self):
        assert corpus_rows(), "no batches under data/corpus"

    def test_no_row_carries_unmasked_pii(self):
        """The acceptance criterion for T405."""
        dirty = [
            (where, [span.label for span in find_pii(row["text"])])
            for where, row in corpus_rows()
            if contains_unmasked_pii(row["text"])
        ]
        assert dirty == []

    def test_scrubbed_rows_record_their_placeholders(self):
        for where, row in corpus_rows():
            if row.get("scrub_applied") is True:
                used = row.get("scrub_placeholders")
                assert isinstance(used, list), where
                assert set(used) <= set(PLACEHOLDER), where
                for label in used:
                    assert PLACEHOLDER[label] in row["text"], where


# --- the tool ----------------------------------------------------------------


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("scrub_corpus", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_row(row_id: str, text: str) -> dict:
    """A row in the shape tools/collect.py emits."""
    return {
        "id": row_id,
        "text": text,
        "source": "press",
        "provenance": "press",
        "source_url": "https://example.kz/article",
        "source_title": "Заголовок с номером +7 707 123 45 67 в нём",
        "publisher": "example.kz",
        "access_date": "2026-09-08",
        "lang": "ru",
        "is_code_switched": False,
        "label": "scam",
        "hard_negative": False,
        "channel": "sms",
        "verbatim": True,
        "text_kind": "message",
        "pii_flags": ["phone"],
        "needs_scrub": True,
        "scrub_applied": [],
        "text_hash": "0123456789abcdef",
        "collected_at": "2026-09-08T05:48:24+00:00",
        "notes": "Contact +7 707 123 45 67 quoted in the notes stays.",
    }


@pytest.fixture
def corpus_dir(tmp_path):
    batch = {
        "batch": "test-01",
        "created_at": "2026-09-08T05:48:24+00:00",
        "items": [
            make_row("t-01-001", f"Переведите на {TEST_CARD}, звоните +7 707 123 45 67"),
            make_row("t-01-002", "Спишется 480 000 тг, код придёт с номера 1414"),
        ],
        "updated_at": "2026-09-08T05:48:24+00:00",
    }
    path = tmp_path / "batch-test-01.json"
    path.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tmp_path


class TestTool:
    def test_check_reports_dirty_rows_and_writes_nothing(self, tool, corpus_dir, capsys):
        path = corpus_dir / "batch-test-01.json"
        before = path.read_bytes()
        assert tool.main(["--check", "--corpus", str(corpus_dir)]) == 1
        out = capsys.readouterr().out
        assert "batch-test-01.json t-01-001: card, phone" in out
        assert "t-01-002" not in out
        assert path.read_bytes() == before

    def test_rewrite_scrubs_text_and_leaves_other_fields(self, tool, corpus_dir, capsys):
        path = corpus_dir / "batch-test-01.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        assert tool.main(["--corpus", str(corpus_dir)]) == 0
        out = capsys.readouterr().out
        assert "batch-test-01.json t-01-001: card, phone" in out
        assert "t-01-002:" not in out

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["batch"] == "test-01"
        assert data["updated_at"] == original["updated_at"]
        dirty, clean = data["items"]

        assert dirty["text"] == "Переведите на <CARD>, звоните <PHONE>"
        assert dirty["scrub_applied"] is True
        assert dirty["scrub_placeholders"] == ["card", "phone"]
        assert clean["text"] == "Спишется 480 000 тг, код придёт с номера 1414"
        assert clean["scrub_applied"] is True
        assert clean["scrub_placeholders"] == []

        changed = {"text", "scrub_applied", "scrub_placeholders"}
        for before, after in zip(original["items"], data["items"], strict=True):
            for key in before:
                if key not in changed:
                    assert after[key] == before[key], key
            assert set(after) == set(before) | {"scrub_placeholders"}
            keys = list(after)
            assert keys.index("scrub_placeholders") == keys.index("scrub_applied") + 1

    def test_rewrite_keeps_the_formatting(self, tool, corpus_dir):
        path = corpus_dir / "batch-test-01.json"
        tool.main(["--corpus", str(corpus_dir)])
        raw = path.read_text(encoding="utf-8")
        assert raw.endswith("}\n")
        assert "\\u" not in raw, "ensure_ascii must be off"
        assert raw == json.dumps(json.loads(raw), ensure_ascii=False, indent=2) + "\n"
        assert path.read_bytes().count(b"\r") == 0

    def test_rewrite_is_idempotent_and_check_passes_after_it(self, tool, corpus_dir, capsys):
        path = corpus_dir / "batch-test-01.json"
        tool.main(["--corpus", str(corpus_dir)])
        first = path.read_bytes()
        capsys.readouterr()
        assert tool.main(["--corpus", str(corpus_dir)]) == 0
        assert "0 texts changed, 0 of 1 files rewritten" in capsys.readouterr().out
        assert path.read_bytes() == first
        assert tool.main(["--check", "--corpus", str(corpus_dir)]) == 0
        assert "no unmasked PII" in capsys.readouterr().out

    def test_bare_list_shape(self, tool, tmp_path):
        path = tmp_path / "staging.json"
        rows = [make_row("s-1", "ИИН " + TEST_IIN)]
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        assert tool.main(["--corpus", str(tmp_path)]) == 0
        (row,) = json.loads(path.read_text(encoding="utf-8"))
        assert row["text"] == "ИИН <IIN>"
        assert row["scrub_placeholders"] == ["iin"]

    def test_missing_directory(self, tool, tmp_path):
        assert tool.main(["--corpus", str(tmp_path / "nowhere")]) == 2
