"""Kazakh side of the deterministic layer — the 17 former `TODO-kk` markers.

The leaderboard publishes a `rules_only` row per language. While those markers
were unfilled the Kazakh column measured a Russian rule set, and a low number
would have said "the baseline was never written" rather than anything about the
language. This file is what stops that regressing.

Four obligations, one per section below:

1. Every filled marker fires on Kazakh, and fires *through its Kazakh phrases*
   rather than by accident through a Russian one that happens to overlap.
2. Every marker also fires on the CODE-SWITCHED variant — a Kazakh sentence
   carrying the Russian banking noun untranslated. That mixture is the normal
   case in Kazakhstan, not an edge case, and it is what the project exists to
   handle.
3. Genuine Kazakh messages stay quiet. In particular a real Kaspi notification
   must produce zero family-A hits, which is harder in Kazakh than in Russian:
   `registry.NEGATION_CUES` is word-based and Kazakh negates with a verb
   suffix, so "кодты ешкімге айтпаңыз" is invisible to that guard.
4. The Kazakh additions changed nothing on the Russian side.

The vocabulary itself lives in `core/data/kk_lexicon.yaml`, not here, so a
native speaker reviews one file. These tests check the wiring and the
invariants; the file checks the words.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import saqbol.core.indicators  # noqa: F401  — registers every family
from saqbol.core.indicators.kk_lexicon import LEXICON, kk, load
from saqbol.core.indicators.registry import REGISTRY, find_phrase_spans, fold_for_matching, score
from tests.test_indicators import HARD_NEGATIVES, SCAM_THRESHOLD, analyse, fired

INDICATOR_DIR = Path(__file__).resolve().parents[1] / "src" / "saqbol" / "core" / "indicators"

#: The seven modules that carried the markers.
OWNED_MODULES = [
    "authority.py",
    "channel.py",
    "credentials.py",
    "money.py",
    "offers.py",
    "software.py",
    "urgency.py",
]


# --------------------------------------------------------------------------
# 1 and 2. One Kazakh fixture and one code-switched fixture per filled marker.
#
# The second element of each pair keeps a Russian noun inside Kazakh grammar:
# счет, карта, кредит, посылка, трубка, операция, пароль. That is how these
# messages are actually written.
# --------------------------------------------------------------------------

KK_FIXTURES: dict[str, tuple[str, str]] = {
    # A — credential extraction
    "A1.otp_request": (
        "Сәлеметсіз бе, сізге келген кодты айтыңыз",
        "Банктің қауіпсіздік қызметі, счетыңыздан ақша алынып жатыр, смс кодты маған айтыңыз",
    ),
    "A2.card_secrets": (
        "Картаңыздың нөмірін және артқы жағындағы үш санды айтыңыз",
        "Kaspi Gold картаның толық нөмірін және пин кодыңызды енгізіңіз",
    ),
    "A3.password_request": (
        "Банк қосымшасының құпия сөзіңізді айтыңыз",
        "Логин мен парольді айтыңыз, әйтпесе кабинетке кіре алмайсыз",
    ),
    # B — urgency and fear
    "B1.urgency": (
        "Шұғыл түрде растаңыз, әйтпесе кеш болады",
        "Операцияны дәл қазір растаңыз, 5 минут ішінде",
    ),
    "B2.account_block_threat": (
        "Шотыңыз бүгін бұғатталады",
        "Счетыңыз бұғатталады, картаңыз бұғатталды",
    ),
    "B3.criminal_threat": (
        "Сізге қатысты қылмыстық іс қозғалды, қамауға аламыз",
        "Мен тергеушімін, сізге қатысты қылмыстық іс бар",
    ),
    "B4.money_at_risk": (
        "Ақшаңыз алынып жатыр, рұқсатсыз кіру тіркелді",
        "Күдікті операция байқалды, счетыңыздан ақша алынып жатыр",
    ),
    # C — authority impersonation
    "C1.bank_security": (
        "Бұл банктің қауіпсіздік қызметі",
        "Алаяқтықпен күресу бөлімінің қызметкерімін, банк қызметкерімін",
    ),
    "C3.egov_1414": (
        "Электрондық үкімет порталы растауды талап етеді",
        "Мемлекеттік қызметтер порталы egov арқылы растаңыз",
    ),
    "C4.national_bank": (
        "Қазақстан Ұлттық Банкі сізді хабардар етеді",
        "Ұлттық банктің өкілімін, счетыңыз тексерілуде",
    ),
    "C6.courier_post": (
        "Қазпоштадан хабарлама: сәлемдемеңіз кеденде ұсталды",
        "Посылкаңыз ұсталды, жеткізуді төлеңіз",
    ),
    # D — channel migration
    "D3.dont_hang_up": (
        "Телефонды тастамаңыз, желіде қалыңыз",
        "Трубканы қоймаңыз, қазір оператормен байланыстырамын",
    ),
    # E — money movement
    "E1.safe_account": (
        "Ақшаңызды қауіпсіз шотқа аударыңыз",
        "Барлық ақшаны қауіпсіз счетке аударыңыз",
    ),
    "E3.take_a_loan": (
        "Қосымшада несиені рәсімдеңіз, бұл тексеру үшін",
        "Сіздің атыңызға кредит рәсімделіп жатыр, кредитке өтінімді растаңыз",
    ),
    # F — software installation
    "F3.install_instruction": (
        "Қосымшаны орнатыңыз, мен көмектесемін",
        "Сілтеме арқылы жүктеңіз, содан кейін файлды ашыңыз",
    ),
    # H — offers
    "H1.guaranteed_returns": (
        "Кепілдендірілген табыс, тәуекел жоқ",
        "Инвестициялық платформада тәуекелсіз пассивті табыс",
    ),
    "H3.unsolicited_prize": (
        "Құттықтаймыз, сіз бас жүлдені ұттыңыз",
        "Сізге өтемақы тиесілі, компенсацияны алу үшін жазыңыз",
    ),
}

VARIANTS = ("kazakh", "code_switched")


def _cases() -> list[tuple[str, str, str]]:
    return [
        (indicator_id, label, text)
        for indicator_id, pair in sorted(KK_FIXTURES.items())
        for label, text in zip(VARIANTS, pair, strict=True)
    ]


@pytest.mark.parametrize(
    ("indicator_id", "variant", "text"),
    _cases(),
    ids=lambda v: v if isinstance(v, str) and len(v) < 30 else "",
)
def test_kazakh_fixture_fires_the_indicator(indicator_id, variant, text):
    _, hits = analyse(text)
    assert indicator_id in fired(hits), f"{variant}: {text!r} fired {sorted(fired(hits))}"


@pytest.mark.parametrize(
    ("indicator_id", "variant", "text"),
    _cases(),
    ids=lambda v: v if isinstance(v, str) and len(v) < 30 else "",
)
def test_the_kazakh_phrases_are_what_matched(indicator_id, variant, text):
    """Fires *because of* the Kazakh lexicon, not by luck.

    Without this a fixture could pass on a Russian pattern that happens to
    overlap — "кредит", "операция", "egov" all appear in both lists — and the
    Kazakh column would look filled while the Kazakh phrases were dead.
    """
    ctx, _ = analyse(text)
    spans = find_phrase_spans(ctx, kk(indicator_id), indicator_id)
    assert spans, f"{variant}: no phrase from kk_lexicon.yaml[{indicator_id}] matched {text!r}"


def test_span_invariant_holds_for_every_kazakh_fixture():
    """normalized[start:end] == span.text, on Kazakh too.

    Worth asserting separately from the Russian suite: Kazakh-specific letters
    are the ones most likely to break a length-preserving fold, and a span that
    does not quote the real text is a highlight pointing at the wrong words.
    """
    for _, variant, text in _cases():
        ctx, hits = analyse(text)
        for hit in hits:
            for span in hit.spans:
                assert span.matches(ctx.text), f"{span.indicator_id} in {variant} {text!r}"


# --------------------------------------------------------------------------
# Agglutination. The reason phrases carry a trailing star at all.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Кодты айтыңыз",
        "Коды айтыңыз",
        "Кодыңызды айтыңыз",
        "Кодыңызды маған айтыңыз",
        "Смс кодты айтыңызшы",
    ],
)
def test_one_stem_survives_the_suffix_chain(text):
    """код / кодты / коды / кодыңызды are one word, not four misses.

    "кодыңызды" is six letters past the stem and the wildcard allows four, so
    the lexicon carries "кодыңыз*" alongside "код*". This test is what fails if
    someone tidies that pair away.
    """
    _, hits = analyse(text)
    assert "A1.otp_request" in fired(hits)


# --------------------------------------------------------------------------
# 3. Genuine Kazakh messages. The half of the job that is easy to get wrong.
# --------------------------------------------------------------------------

KK_HARD_NEGATIVES = {
    # A real one-time-password SMS. Kazakh negates with a verb suffix
    # (айт-па-ңыз), so registry.NEGATION_CUES cannot see the warning; the
    # family-A phrases avoid it by spelling out the positive imperative.
    "kaspi_otp": "Kaspi.kz: 4821 - кіру коды. Кодты ешкімге айтпаңыз.",
    "kaspi_otp_long": (
        "Kaspi Bank: 8391 - растау коды. Бұл кодты ешкімге, соның ішінде банк "
        "қызметкерлеріне де айтпаңыз."
    ),
    # The bank's own anti-fraud advice. Contains the password noun and the verb.
    "kaspi_advice": (
        "Kaspi Bank: құпия сөзіңізді ешкімге айтпаңыз. Банк қызметкерлері оны ешқашан сұрамайды."
    ),
    # A bank telling customers what it will never ask for. Names the code, the
    # password and the card number in one sentence.
    "kaspi_advice_full": (
        "Банк қызметкерлері ешқашан кодты, паролыңызды немесе картаңыздың нөмірін сұрамайды."
    ),
    "kaspi_receipt": "Kaspi Gold: 12 500 ₸ аударым қабылданды. Балансыңыз: 45 300 ₸.",
    "kaspi_bonus": "Kaspi Bonus: сізге шілде айындағы сатып алулар үшін 500 бонус берілді.",
    "kazpost_tracking": "Қазпошта: сәлемдемеңіз жеткізуге дайын. AB123456789KZ",
    "egov_notification": "eGov: мемлекеттік қызмет көрсетілді. Нәтижені порталдан алыңыз.",
    # Regression: a bare "жүктеп алыңыз" in F3 fired on this, and C3 fires on
    # genuine eGov traffic by design, so the two together reached the
    # threshold on a real government message.
    "egov_certificate": "Электрондық үкімет: анықтамаңыз дайын, egov.kz сайтынан жүктеп алыңыз.",
    "olx_buyer": "Сәлеметсіз бе, тауар әлі сатылып жатыр ма? Ертең алып кетсем бола ма?",
    "halyk_login": (
        "Halyk Bank: жаңа құрылғыдан қосымшаға кіру тіркелді. Егер бұл сіз болмасаңыз, "
        "банкке қоңырау шалыңыз."
    ),
    # Legitimate app prompts. Entering a code is what a real flow asks for;
    # only handing it to a person is the scam, which is why no phrase pairs the
    # code noun with "енгізіңіз".
    "app_code_prompt": "Қосымшаға кіру үшін кодты енгізіңіз.",
    "app_sms_prompt": "Растау үшін смс кодты енгізіңіз.",
}


@pytest.mark.parametrize("name", sorted(KK_HARD_NEGATIVES))
def test_kazakh_hard_negatives_stay_below_threshold(name):
    _, hits = analyse(KK_HARD_NEGATIVES[name])
    assert score(hits) < SCAM_THRESHOLD, f"{name} fired {sorted(fired(hits))}"


@pytest.mark.parametrize("name", sorted(KK_HARD_NEGATIVES))
def test_genuine_kazakh_messages_produce_no_credential_hit(name):
    """The requirement that matters: zero family-A hits on a real notification.

    A Kazakh one-time-password SMS contains the code, the noun and the verb of
    the scam that asks for it, separated only by a suffix. If this fails, the
    highest-severity rule in the catalogue is firing on the most common
    legitimate message in the Kazakh corpus.
    """
    _, hits = analyse(KK_HARD_NEGATIVES[name])
    assert not [h for h in hits if h.indicator_id.startswith("A")]


@pytest.mark.parametrize(
    "text",
    [
        "Кодты ешкімге айтпаңыз",
        "Кодты ешкімге хабарламаңыз",
        "Құпия сөзіңізді ешкімге айтпаңыз",
        "Паролыңызды ешкімге бермеңіз",
        "Картаңыздың нөмірін ешкімге айтпаңыз",
    ],
)
def test_kazakh_prohibitive_forms_do_not_fire_family_a(text):
    """-ма/-ме/-ба/-бе/-па/-пе is a suffix, so the negation guard never sees it.

    The lexicon compensates by spelling out the positive imperative. Anyone who
    "simplifies" "айтыңыз*" back to "айт*" fails here rather than in production.
    """
    _, hits = analyse(text)
    assert not [h for h in hits if h.indicator_id.startswith("A")], text


def test_a_full_kazakh_scam_still_clears_the_threshold():
    """The negatives above must not have been bought with a dead rule set."""
    text = (
        "Сәлеметсіз бе! Бұл банктің қауіпсіздік қызметі. Счетыңыздан ақша алынып жатыр, "
        "шұғыл түрде кодты маған айтыңыз және ақшаңызды қауіпсіз шотқа аударыңыз. "
        "Телефонды тастамаңыз."
    )
    _, hits = analyse(text)
    assert score(hits) >= SCAM_THRESHOLD, f"only fired {sorted(fired(hits))}"
    assert {
        "A1.otp_request",
        "B1.urgency",
        "B4.money_at_risk",
        "C1.bank_security",
        "D3.dont_hang_up",
        "E1.safe_account",
    } <= fired(hits)


# --------------------------------------------------------------------------
# 4. Nothing on the Russian side moved.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(HARD_NEGATIVES))
def test_no_kazakh_phrase_matches_a_russian_hard_negative(name):
    """The lexicon may add Kazakh recall; it may not spend Russian precision.

    Checked directly against the phrase lists rather than through the score, so
    it fails on the first Kazakh phrase that reaches Russian text even if the
    total happens to stay under the threshold.
    """
    ctx, _ = analyse(HARD_NEGATIVES[name])
    for indicator_id, phrases in load().items():
        spans = find_phrase_spans(ctx, phrases, indicator_id)
        assert not spans, f"{indicator_id} matched {[s.text for s in spans]} in {name}"


# --------------------------------------------------------------------------
# Lexicon hygiene. These guard the file a non-programmer will be editing.
# --------------------------------------------------------------------------


def test_no_todo_kk_marker_survives_in_the_owned_modules():
    """The 17 markers are the deliverable. This is the count, made executable."""
    leftover = []
    for name in OWNED_MODULES:
        lines = (INDICATOR_DIR / name).read_text(encoding="utf-8").splitlines()
        leftover += [f"{name}:{n}" for n, line in enumerate(lines, 1) if "TODO-kk" in line]
    assert not leftover, f"unfilled Kazakh markers: {leftover}"


def test_every_lexicon_key_is_a_registered_indicator():
    """A typo in the YAML would otherwise be a phrase list nothing ever runs."""
    unknown = sorted(set(load()) - set(REGISTRY))
    assert not unknown, f"{LEXICON.name} names indicators that do not exist: {unknown}"


def test_every_lexicon_entry_has_a_fixture():
    missing = sorted(set(load()) - set(KK_FIXTURES))
    assert not missing, f"Kazakh phrases with nothing testing them: {missing}"


def test_the_lexicon_covers_every_marker_that_existed():
    """Seventeen markers, seventeen phrase lists."""
    assert len(load()) == 17


@pytest.mark.parametrize("indicator_id", sorted(load()))
def test_phrases_are_folded_for_matching(indicator_id):
    """Matching runs against casefolded text, so a capitalised phrase is dead.

    Easy mistake for a reviewer adding "Қазпошта" the way the brand is written.
    """
    for phrase in kk(indicator_id):
        assert phrase == fold_for_matching(phrase), f"{indicator_id}: {phrase!r} must be lowercase"


@pytest.mark.parametrize("indicator_id", sorted(load()))
def test_phrases_are_non_empty_and_unique(indicator_id):
    phrases = kk(indicator_id)
    assert all(phrases), f"{indicator_id} carries an empty phrase"
    duplicates = sorted({p for p in phrases if phrases.count(p) > 1})
    assert not duplicates, f"{indicator_id} repeats {duplicates}"


def test_uncertain_entries_are_marked_for_the_reviewer():
    """An honest VERIFY-kk is worth more than a confident wrong pattern.

    The reviewer's entry point into this file is `grep VERIFY-kk`. If that
    returns nothing, either the file is perfect or nobody was honest.
    """
    assert LEXICON.read_text(encoding="utf-8").count("VERIFY-kk") >= 5


def test_missing_indicator_raises_rather_than_returning_empty():
    """A silent empty list would restore the exact hole the markers stood for."""
    with pytest.raises(KeyError, match=r"kk_lexicon\.yaml"):
        kk("Z9.not_an_indicator")
