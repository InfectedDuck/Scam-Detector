"""Stage 3b: playbook retrieval.

Two implementations behind one protocol.

`LexicalRetriever` scores a message against each playbook's phrase list with no
dependencies, no model download and no network. It is the default, and it is
what lets the whole pipeline — including the `rules_only` and `hybrid`
leaderboard rows — run inside CI with no key.

`DenseRetriever` uses sentence embeddings when the optional extra is installed.
Keeping both is not hedging: lexical versus dense retrieval is a leaderboard
row of its own, and a hybrid that beats rules only because of dense retrieval
is a different claim from one that beats them on the model's judgement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import regex as re

from saqbol.core.indicators.registry import compile_phrase, fold_for_matching
from saqbol.playbooks.schema import Playbook

_WORD = re.compile(r"[\p{L}\p{Nd}]{3,}")
_HAN_RUN = re.compile(r"[\p{Han}]+")

#: Vocabulary coverage carries the score because it works whether the phrase
#: lists are written as scammer wording or as victim descriptions. A literal
#: phrase hit is a strong extra signal on top.
OVERLAP_WEIGHT = 0.70
PHRASE_WEIGHT = 0.30

#: Controls how fast the phrase score saturates. At 2.0 one hit scores 0.39,
#: two 0.63, three 0.78 — diminishing returns, so a playbook with many phrases
#: cannot win on volume alone.
SATURATION = 2.0


@runtime_checkable
class Retriever(Protocol):
    def search(self, text: str, k: int = 3) -> list[tuple[str, float]]:
        """Top `k` playbook ids with similarity in [0, 1], best first."""
        ...


def tokens(text: str) -> set[str]:
    """Content tokens, with Chinese handled by character bigrams.

    Chinese is written without spaces and its words are one or two characters,
    so a three-character minimum tokenised every Chinese message to nothing and
    scored the whole China playbook set at zero. Bigrams are the standard way
    to index Chinese without shipping a word segmenter.
    """
    folded = fold_for_matching(text)
    found = set(_WORD.findall(folded))
    for run in _HAN_RUN.findall(folded):
        if len(run) == 1:
            found.add(run)
        else:
            found.update(run[i : i + 2] for i in range(len(run) - 1))
    return found


@dataclass
class _Index:
    playbook_id: str
    phrases: tuple[str, ...]
    vocabulary: frozenset[str]


class LexicalRetriever:
    """Vocabulary-coverage scoring with a bonus for literal phrase hits.

    Deterministic, offline, explainable, and — importantly — indifferent to how
    the phrase lists are written.

    That last property was learned the hard way. The first version scored only
    whole-phrase substring hits, which assumes the phrases are spelled the way a
    scammer writes. The playbooks were written the other way, as first-person
    victim descriptions ("мне позвонили из службы безопасности банка"), and a
    victim's paraphrase never appears verbatim inside the scammer's message. A
    textbook bank-security scam scored 0.04 against its own playbook: fifteen
    phrases, zero hits, by construction.

    Both styles are defensible; they just suit different mechanics. Coverage of
    distinctive vocabulary works with either, so it carries the score, and a
    literal phrase hit is treated as a bonus rather than the whole signal.

    Still not semantic, and the report must say so: a paraphrase sharing no
    vocabulary is invisible to it. That is what `DenseRetriever` is for, and
    comparing the two is a leaderboard row.
    """

    def __init__(self, playbooks: dict[str, Playbook]) -> None:
        self._index = [
            _Index(
                playbook_id=pid,
                phrases=tuple(pb.retrieval_phrases),
                vocabulary=frozenset(tokens(pb.embedding_text())),
            )
            for pid, pb in sorted(playbooks.items())
        ]
        self._idf = self._build_idf()

    def _build_idf(self) -> dict[str, float]:
        """Inverse document frequency across the playbooks.

        A word appearing in every playbook — "банк", "деньги" — carries no
        information about which one applies and is weighted to nothing. A word
        in one playbook is what actually discriminates.
        """
        total = len(self._index)
        if total == 0:
            return {}
        frequency: dict[str, int] = {}
        for entry in self._index:
            for token in entry.vocabulary:
                frequency[token] = frequency.get(token, 0) + 1
        return {token: math.log(total / count) for token, count in frequency.items()}

    #: Weight for a token the corpus has never seen. Maximally distinctive, so
    #: a message full of unknown vocabulary scores low against every playbook
    #: rather than accidentally matching the shortest one.
    def _weight(self, token: str) -> float:
        default = math.log(max(2, len(self._index)))
        return self._idf.get(token, default)

    def __len__(self) -> int:
        return len(self._index)

    def score(self, text: str, entry: _Index) -> float:
        message_tokens = tokens(text)
        if not message_tokens:
            return 0.0

        total = sum(self._weight(token) for token in message_tokens)
        covered = sum(self._weight(token) for token in message_tokens & entry.vocabulary)
        coverage = covered / total if total else 0.0

        haystack = fold_for_matching(text)
        hits = sum(1 for phrase in entry.phrases if compile_phrase(phrase).search(haystack))
        phrase_score = 1.0 - math.exp(-hits / SATURATION)

        return min(1.0, OVERLAP_WEIGHT * coverage + PHRASE_WEIGHT * phrase_score)

    def explain(self, text: str, playbook_id: str) -> dict:
        """Why a playbook scored what it did. For error analysis in the report."""
        entry = next(e for e in self._index if e.playbook_id == playbook_id)
        message_tokens = tokens(text)
        shared = sorted(message_tokens & entry.vocabulary, key=lambda t: -self._weight(t))
        haystack = fold_for_matching(text)
        return {
            "score": round(self.score(text, entry), 4),
            "shared_tokens": shared[:15],
            "phrase_hits": [p for p in entry.phrases if compile_phrase(p).search(haystack)],
        }

    def search(self, text: str, k: int = 3) -> list[tuple[str, float]]:
        if not text.strip() or not self._index:
            return []
        scored = [(entry.playbook_id, self.score(text, entry)) for entry in self._index]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [(pid, round(score, 4)) for pid, score in scored[:k] if score > 0.0]


class DenseRetriever:
    """Sentence-embedding retrieval. Requires the optional `llm` extra.

    Constructed lazily so importing this module never pulls in torch.
    """

    def __init__(
        self, playbooks: dict[str, Playbook], model_name: str = "intfloat/multilingual-e5-small"
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as err:  # pragma: no cover - exercised only with the extra
            raise ImportError(
                "DenseRetriever needs the 'llm' extra: pip install -e '.[llm]'. "
                "LexicalRetriever is the dependency-free default."
            ) from err

        self._model = SentenceTransformer(model_name)
        self._ids = sorted(playbooks)
        # e5 expects these prefixes; omitting them measurably degrades retrieval.
        corpus = [f"passage: {playbooks[pid].embedding_text()}" for pid in self._ids]
        self._vectors = self._model.encode(corpus, normalize_embeddings=True)

    def __len__(self) -> int:
        return len(self._ids)

    def search(self, text: str, k: int = 3) -> list[tuple[str, float]]:  # pragma: no cover
        if not text.strip():
            return []
        query = self._model.encode([f"query: {text}"], normalize_embeddings=True)[0]
        scored = [
            (pid, float(vec @ query)) for pid, vec in zip(self._ids, self._vectors, strict=True)
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [(pid, round(max(0.0, score), 4)) for pid, score in scored[:k]]


class NullRetriever:
    """Retrieves nothing. The `llm_zeroshot` leaderboard row and the
    `no_playbook_context` ablation both run with this."""

    def search(self, text: str, k: int = 3) -> list[tuple[str, float]]:
        return []
