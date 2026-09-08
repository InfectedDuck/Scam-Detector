"""T103 — entity extraction, and the PII masking guarantee."""

from __future__ import annotations

import pytest

from saqbol.core.extract import (
    extract,
    find_amounts,
    find_app_names,
    find_crypto,
    find_phones,
    find_short_codes,
    find_urls,
)
from saqbol.core.privacy import contains_unmasked_pii, luhn, scrub
from saqbol.core.types import Entities

# Luhn-valid test number from the standard test-card set. Not a real account.
TEST_CARD = "4242 4242 4242 4242"


class TestUrls:
    def test_scheme_url(self):
        assert find_urls("Оплатите здесь https://kaspi-kz.ru/pay") == ["https://kaspi-kz.ru/pay"]

    def test_bare_domain(self):
        assert find_urls("Перейдите на kaspi.kz сейчас") == ["kaspi.kz"]

    def test_homograph_domain_is_captured(self):
        """Cyrillic 'і'. If the extractor drops it, indicator G1 never runs."""
        assert find_urls("Оплата на kaspі.kz") == ["kaspі.kz"]

    def test_trailing_punctuation_trimmed(self):
        assert find_urls("Ссылка: https://post.kz/track.") == ["https://post.kz/track"]

    def test_abbreviation_is_not_a_domain(self):
        """Russian 'и т.д.' must not become a URL. This is why the public
        suffix list is consulted rather than a bare dot heuristic."""
        assert find_urls("Купите хлеб, молоко и т.д.") == []

    def test_filename_is_not_a_domain(self):
        assert find_urls("Установите document.apk") == []

    def test_no_duplicates(self):
        assert find_urls("kaspi.kz и снова kaspi.kz") == ["kaspi.kz"]


class TestPhonesAndCodes:
    @pytest.mark.parametrize(
        "raw",
        ["+7 707 123 45 67", "8 (727) 330-00-00", "+86 138 0013 8000"],
    )
    def test_formats(self, raw):
        assert find_phones(raw)

    def test_too_short_rejected(self):
        assert find_phones("Дом 12345") == []

    def test_short_codes(self):
        assert "1414" in find_short_codes("Код придёт с номера 1414")

    def test_amount_is_not_a_short_code(self):
        """Without this the tenge amount in every scam message becomes a code."""
        assert find_short_codes("Спишется 480 тг") == []

    def test_amount_extracted_instead(self):
        assert find_amounts("Спишется 480 тг") == ["480 тг"]

    @pytest.mark.parametrize("raw", ["480 000 тенге", "$500", "1200 юаней", "5000₸", "300 руб"])
    def test_currency_variants(self, raw):
        assert find_amounts(raw)


class TestCryptoAndApps:
    def test_eth_address(self):
        addr = "0x" + "a1b2c3d4e5" * 4
        assert find_crypto(f"Переведите на {addr}") == [addr]

    def test_latin_app_name(self):
        assert find_app_names("Установите AnyDesk для защиты") == ["anydesk"]

    def test_cyrillic_dictated_spelling(self):
        """A caller reads the app name aloud, so the victim types it in Cyrillic."""
        assert find_app_names("скачайте энидеск") == ["anydesk"]

    def test_no_false_positive(self):
        assert find_app_names("Обычное сообщение без приложений") == []


class TestApk:
    def test_attachment_reference(self):
        assert extract("Установите Kaspi_update.apk").has_apk is True

    def test_clean_message(self):
        assert extract("Ваш заказ отправлен").has_apk is False


class TestPiiMasking:
    def test_luhn(self):
        assert luhn(TEST_CARD)
        assert not luhn("4242 4242 4242 4243")

    def test_card_is_masked_in_entities(self):
        ents = extract(f"Введите номер карты {TEST_CARD}")
        assert ents.card_numbers == ["<CARD:16>"]

    def test_iin_is_masked_in_entities(self):
        ents = extract("Ваш ИИН 123456789012 подтверждён")
        assert ents.iins == ["<IIN>"]

    def test_no_unmasked_pii_reaches_the_entities_object(self):
        """The guarantee behind T103. Serialise the whole object and assert
        nothing recoverable survives anywhere inside it."""
        text = (
            f"Карта {TEST_CARD}, ИИН 123456789012, "
            "почта victim@example.com, звоните +7 707 123 45 67"
        )
        blob = extract(text).model_dump_json()
        assert TEST_CARD.replace(" ", "") not in blob.replace(" ", "")
        assert "123456789012" not in blob
        assert "victim@example.com" not in blob

    def test_scrub_replaces_every_class(self):
        text = f"Карта {TEST_CARD}, ИИН 123456789012, почта a@b.kz, тел +7 707 123 45 67"
        result = scrub(text)
        assert not contains_unmasked_pii(result.text)
        assert set(result.applied) >= {"card", "iin", "email", "phone"}

    def test_scrub_keeps_amounts_and_brands(self):
        """Amounts and institution names are signal, not PII."""
        result = scrub("Kaspi спишет 480 000 тенге")
        assert "Kaspi" in result.text
        assert "480 000" in result.text
        assert result.applied == []


class TestSpanArbitration:
    """Regressions. Digit runs in this domain are genuinely ambiguous, and
    matching each pattern independently produced contradictory entities."""

    def test_iin_is_not_also_reported_as_a_phone(self):
        """Twelve digits satisfy both the identification-number and the loose
        phone pattern. The stronger pattern must win, or the number leaks into
        `phones` unmasked."""
        ents = extract("Ваш ИИН 123456789012 подтверждён")
        assert ents.iins == ["<IIN>"]
        assert ents.phones == []

    def test_card_does_not_yield_four_short_codes(self):
        ents = extract(f"Карта {TEST_CARD}")
        assert ents.card_numbers == ["<CARD:16>"]
        assert ents.short_codes == []

    def test_phone_fragments_are_not_short_codes(self):
        ents = extract("Звоните +7 707 123 45 67")
        assert ents.phones == ["+7 707 123 45 67"]
        assert ents.short_codes == []

    def test_large_amount_is_not_a_phone_number(self):
        """Six or more digits with separators look exactly like a phone.
        Amounts are reserved before phone matching for this reason."""
        ents = extract("Спишется 480 000 тенге")
        assert ents.amounts == ["480 000 тенге"]
        assert ents.phones == []

    def test_scrub_agrees_with_extract(self):
        """Both consume the same patterns, so they must never disagree about
        what counts as an amount."""
        result = scrub("Спишется 480 000 тенге")
        assert "480 000" in result.text
        assert "phone" not in result.applied


class TestEndToEnd:
    def test_realistic_scam_message(self):
        text = (
            "Здравствуйте! Это служба безопасности Kaspi. "
            "С вашего счёта пытаются списать 480 000 тг. "
            "Установите AnyDesk и подтвердите по ссылке kaspi-secure.ru, "
            "код придёт с номера 1414."
        )
        ents = extract(text)
        assert ents.urls == ["kaspi-secure.ru"]
        assert ents.app_names == ["anydesk"]
        assert "480 000 тг" in ents.amounts
        assert "1414" in ents.short_codes

    def test_legitimate_message_stays_quiet(self):
        ents = extract("Ваш заказ отправлен. Отследить: https://post.kz/track/AB123456789KZ")
        assert ents.urls == ["https://post.kz/track/AB123456789KZ"]
        assert ents.app_names == []
        assert ents.card_numbers == []
        assert ents.has_apk is False

    def test_empty_input(self):
        assert extract("") == Entities()
