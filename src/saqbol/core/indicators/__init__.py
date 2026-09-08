"""Indicator families.

Importing this package registers every rule. Family modules are imported for
their side effect, which is why they are re-exported in `__all__` rather than
left as unused imports.

Family G (links and domains) is registered by `links.py`; the analysis itself
lives in `url_analyzer.py`, which keeps its one network path opt-in.
"""

from __future__ import annotations

from saqbol.core.indicators import (
    authority,
    channel,
    credentials,
    links,
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
    "links",
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
