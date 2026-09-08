"""T102 — normalizer, script analysis and language identification."""

from __future__ import annotations

import pytest

from saqbol.core.normalize import (
    collapse_whitespace,
    detect_language,
    mixed_script_tokens,
    normalize,
    script_ratios,
    strip_invisible,
)
from saqbol.core.types import Lang

RU_SCAM = "Здравствуйте, это служба безопасности банка. С вашего счёта пытаются списать деньги."
KK_SCAM = "Сәлеметсіз бе, бұл банктің қауіпсіздік қызметі. Шотыңыздан ақша алуға тырысып жатыр."
KK_RU_MIXED = "Сәлеметсіз бе! Мне позвонили из банка и просят код из СМС. Что делать?"
ZH_SCAM = "您好，我是公安局的警官。您涉嫌洗钱，需要缴纳保证金。"
EN_TEXT = "Hello, this is the bank security department calling about your account."
RU_LEGIT_WITH_URL = "Ваш заказ отправлен. Отследить: https://post.kz/track/AB123456789KZ"


class TestLanguage:
    def test_russian(self):
        lang, conf, switched = detect_language(RU_SCAM)
        assert lang is Lang.RU
        assert conf > 0.5
        assert not switched

    def test_kazakh(self):
        lang, conf, _ = detect_language(KK_SCAM)
        assert lang is Lang.KK
        assert conf > 0.6

    def test_chinese(self):
        lang, _, _ = detect_language(ZH_SCAM)
        assert lang is Lang.ZH

    def test_english(self):
        lang, _, _ = detect_language(EN_TEXT)
        assert lang is Lang.EN

    def test_code_switched_is_russian_not_kazakh(self):
        """A Kazakh greeting on a Russian message is code-switched Russian.

        Classifying it as Kazakh would inflate the Kazakh split with what is
        really Russian text, which would confound the headline H1 comparison.
        """
        lang, _, switched = detect_language(KK_RU_MIXED)
        assert lang is Lang.RU
        assert switched is True

    def test_url_does_not_trigger_code_switching(self):
        """Latin URLs appear in almost every Russian message and must not count."""
        lang, _, switched = detect_language(RU_LEGIT_WITH_URL)
        assert lang is Lang.RU
        assert switched is False

    def test_empty(self):
        assert detect_language("")[0] is Lang.UNKNOWN
        assert detect_language("12345 !!! ???")[0] is Lang.UNKNOWN


class TestInvisibleCharacters:
    @pytest.mark.parametrize(
        "raw",
        [
            "к​од из СМС",  # zero-width space
            "к‍од из СМС",  # zero-width joiner
            "к­or из СМС".replace("or", "од"),  # soft hyphen
            "﻿код из СМС",  # BOM
        ],
    )
    def test_keyword_evasion_is_defeated(self, raw):
        """Invisible characters inserted mid-word are the cheapest way to break
        naive keyword matching. Stripping them is why indicators can stay simple."""
        assert "код" in strip_invisible(raw)

    def test_bidi_override_removed(self):
        assert "‮" not in strip_invisible("файл‮gpj.apk")


class TestNfkcAndWhitespace:
    def test_fullwidth_folded(self):
        """Full-width Latin is common in Chinese scam text."""
        assert normalize("ＡＮＹＤＥＳＫ").text == "ANYDESK"

    def test_horizontal_whitespace_collapsed(self):
        assert collapse_whitespace("код    из\t\tСМС") == "код из СМС"

    def test_newlines_preserved_but_capped(self):
        out = collapse_whitespace("строка1\n\n\n\n\nстрока2")
        assert out == "строка1\n\nстрока2"

    def test_lines_are_stripped(self):
        assert collapse_whitespace("  привет  \n   мир  ") == "привет\nмир"


class TestScriptAnalysis:
    def test_ratios_sum_to_one(self):
        ratios = script_ratios(RU_SCAM)
        assert pytest.approx(sum(ratios.values()), abs=1e-6) == 1.0
        assert ratios["cyrillic"] == 1.0

    def test_no_letters_gives_empty(self):
        assert script_ratios("123 !!! ???") == {}

    def test_homograph_token_detected(self):
        """Cyrillic 'і' inside a Latin brand name. The classic .kz lookalike."""
        tokens = mixed_script_tokens("Оплатите на kaspі.kz прямо сейчас")
        assert tokens == ["kaspі"]

    def test_clean_latin_token_is_not_flagged(self):
        assert mixed_script_tokens("Перейдите на kaspi.kz") == []


class TestNormalizeContract:
    def test_offsets_index_the_normalized_text(self):
        """Every downstream span indexes `text`, never `original`. NFKC and
        whitespace collapse change lengths, so the two are not interchangeable."""
        raw = "  Здравствуйте,   это​ служба   безопасности  "
        n = normalize(raw)
        assert n.text == "Здравствуйте, это служба безопасности"
        assert n.original == raw
        idx = n.text.index("служба")
        assert n.text[idx : idx + 6] == "служба"

    def test_normalize_is_idempotent(self):
        once = normalize(RU_SCAM).text
        assert normalize(once).text == once

    def test_lang_hint_only_fills_unknown(self):
        assert normalize("12345", lang_hint=Lang.KK).lang is Lang.KK
        # A hint must never override a confident detection.
        assert normalize(KK_SCAM, lang_hint=Lang.ZH).lang is Lang.KK

    def test_empty_input(self):
        n = normalize("   \n\n  ")
        assert n.text == ""
        assert n.lang is Lang.UNKNOWN
