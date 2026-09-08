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

#: Phrase hits dominate; vocabulary overlap only separates near-ties.
PHRASE_WEIGHT = 0.75
OVERLAP_WEIGHT = 0.25

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
    return set(_WORD.findall(fold_for_matching(text)))


@dataclass
class _Index:
    playbook_id: str
    phrases: tuple[str, ...]
    vocabulary: frozenset[str]


class LexicalRetriever:
    """Phrase-overlap scoring. Deterministic, offline, explainable.

    Not semantic, and the report must say so: it cannot match a paraphrase that
    shares no vocabulary with any listed phrase. That is precisely why the
    playbooks carry ten to twenty phrasings each rather than one canonical
    description.
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

    def __len__(self) -> int:
        return len(self._index)

    def score(self, text: str, entry: _Index) -> float:
        haystack = fold_for_matching(text)
        hits = sum(1 for phrase in entry.phrases if compile_phrase(phrase).search(haystack))
        phrase_score = 1.0 - math.exp(-hits / SATURATION)

        message_tokens = tokens(text)
        overlap = (
            len(message_tokens & entry.vocabulary) / len(entry.vocabulary)
            if entry.vocabulary
            else 0.0
        )
        return PHRASE_WEIGHT * phrase_score + OVERLAP_WEIGHT * min(1.0, overlap)

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
