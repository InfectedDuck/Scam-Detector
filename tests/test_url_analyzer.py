"""T107 — link and domain analysis, family G, and the fetch sandbox.

The sandbox tests matter most. This is the only code in the project that
fetches an attacker-supplied URL, and the failure mode is not a wrong verdict
but a request made from inside a network on an attacker's behalf. Every
refusal below is asserted to happen *before* any connection is attempted, so
none of these tests need the network.
"""

from __future__ import annotations

import pytest

import saqbol.core.indicators  # noqa: F401  — registers family G
from saqbol.core.extract import extract
from saqbol.core.indicators.registry import build_context, run_all, score
from saqbol.core.normalize import normalize
from saqbol.core.url_analyzer import (
    analyse_url,
    brands_named_in,
    edit_distance,
    load_reference,
    resolve_redirects,
    skeleton,
)


def analyse(text: str, metadata: dict | None = None):
    norm = normalize(text)
    ctx = build_context(norm, extract(norm.text), metadata=metadata or {})
    return ctx, run_all(ctx)


def fired(hits) -> set[str]:
    return {h.indicator_id for h in hits}


class TestSkeleton:
    def test_cyrillic_i_collapses_onto_latin(self):
        """The whole homograph defence in one assertion."""
        assert skeleton("kaspі") == skeleton("kaspi")

    def test_digit_letter_pairs_collapse(self):
        assert skeleton("kasp1") == skeleton("kaspl")
        assert skeleton("h0lyk") == skeleton("holyk")

    def test_unrelated_words_stay_apart(self):
        assert skeleton("kaspi") != skeleton("halyk")

    def test_is_case_insensitive(self):
        assert skeleton("KASPI") == skeleton("kaspi")


class TestEditDistance:
    @pytest.mark.parametrize(
        "a,b,expected",
        [
            ("kaspi", "kaspi", 0),
            ("kaspi", "kasp", 1),
            ("kaspi", "kaspii", 1),
            ("kaspi", "kapsi", 1),
            ("kaspi", "halyk", 4),
        ],
    )
    def test_distances(self, a, b, expected):
        assert edit_distance(a, b) == min(expected, 4)

    def test_transposition_counts_once(self):
        """A swapped pair is one typo, not two, which is how a lookalike domain
        is usually built."""
        assert edit_distance("kaspi", "kapsi") == 1

    def test_cap_short_circuits(self):
        assert edit_distance("a", "abcdefghij", cap=2) == 3


class TestOfflineFacts:
    def test_official_domain_is_clean(self):
        f = analyse_url("https://kaspi.kz/bonus")
        assert f.registrable == "kaspi.kz"
        assert f.lookalike_of is None

    def test_confusable_domain_detected(self):
        f = analyse_url("kaspі.kz")
        assert f.lookalike_of == "Kaspi"
        assert f.lookalike_method == "confusable"

    def test_typo_domain_detected(self):
        f = analyse_url("kasp1.kz")
        assert f.lookalike_of == "Kaspi"
        assert f.lookalike_method == "edit"

    def test_bare_ip(self):
        f = analyse_url("http://192.168.1.5/pay")
        assert f.is_ip is True

    def test_shortener(self):
        assert analyse_url("https://bit.ly/3xYz").is_shortener is True

    def test_punycode(self):
        assert analyse_url("http://xn--80ak6aa92e.com").is_punycode is True

    def test_short_labels_are_not_compared(self):
        """A three-letter host would sit within two edits of half the brand
        list, so it is excluded rather than guessed at."""
        assert analyse_url("abc.kz").lookalike_of is None

    def test_no_network_on_the_default_path(self):
        """`resolve` defaults off, so the offline analysis never fetches."""
        f = analyse_url("https://bit.ly/3xYz")
        assert f.redirect_chain == []
        assert f.final_registrable is None

    def test_brands_named_in_text(self):
        names = {b.name for b in brands_named_in("Здравствуйте, это Каспи банк")}
        assert "Kaspi" in names


class TestFetchSandbox:
    """No network needed: every case is refused before a socket is opened."""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/x",
            "gopher://example.com",
            "data:text/html,hi",
            "javascript:alert(1)",
        ],
    )
    def test_scheme_allowlist(self, url):
        chain, final, error = resolve_redirects(url)
        assert error in {"scheme_not_allowed", "no_host"}
        assert final is None
        assert chain == []

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/admin",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
            "http://[::1]/",
            "http://0.0.0.0/",
        ],
    )
    def test_private_and_reserved_addresses_refused(self, url):
        chain, final, error = resolve_redirects(url)
        assert error == "address_not_public", url
        assert final is None
        assert chain == []

    def test_localhost_by_name_refused(self):
        chain, _final, error = resolve_redirects("http://localhost:8000/")
        assert error == "address_not_public"
        assert chain == []


