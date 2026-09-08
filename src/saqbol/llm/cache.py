"""Disk cache, which is also the cassette layer.

One mechanism serves two purposes that would otherwise be built twice:

* development and eval reruns do not pay twice for an identical call;
* T115 and T507 replay a whole pipeline in CI with no key and no network,
  because a committed cache directory *is* the recording.

That dual role is why the key covers everything that could change the answer.
If a prompt is edited, the key changes and the old entry is simply never read
again, which is the correct behaviour: a cassette recorded against a different
prompt is not evidence about the current one.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

#: Bumped when the on-disk entry shape changes, so old files are ignored
#: rather than misread.
CACHE_VERSION = 1

ENV_CACHE_DIR = "SAQBOL_LLM_CACHE_DIR"
DEFAULT_CACHE_DIR = Path(".cache") / "llm"


class CacheEntry(BaseModel):
    version: int = CACHE_VERSION
    model: str
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    recorded_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def cache_key(
    *,
    model: str,
    system: str,
    user: str,
    schema_name: str,
    temperature: float,
) -> str:
    """sha256 over everything that determines the response.

    Fields are length-prefixed rather than joined by a separator, so no
    combination of inputs containing the separator can collide with another.
    """
    digest = hashlib.sha256()
    for part in (str(CACHE_VERSION), model, system, user, schema_name, f"{temperature:.4f}"):
        encoded = part.encode("utf-8")
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b"\x00")
        digest.update(encoded)
    return digest.hexdigest()


class DiskCache:
    """A flat content-addressed store, sharded one level to keep directories small."""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = os.environ.get(ENV_CACHE_DIR) or DEFAULT_CACHE_DIR
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> CacheEntry | None:
        path = self._path(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError:
            return None

        try:
            entry = CacheEntry.model_validate_json(raw)
        except ValueError:
            # A corrupt or hand-edited entry is treated as absent. Raising here
            # would let one bad file break an eval run that has already spent
            # money on the other several hundred.
            return None

        return entry if entry.version == CACHE_VERSION else None

    def put(self, key: str, entry: CacheEntry) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Written through a temp file in the same directory, then renamed, so a
        # crashed or concurrent run never leaves a half-written cassette that a
        # later run would read as truth.
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(entry.model_dump_json(indent=2))
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def __len__(self) -> int:
        if not self.root.exists():
            return 0
        return sum(1 for _ in self.root.rglob("*.json"))
