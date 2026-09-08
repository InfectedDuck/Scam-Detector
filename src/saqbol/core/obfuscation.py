"""Adversarial obfuscation: turning one fixture into a family of harder ones.

Two jobs, both of which produce numbers for the report.

**Generation.** Every transform here is a pure, seeded, reproducible function
from text to text. Given one clean fixture it yields the same message written
the way it arrives when the sender is trying not to be matched: Cyrillic and
Latin letters swapped for their lookalikes, invisible characters wedged between
letters, words broken up with spaces or dots, letters replaced by the digits
they resemble.

**Measurement.** `measure_recall` runs the deterministic layer over a corpus
twice, clean and transformed, and reports how many indicator hits survive. That
number is the honest answer to "how brittle is the rules-only baseline", and it
belongs in the report next to the leaderboard rather than being discovered by a
reviewer.

Not every transform is an attack, and the distinction is recorded on each spec:

* `LATIN_KAZAKH` and `LATIN_ASCII` are how a growing number of people write
  Kazakh, given the ongoing Cyrillic-to-Latin script transition. A recall drop
  here is not an adversary defeating the system, it is the system failing a
  legitimate user, which is the more serious of the two failures.
* `CUE_MASK` is the `cue_masked` ablation from docs/05_EVAL_PROTOCOL.md section
  6, expressed as one more transform rather than as a separate hand-built
  corpus. Brand names, short codes and numbers become typed placeholders, so a
  system that scores a message because it contains the word "Kaspi" loses that
  crutch while the structure of the request survives.

Nothing here touches the network, a clock, or an API key, so the whole module
runs inside the `rules_only` row and inside CI.

Character offsets are *not* preserved. These transforms change length, so a
transformed message is a new document that must be re-normalized and
re-analysed from scratch. That is deliberate: the evidence-span invariant
`normalized[start:end] == text` is checked against whatever text was actually
analysed, and quietly reusing clean offsets would break it.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import regex as re

from saqbol.core.extract import extract
from saqbol.core.indicators.registry import build_context, run_all, score
from saqbol.core.normalize import normalize
from saqbol.core.patterns import AMOUNT_PREFIX, AMOUNT_SUFFIX

#: Default seed. Every number this module produces has to be reproducible from
#: a config file, per docs/05_EVAL_PROTOCOL.md section 8, so no transform is
#: allowed to reach for global randomness.
DEFAULT_SEED = 7


class Attack(StrEnum):
    """Transform names. Stable: they end up as column headers in results.json."""

    HOMOGLYPH = "homoglyph"
    ZERO_WIDTH = "zero_width"
    FORMAT_CHARS = "format_chars"
    SPACING = "spacing"
    PUNCTUATION = "punctuation"
    LEET = "leet"
    LATIN_KAZAKH = "latin_kazakh"
    LATIN_ASCII = "latin_ascii"
    CUE_MASK = "cue_mask"
    COMBINED = "combined"


# --------------------------------------------------------------------------
# Character tables
# --------------------------------------------------------------------------

#: Cyrillic letters whose Latin twin is visually identical, or close enough that
#: nobody reading a message on a phone would notice. Restricted to genuine
#: confusables: "т" is a poor lowercase "t" but a perfect uppercase "T", so the
#: two cases are listed separately rather than folded together.
#:
#: `url_analyzer.CONFUSABLES` carries the same idea for hostnames, where the
#: mapping is one-way and used to build a comparison skeleton. Here it has to
#: run in both directions, because the attack is applied to running text that
#: already mixes scripts, so the two tables are related but not interchangeable.
CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "і": "i",
    "ѕ": "s",
    "ј": "j",
    "һ": "h",
    "ԁ": "d",
    "ӏ": "l",
    "ԛ": "q",
    "ԝ": "w",
    "ё": "e",
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
    "І": "I",
    "Ј": "J",
    "Ѕ": "S",
    "Һ": "H",
    "Ԁ": "D",
}

#: The inverse. A Latin word inside a Russian message, "AnyDesk" or "CVV" or
#: "WhatsApp", is attacked by pushing letters the other way, which is how a
#: remote-access app name gets past `F1.remote_access_app`.
LATIN_TO_CYRILLIC: dict[str, str] = {
    "a": "а",
    "c": "с",
    "e": "е",
    "o": "о",
    "p": "р",
    "x": "х",
    "y": "у",
    "i": "і",
    "s": "ѕ",
    "j": "ј",
    "h": "һ",
    "d": "ԁ",
    "l": "ӏ",
    "q": "ԛ",
    "w": "ԝ",
    "A": "А",
    "B": "В",
    "C": "С",
    "E": "Е",
    "H": "Н",
    "I": "І",
    "J": "Ј",
    "K": "К",
    "M": "М",
    "O": "О",
    "P": "Р",
    "S": "Ѕ",
    "T": "Т",
    "X": "Х",
    "Y": "У",
    "D": "Ԁ",
}

HOMOGLYPHS: dict[str, str] = {**CYRILLIC_TO_LATIN, **LATIN_TO_CYRILLIC}

#: Invisible characters that `normalize.INVISIBLE` removes. Inserting these is
#: the oldest keyword-evasion trick there is, and stage 0 already answers it,
#: which is worth measuring precisely so the report can say so with a number
#: instead of with a claim.
ZERO_WIDTH_CHARS: tuple[str, ...] = (
    "​",  # zero width space
    "‌",  # zero width non-joiner
    "‍",  # zero width joiner
    "⁠",  # word joiner
    "­",  # soft hyphen
    "﻿",  # zero width no-break space
)

#: Invisible characters that `normalize.INVISIBLE` does **not** remove. They
#: render as nothing, survive NFKC, and sit between letters exactly like the
#: characters above, so they defeat every phrase match in the catalogue.
#:
#: This is a live gap in stage 0, recorded in `tests/test_adversarial.py` as an
#: xfail rather than patched here, because normalization is not this module's
#: to change. Closing it is a one-line edit to `normalize.INVISIBLE`: add
#: U+034F, U+180E and the U+FE00-FE0F variation selectors.
FORMAT_CHAR_GAP: tuple[str, ...] = (
    "͏",  # combining grapheme joiner
    "᠎",  # mongolian vowel separator
    "︀",  # variation selector-1
    "️",  # variation selector-16
)

#: Punctuation wedged between letters. All of it survives normalization, since
#: it is ordinary visible punctuation, and all of it breaks a phrase match.
PUNCTUATION_CHARS: tuple[str, ...] = (".", "-", "_", "*", "·")

#: Digits for the letters they resemble, in both scripts. Russian and Kazakh
#: writers use the Cyrillic half routinely, so this is a cheap evasion that
#: costs the sender almost no legibility.
LEET: dict[str, str] = {
    "о": "0",
    "О": "0",
    "з": "3",
    "З": "3",
    "ч": "4",
    "б": "6",
    "в": "8",
    "o": "0",
    "O": "0",
    "e": "3",
    "E": "3",
    "a": "4",
    "A": "4",
    "i": "1",
    "l": "1",
    "s": "5",
    "S": "5",
    "t": "7",
    "b": "6",
    "g": "9",
}

#: Kazakh Cyrillic to Latin, following the 2021 alphabet (umlauts and breves)
#: for the Kazakh letters, with pragmatic fallbacks for the Russian-only letters
#: that appear in code-switched text.
#:
#: This is a transliteration adequate for measuring a recall drop, not a
#: standards-compliant romanization, and it should not be cited as one. Where
#: the 2021 alphabet is silent about a Russian letter Kazakh has no use for,
#: the common informal choice is taken.
KAZAKH_LATIN: dict[str, str] = {
    "а": "a",
    "ә": "ä",
    "б": "b",
    "в": "v",
    "г": "g",
    "ғ": "ğ",
    "д": "d",
    "е": "e",
    "ё": "io",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "i",
    "к": "k",
    "қ": "q",
    "л": "l",
    "м": "m",
    "н": "n",
    "ң": "ñ",
    "о": "o",
    "ө": "ö",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ұ": "ū",
    "ү": "ü",
    "ф": "f",
    "х": "h",
    "һ": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "ş",
    "щ": "şş",
    "ъ": "",
    "ы": "y",
    "і": "i",
    "ь": "",
    "э": "e",
    "ю": "iu",
    "я": "ia",
}

#: What people actually type on a phone with no Kazakh Latin layout: digraphs
#: instead of diacritics, and no distinction between the letters the diacritics
#: were carrying. Strictly lossier than `KAZAKH_LATIN`, and far more common.
KAZAKH_LATIN_ASCII: dict[str, str] = {
    **KAZAKH_LATIN,
    "ә": "a",
    "ғ": "g",
    "ж": "zh",
    "қ": "k",
    "ң": "n",
    "ө": "o",
    "ұ": "u",
    "ү": "u",
    "ш": "sh",
    "щ": "sch",
    "ё": "yo",
    "ю": "yu",
    "я": "ya",
}

#: Typed placeholders for `CUE_MASK`, shaped like `privacy.PLACEHOLDER`, so a
#: masked corpus and a scrubbed corpus read the same way.
#:
#: Typed rather than blanked, for the reason `privacy.scrub` gives: the text has
#: to stay linguistically usable. A model should still be able to tell that a
#: message demanded *a sum of money* and quoted *a short code*, because that
#: structure is what the ablation is asking whether it can reason about.
CUE_PLACEHOLDER: dict[str, str] = {
    "brand": "<BRAND>",
    "url": "<URL>",
    "amount": "<AMOUNT>",
    "short_code": "<SHORTCODE>",
    "number": "<NUM>",
}

_URL_LIKE = re.compile(
    r"(?:https?://|www\.)\S+"
    r"|(?<![@\w./])(?:[\p{L}\p{N}][\p{L}\p{N}-]*\.)+[\p{L}]{2,24}(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)
_DIGIT_RUN = re.compile(r"(?<![\d\w])\d+(?![\d])")
_WORD = re.compile(r"\p{L}[\p{L}\p{M}\p{Nd}]*")


# --------------------------------------------------------------------------
# Primitive transforms
# --------------------------------------------------------------------------


def _rng_for(text: str, attack: str, seed: int) -> random.Random:
    """A generator seeded on the message as well as on the run.

    Seeding per message rather than per corpus means one message's obfuscation
    does not depend on how many messages preceded it, so a single row can be
    reproduced from `results.json` without replaying the whole corpus.
    """
    return random.Random(f"{seed}:{attack}:{text}")


def _substitute(text: str, table: dict[str, str], rate: float, rng: random.Random) -> str:
    return "".join(table[ch] if ch in table and rng.random() < rate else ch for ch in text)


def _insert_inside_words(text: str, rate: float, rng: random.Random, palette: Sequence[str]) -> str:
    """Wedge a character from `palette` between two adjacent alphanumerics.

    Only word interiors are touched. Inserting at a word boundary would be
    invisible to a matcher that already splits on whitespace, and would make
    the attack look weaker than it is.
    """
    out: list[str] = []
    last = len(text) - 1
    for i, ch in enumerate(text):
        out.append(ch)
        if i < last and ch.isalnum() and text[i + 1].isalnum() and rng.random() < rate:
            out.append(rng.choice(palette))
    return "".join(out)


def _transliterate_word(word: str, table: dict[str, str]) -> str:
    out = "".join(table.get(ch.lower(), ch) for ch in word)
    if not out:
        return out
    if word.isupper() and len(word) > 1:
        return out.upper()
    if word[:1].isupper():
        return out[:1].upper() + out[1:]
    return out


def _transliterate(text: str, table: dict[str, str], rate: float, rng: random.Random) -> str:
    """Rewrite whole words rather than individual characters.

    Script choice is a property of a word, not of a letter. At a `rate` below
    1.0 the result is a message with some words in Latin and some in Cyrillic,
    which is what genuinely code-switched Kazakh looks like today.
    """

    def repl(m: re.Match) -> str:
        word = m.group(0)
        if rng.random() >= rate:
            return word
        return _transliterate_word(word, table)

    return _WORD.sub(repl, text)


def homoglyph(text: str, rate: float, rng: random.Random) -> str:
    """Swap letters for their lookalikes in the other script."""
    return _substitute(text, HOMOGLYPHS, rate, rng)


def zero_width(text: str, rate: float, rng: random.Random) -> str:
    """Insert invisible characters that stage 0 strips."""
    return _insert_inside_words(text, rate, rng, ZERO_WIDTH_CHARS)


def format_chars(text: str, rate: float, rng: random.Random) -> str:
    """Insert invisible characters stage 0 misses. See `FORMAT_CHAR_GAP`."""
    return _insert_inside_words(text, rate, rng, FORMAT_CHAR_GAP)


def spacing(text: str, rate: float, rng: random.Random) -> str:
    """Break words apart with spaces, the way "срочно" becomes "с р о ч н о"."""
    return _insert_inside_words(text, rate, rng, (" ",))


def punctuation(text: str, rate: float, rng: random.Random) -> str:
    """Break words apart with visible punctuation, the way "код" becomes "к.о.д"."""
    return _insert_inside_words(text, rate, rng, PUNCTUATION_CHARS)


def leet(text: str, rate: float, rng: random.Random) -> str:
    """Replace letters with the digits that look like them."""
    return _substitute(text, LEET, rate, rng)


def latin_kazakh(text: str, rate: float, rng: random.Random) -> str:
    """Rewrite Cyrillic words in the 2021 Kazakh Latin alphabet."""
    return _transliterate(text, KAZAKH_LATIN, rate, rng)


def latin_ascii(text: str, rate: float, rng: random.Random) -> str:
    """Rewrite Cyrillic words the way a phone keyboard makes people write them."""
    return _transliterate(text, KAZAKH_LATIN_ASCII, rate, rng)


def combined(text: str, rate: float, rng: random.Random) -> str:
    """Homoglyphs, invisibles and punctuation together, each at a low rate.

    Applied in this order because substitution has to precede insertion: a
    letter with a zero-width character wedged after it is still that letter,
    but running the homoglyph table over already-broken words would change
    which positions count as word interiors.
    """
    out = homoglyph(text, rate, rng)
    out = zero_width(out, rate, rng)
    return punctuation(out, rate / 2, rng)


def cue_mask(text: str, rate: float, rng: random.Random) -> str:
    """The `cue_masked` ablation: brands, short codes and numbers to placeholders.

    `rate` and `rng` are accepted for a uniform transform signature and then
    ignored. Masking a random half of the brand mentions would leave the model
    the other half, which is not the ablation docs/05_EVAL_PROTOCOL.md
    describes.

    Order matters and is the same idea `privacy.scrub` uses. URLs go first and
    go whole: a link carries the brand name in its host and frequently a number
    in its path, so masking brands while leaving `kaspi-secure.ru/1414`
    standing would leave the cue in the one place it matters most. Amounts are
    reserved before short codes, or a five-figure sum in tenge is masked as a
    bank's four-digit short code and the message stops meaning what it meant.

    Digits inside an alphanumeric identifier — a parcel number like
    `RB123456789KZ` — are left alone. Splitting one produces text no sender
    would ever write, and the ablation is supposed to yield messages that are
    still plausible. It is a stated limit of the manipulation, not an oversight.
    """
    from saqbol.core.url_analyzer import load_reference

    masked = _URL_LIKE.sub(CUE_PLACEHOLDER["url"], text)

    brands, _ = load_reference()
    terms = sorted({t for b in brands for t in b.terms if t}, key=len, reverse=True)
    if terms:
        pattern = re.compile(
            r"(?<!\p{L})(?:" + "|".join(re.escape(t) for t in terms) + r")(?!\p{L})",
            re.IGNORECASE,
        )
        masked = pattern.sub(CUE_PLACEHOLDER["brand"], masked)

    for amount in (AMOUNT_SUFFIX, AMOUNT_PREFIX):
        masked = amount.sub(CUE_PLACEHOLDER["amount"], masked)

    def mask_digits(m: re.Match) -> str:
        run = m.group(0)
        key = "short_code" if 3 <= len(run) <= 5 else "number"
        return CUE_PLACEHOLDER[key]

    return _DIGIT_RUN.sub(mask_digits, masked)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TransformSpec:
    fn: Callable[[str, float, random.Random], str]
    default_rate: float
    hostile: bool
    description: str


#: Default rates are what the attack looks like in the wild, not the maximum
#: the transform can reach. A sender who homoglyphs every eligible letter
#: produces a message that reads as broken; these rates keep the output
#: plausible enough that a recipient would still act on it.
TRANSFORMS: dict[Attack, TransformSpec] = {
    Attack.HOMOGLYPH: TransformSpec(
        homoglyph, 0.35, True, "Cyrillic and Latin letters swapped for lookalikes"
    ),
    Attack.ZERO_WIDTH: TransformSpec(
        zero_width, 0.5, True, "Invisible characters that stage 0 strips"
    ),
    Attack.FORMAT_CHARS: TransformSpec(
        format_chars, 0.5, True, "Invisible characters that stage 0 does not strip"
    ),
    Attack.SPACING: TransformSpec(spacing, 0.3, True, "Words broken apart with spaces"),
    Attack.PUNCTUATION: TransformSpec(
        punctuation, 0.3, True, "Words broken apart with punctuation"
    ),
    Attack.LEET: TransformSpec(leet, 0.6, True, "Letters replaced by lookalike digits"),
    Attack.LATIN_KAZAKH: TransformSpec(
        latin_kazakh, 1.0, False, "Kazakh written in the 2021 Latin alphabet"
    ),
    Attack.LATIN_ASCII: TransformSpec(
        latin_ascii, 1.0, False, "Kazakh written in ASCII Latin, as typed on a phone"
    ),
    Attack.CUE_MASK: TransformSpec(
        cue_mask, 1.0, False, "Brands, short codes and numbers replaced by placeholders"
    ),
    Attack.COMBINED: TransformSpec(
        combined, 0.25, True, "Homoglyphs, invisibles and punctuation together"
    ),
}


def obfuscate(
    text: str,
    attack: Attack | str,
    *,
    rate: float | None = None,
    seed: int = DEFAULT_SEED,
) -> str:
    """Apply one transform. Deterministic in `(text, attack, rate, seed)`."""
    attack = Attack(attack)
    spec = TRANSFORMS[attack]
    effective = spec.default_rate if rate is None else rate
    return spec.fn(text, effective, _rng_for(text, attack, seed))


def obfuscate_all(
    text: str, *, seed: int = DEFAULT_SEED, attacks: Iterable[Attack] | None = None
) -> dict[Attack, str]:
    """One message, every transform. The unit the recall table is built from."""
    chosen = list(TRANSFORMS) if attacks is None else [Attack(a) for a in attacks]
    return {a: obfuscate(text, a, seed=seed) for a in chosen}


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


def _analyse(text: str) -> tuple[set[str], int]:
    """Indicator ids and rule score for one message, through the whole layer."""
    # Imported here rather than at module scope: importing the package registers
    # every family as a side effect, and a caller who wants only the text
    # transforms should not have to pay for that.
    import saqbol.core.indicators  # noqa: F401

    norm = normalize(text)
    ctx = build_context(norm, extract(norm.text))
    hits = run_all(ctx)
    return {h.indicator_id for h in hits}, score(hits)


@dataclass(frozen=True)
class RecallReport:
    """What one transform did to the deterministic layer.

    Recall is over `(message, indicator_id)` pairs, treating what fires on the
    clean text as ground truth. That is the right denominator for this
    question: it asks what share of the detections the system already makes
    survive the rewrite, and it does not depend on hand-declared expectations
    that would go stale as the catalogue grows.
    """

    attack: str
    rate: float
    seed: int
    messages: int
    clean_pairs: int
    survived_pairs: int
    spurious_pairs: int
    clean_score: int
    attacked_score: int
    per_indicator: dict[str, tuple[int, int]] = field(default_factory=dict)
    lost_examples: tuple[tuple[str, str], ...] = ()

    @property
    def recall(self) -> float:
        """Share of clean indicator hits that still fire after the transform."""
        return self.survived_pairs / self.clean_pairs if self.clean_pairs else 1.0

    @property
    def drop(self) -> float:
        """The headline number: how much recall the transform costs."""
        return 1.0 - self.recall

    @property
    def score_retained(self) -> float:
        """Share of the summed rule score that survives.

        Reported next to recall because banding in `fuse.py` reads the score,
        not the hit count. Losing four low-severity hits and losing one
        critical one are the same recall and a very different verdict.
        """
        return self.attacked_score / self.clean_score if self.clean_score else 1.0

    @property
    def by_family(self) -> dict[str, tuple[int, int]]:
        """Clean and surviving counts per indicator family."""
        out: dict[str, tuple[int, int]] = {}
        for indicator_id, (clean, survived) in self.per_indicator.items():
            family = indicator_id[0]
            prev = out.get(family, (0, 0))
            out[family] = (prev[0] + clean, prev[1] + survived)
        return dict(sorted(out.items()))


def measure_recall(
    messages: Sequence[str],
    attack: Attack | str,
    *,
    rate: float | None = None,
    seed: int = DEFAULT_SEED,
    keep_examples: int = 3,
) -> RecallReport:
    """Run the deterministic layer over `messages` clean, then transformed."""
    attack = Attack(attack)
    spec = TRANSFORMS[attack]
    effective = spec.default_rate if rate is None else rate

    clean_pairs = survived_pairs = spurious_pairs = 0
    clean_total = attacked_total = 0
    per_indicator: dict[str, tuple[int, int]] = {}
    lost: list[tuple[str, str]] = []

    for message in messages:
        clean_ids, clean_score = _analyse(message)
        attacked = obfuscate(message, attack, rate=effective, seed=seed)
        attacked_ids, attacked_score = _analyse(attacked)

        clean_total += clean_score
        attacked_total += attacked_score
        clean_pairs += len(clean_ids)
        survived_pairs += len(clean_ids & attacked_ids)
        spurious_pairs += len(attacked_ids - clean_ids)

        for indicator_id in clean_ids:
            prev = per_indicator.get(indicator_id, (0, 0))
            per_indicator[indicator_id] = (
                prev[0] + 1,
                prev[1] + (1 if indicator_id in attacked_ids else 0),
            )
        for indicator_id in sorted(clean_ids - attacked_ids):
            if len(lost) < keep_examples:
                lost.append((indicator_id, attacked))

    return RecallReport(
        attack=str(attack),
        rate=effective,
        seed=seed,
        messages=len(messages),
        clean_pairs=clean_pairs,
        survived_pairs=survived_pairs,
        spurious_pairs=spurious_pairs,
        clean_score=clean_total,
        attacked_score=attacked_total,
        per_indicator=dict(sorted(per_indicator.items())),
        lost_examples=tuple(lost),
    )


def recall_table(
    messages: Sequence[str],
    *,
    attacks: Iterable[Attack] | None = None,
    seed: int = DEFAULT_SEED,
) -> list[RecallReport]:
    """One `RecallReport` per transform, over the same corpus."""
    chosen = list(TRANSFORMS) if attacks is None else [Attack(a) for a in attacks]
    return [measure_recall(messages, a, seed=seed) for a in chosen]


def format_markdown(reports: Sequence[RecallReport]) -> str:
    """The recall table as it goes into the report.

    Generated, never hand-edited, on the same principle as `leaderboard.md`.
    """
    lines = [
        "| Transform | Kind | Rate | Indicator recall | Score retained | Spurious hits |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for r in reports:
        spec = TRANSFORMS[Attack(r.attack)]
        kind = "attack" if spec.hostile else "natural"
        lines.append(
            f"| `{r.attack}` | {kind} | {r.rate:.2f} | {r.recall:.1%} "
            f"| {r.score_retained:.1%} | {r.spurious_pairs} |"
        )
    return "\n".join(lines)
