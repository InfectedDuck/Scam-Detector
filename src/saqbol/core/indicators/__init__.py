"""Indicator families.

Importing this package registers every rule. Family modules are imported for
their side effect, which is why they are re-exported in `__all__` rather than
left as unused imports.

Family G (links and domains) is implemented in `url_analyzer.py` and registered
by `links.py`, which arrives with T107.
"""

from __future__ import annotations

from saqbol.core.indicators import (
    authority,
    channel,
    credentials,
    metadata,
    money,
    offers,
    social,
    software,
    urgency,
)
from saqbol.core.indicators.registry import (
    REGISTRY,
    DetectionContext,
    build_context,
    rule_norm,
    run_all,
    score,
)

__all__ = [
    "REGISTRY",
    "DetectionContext",
    "authority",
    "build_context",
    "channel",
    "credentials",
    "metadata",
    "money",
    "offers",
    "rule_norm",
    "run_all",
    "score",
    "social",
    "software",
    "urgency",
]