class TestFamilyG:
    def test_homograph_fires_g1(self):
        _, hits = analyse("Оплата на kaspі.kz прямо сейчас")
        assert "G1.lookalike_domain" in fired(hits)

    def test_brand_mismatch_fires_g5(self):
        """The shape a lookalike check misses: nowhere near kaspi.kz by edit
        distance, but wearing the brand's name."""
        _, hits = analyse("Kaspi: подтвердите вход kaspi-secure.ru")
        assert "G5.brand_mismatch" in fired(hits)

    def test_delivery_scam_fires_g5(self):
        _, hits = analyse("Казпочта: оплатите сбор на kazpost-dostavka.info/pay")
        assert "G5.brand_mismatch" in fired(hits)

    def test_ip_url_fires_g8(self):
        _, hits = analyse("Оплатите здесь http://45.9.148.22/pay")
        assert "G8.ip_url" in fired(hits)

    def test_shortener_fires_g3(self):
        _, hits = analyse("Перейдите: https://bit.ly/3xYzAbc")
        assert "G3.shortener" in fired(hits)

    def test_punycode_fires_g2(self):
        _, hits = analyse("Ссылка http://xn--80ak6aa92e.com/pay")
        assert "G2.punycode_idn" in fired(hits)

    def test_fresh_domain_needs_enrichment(self):
        """Domain age is not in the text, so the rule stays silent without it
        rather than inventing a signal."""
        _, without = analyse("Магазин: super-shop-kz.top")
        assert "G6.fresh_domain" not in fired(without)

        _, with_ages = analyse(
            "Магазин: super-shop-kz.top", {"domain_ages": {"super-shop-kz.top": 4}}
        )
        assert "G6.fresh_domain" in fired(with_ages)

    def test_old_domain_does_not_fire(self):
        _, hits = analyse("Магазин: super-shop-kz.top", {"domain_ages": {"super-shop-kz.top": 900}})
        assert "G6.fresh_domain" not in fired(hits)

    def test_redirect_chain_needs_resolution(self):
        _, hits = analyse("https://bit.ly/3xYzAbc")
        assert "G4.long_redirect_chain" not in fired(hits)


class TestLegitimateLinks:
    """The precision half. Real institutional links must produce nothing."""

    @pytest.mark.parametrize(
        "text",
        [
            "Ваш заказ отправлен. Отследить: https://post.kz/track/AB123456789KZ",
            "Kaspi Bonus: подробности на kaspi.kz/bonus",
            "Halyk Bank: вход в интернет-банк halykbank.kz",
            "Портал egov.kz: услуга готова",
            "Объявление на olx.kz ещё активно?",
        ],
    )
    def test_official_links_are_silent(self, text):
        _, hits = analyse(text)
        assert not [h for h in hits if h.indicator_id.startswith("G")], text

    def test_unrelated_legitimate_domain_is_silent(self):
        """A message naming a bank that also links elsewhere is ordinary. G5 is
        keyed on the host wearing the brand name, not on the brand being
        mentioned, precisely so this does not fire."""
        _, hits = analyse("Kaspi: пройдите опрос на forms.gle/abc123")
        assert "G5.brand_mismatch" not in fired(hits)


class TestReference:
    def test_every_brand_has_a_domain_and_terms(self):
        brands, shorteners = load_reference()
        assert brands and shorteners
        for brand in brands:
            assert brand.domains, brand.name
            assert brand.terms, brand.name
            assert brand.sld, brand.name

    def test_official_domains_never_look_like_each_other(self):
        """If two brands' labels sat within the lookalike threshold, every real
        link to one would be flagged as imitating the other."""
        brands, _ = load_reference()
        for i, a in enumerate(brands):
            for b in brands[i + 1 :]:
                assert edit_distance(skeleton(a.sld), skeleton(b.sld)) > 2, (a.name, b.name)


class TestEndToEnd:
    def test_full_delivery_scam_is_recognised(self):
        """The delivery playbook fires the right rules but lands just under the
        rules-only scam threshold, at 49.

        That gap is expected, not a defect: docs/03_INDICATORS.md specifies a
        combination bonus of +10 when any family-G rule co-occurs with
        C6.courier_post, and combination rules live in fuse.py, which is T113.
        This test pins the current rules-only behaviour so the bonus can be seen
        to do its job when it lands."""
        _, hits = analyse(
            "Казпочта: ваша посылка задержана на таможне. Срочно оплатите "
            "таможенный сбор 1 200 тг по ссылке kazpost-dostavka.info/pay"
        )
        assert {"C6.courier_post", "G5.brand_mismatch", "B1.urgency"} <= fired(hits)
        assert 45 <= score(hits) < 50

    def test_span_invariant_still_holds_with_family_g(self):
        ctx, hits = analyse("Казпочта: оплатите на kazpost-dostavka.info")
        for hit in hits:
            for span in hit.spans:
                assert span.matches(ctx.text)
