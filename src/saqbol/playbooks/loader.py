"""Playbook loading and validation.

Loading fails loudly. A playbook supplies the advice and the phone number shown
to someone who may be mid-scam, so a file that is malformed, orphaned from the
indicator registry, or missing its official source is an error at import time
rather than a gap discovered by a user.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from saqbol.playbooks.schema import PLAYBOOK_IDS, Playbook

DATA_DIR = Path(__file__).parent / "data"


class PlaybookError(Exception):
    """Raised for any problem that would let a bad playbook reach a user."""


def _load_file(path: Path, *, known_indicators: frozenset[str] | None) -> Playbook:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise PlaybookError(f"{path.name}: not valid YAML — {err}") from err

    if not isinstance(raw, dict):
        raise PlaybookError(f"{path.name}: expected a mapping at the top level")

    try:
        playbook = Playbook.model_validate(raw)
    except ValidationError as err:
        raise PlaybookError(f"{path.name}: {err}") from err

    if playbook.id != path.stem:
        raise PlaybookError(
            f"{path.name}: declares id {playbook.id!r}. The filename is the id, so a "
            "mismatch means one of the two is a typo."
        )

    if known_indicators is not None:
        unknown = sorted(set(playbook.expected_indicators) - known_indicators)
        if unknown:
            raise PlaybookError(
                f"{path.name}: expected_indicators names rules that do not exist: "
                f"{unknown}. A renamed rule must be updated here too, or the "
                "playbook silently loses the signals it was written around."
            )

    return playbook


def load_all(
    directory: Path | None = None, *, check_indicators: bool = True
) -> dict[str, Playbook]:
    """Every playbook in `directory`, keyed by id.

    `check_indicators` is switchable only so the schema can be tested without
    importing the registry. Production always checks.
    """
    directory = directory or DATA_DIR
    known: frozenset[str] | None = None
    if check_indicators:
        from saqbol.core.indicators import REGISTRY  # local import avoids a cycle

        known = frozenset(REGISTRY)

    playbooks: dict[str, Playbook] = {}
    for path in sorted(directory.glob("*.yaml")):
        playbook = _load_file(path, known_indicators=known)
        if playbook.id in playbooks:
            raise PlaybookError(f"{path.name}: duplicate playbook id {playbook.id!r}")
        playbooks[playbook.id] = playbook

    unknown = sorted(set(playbooks) - set(PLAYBOOK_IDS))
    if unknown:
        raise PlaybookError(f"playbooks outside the closed label set: {unknown}")

    return playbooks


@lru_cache(maxsize=1)
def registry() -> dict[str, Playbook]:
    """Process-wide cache. Call `registry.cache_clear()` after editing a file."""
    return load_all()


def get(playbook_id: str) -> Playbook:
    try:
        return registry()[playbook_id]
    except KeyError as err:
        raise PlaybookError(f"no playbook {playbook_id!r}") from err


def missing_playbooks(loaded: dict[str, Playbook] | None = None) -> list[str]:
    """Label-set entries with no file yet. Empty once T109 is finished."""
    loaded = registry() if loaded is None else loaded
    return [pid for pid in PLAYBOOK_IDS if pid not in loaded]


def translation_report(loaded: dict[str, Playbook] | None = None) -> dict[str, dict]:
    """What the co-annotators still have to translate, per playbook.

    Written for week two: the Kazakh and Chinese strings are somebody else's
    task with a deadline, so the gap needs to be countable rather than guessed.
    """
    loaded = registry() if loaded is None else loaded
    return {pid: pb.translation_gaps for pid, pb in loaded.items() if pb.translation_gaps}
