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
from briefing_digest import (
    OPERATOR_REGION,
    BRIEFING_LANG,
    _ASEAN_BBOX,
    _LOCAL_KEYWORDS,
    _REGION_KEYWORDS,
    _SEVERITY_RANK,
    _gdelt_local_slots,
    _newsdata_slots,
    _is_newsdata_item,
    _watch_max_items,
    _watch_id,
    _cell_id,
    _watch_item,
    enrich_watch_items_coords,
    _resolve_lang,
    _region_bbox,
    _region_label,
    haversine_km,
    _in_bbox,
    _text_bucket,
    classify_item,
    _line,
    _pm25_severity,
    _collect_digest_items,
    build_watch_items,
    format_watch_items_block,
    _severity_key,
    _sort_bucket,
    format_digest_sections,
)
from briefing_prompt import (
    _lang_instructions,
    _prediction_calibration_line,
    build_security_advisor_prompt,
    format_fallback_protocol,
)
