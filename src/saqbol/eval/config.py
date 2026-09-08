"""T501 — the evaluation matrix, read from a YAML file.

A config is a matrix, not a script: every system in `systems` is crossed with
every model, split, language and ablation, and each product is one cell of
`results.json`. Cells that cannot run — no provider key, a split file that
does not exist yet, an ablation the split cannot support — are recorded with a
reason rather than failing the run, so a partial matrix is still an honest
record of what was measured and what was not.

The file is validated against the closed sets in `saqbol.eval.results`, since
a system or ablation name that the results writer would reject is better
caught before an hour of model calls than after. The hash of the validated
config travels into the manifest, so a published number can be traced back to
exactly the matrix that produced it.

Relative split paths are resolved against the working directory, which is the
repository root when the harness is run the way docs/05_EVAL_PROTOCOL.md
shows: `python -m saqbol.eval run --config eval/configs/v0.1.yaml`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from saqbol.core.types import Band
from saqbol.eval.results import LANGS, Ablation, Split, System

#: Contract: the bootstrap seed a config carries when it names none.
DEFAULT_SEED = 20260908
#: Contract: docs/05_EVAL_PROTOCOL.md section 5, "Bootstrap, 10,000 resamples".
DEFAULT_N_BOOTSTRAP = 10_000
#: Systems that call a model and therefore need a provider key to run.
LLM_SYSTEMS: tuple[System, ...] = ("llm_zeroshot", "hybrid")
#: Names accepted for the baseline ablation besides the contract's `none`.
ABLATION_ALIASES: dict[str, str] = {"original": "none", "baseline": "none"}
#: Bands a prediction may be counted as positive under. `unsure` is an
#: abstention, never a positive.
_POSITIVE_CHOICES: tuple[str, ...] = tuple(b.value for b in Band if b is not Band.UNSURE)


class EvalConfig(BaseModel):
    """One evaluation matrix, as read from `eval/configs/*.yaml`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    dataset_version: str = Field(default="kazscam-v0.1", min_length=1)
    seed: int = DEFAULT_SEED
    n_bootstrap: int = Field(default=DEFAULT_N_BOOTSTRAP, ge=1)
    systems: list[System] = Field(min_length=1)
    models: list[str] = Field(default_factory=list)
    #: Split name to JSONL path, as written in the file.
    splits: dict[Split, str] = Field(min_length=1)
    #: Values of the row's `lang` field to slice by; `all` is no filter.
    languages: list[str] = Field(default_factory=lambda: ["all"], min_length=1)
    ablations: list[Ablation] = Field(default_factory=lambda: ["none"], min_length=1)
    #: Verdict bands scored as a positive (`scam`) prediction. The default
    #: counts a `suspicious` warning as a positive, because a warning on a
    #: genuine bank SMS is what makes people uninstall, whatever its wording.
    positive_bands: list[str] = Field(default_factory=lambda: ["scam", "suspicious"], min_length=1)
    #: Rows in flight at once within a cell. Only matters for systems that
    #: call a model; predictions are collected in row order regardless.
    concurrency: int = Field(default=4, ge=1)

    @field_validator("ablations", mode="before")
    @classmethod
    def _alias_ablations(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [ABLATION_ALIASES.get(v, v) if isinstance(v, str) else v for v in value]
        return value

    @field_validator("systems", "models", "languages", "ablations", "positive_bands")
    @classmethod
    def _no_duplicates(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        for item in value:
            if item in seen:
                raise ValueError(f"{item!r} is listed twice")
            seen.add(item)
        return value

    @field_validator("models")
    @classmethod
    def _model_names(cls, value: list[str]) -> list[str]:
        if any(not m.strip() for m in value):
            raise ValueError("model names must not be empty")
        return value

    @field_validator("languages")
    @classmethod
    def _known_languages(cls, value: list[str]) -> list[str]:
        unknown = [v for v in value if v not in LANGS]
        if unknown:
            raise ValueError(f"languages must be among {LANGS}, got {unknown}")
        return value

    @field_validator("positive_bands")
    @classmethod
    def _known_bands(cls, value: list[str]) -> list[str]:
        unknown = [v for v in value if v not in _POSITIVE_CHOICES]
        if unknown:
            raise ValueError(f"positive_bands must be among {_POSITIVE_CHOICES}, got {unknown}")
        return value

    @field_validator("splits")
    @classmethod
    def _split_paths(cls, value: dict[Split, str]) -> dict[Split, str]:
        for name, path in value.items():
            if not isinstance(path, str) or not path.strip():
                raise ValueError(f"split {name!r} needs a file path")
        return value

    @model_validator(mode="after")
    def _models_for_llm_systems(self) -> EvalConfig:
        if self.needs_models and not self.models:
            wanted = [s for s in self.systems if s in LLM_SYSTEMS]
            raise ValueError(f"systems {wanted} call a model, so `models` must list at least one")
        return self

    @property
    def needs_models(self) -> bool:
        return any(s in LLM_SYSTEMS for s in self.systems)

    def split_path(self, split: str) -> Path:
        """The split's file, resolved against the working directory."""
        return Path(self.splits[split])  # type: ignore[index]


def load_config(path: str | os.PathLike[str]) -> EvalConfig:
    """Read and validate a matrix file. Raises on any shape error."""
    text = Path(path).read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return EvalConfig.model_validate(payload)


def config_hash(config: EvalConfig) -> str:
    """A stable digest of the validated matrix, for the run manifest.

    Hashing the validated model rather than the file text means two files
    that differ only in comments, key order or an ablation alias hash the
    same, which is the equivalence a reader wants when checking that two runs
    measured the same thing. `concurrency` changes no number and is left out.
    """
    payload = config.model_dump(mode="json", exclude={"concurrency"})
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
