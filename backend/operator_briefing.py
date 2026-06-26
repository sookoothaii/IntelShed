"""Security-advisor style 24h digest — operator home region + world pulse.

Phase 2 refactor: implementation split into briefing_digest.py (feed
classification, digest collection, watch items) and briefing_prompt.py
(LLM prompt building, fallback protocol). This module re-exports
everything for backward compatibility.
"""

from __future__ import annotations

from briefing_digest import *  # noqa: F401,F403
from briefing_prompt import *  # noqa: F401,F403

# Explicit re-exports for symbols used with `from operator_briefing import X`
# Star-import doesn't re-export _-prefixed names, so list them explicitly.
from briefing_digest import (  # noqa: F401
    _ASEAN_BBOX,
    _pm25_severity,
    _region_bbox,
    _text_bucket,
)
