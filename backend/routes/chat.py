"""Chat + LLM proxy endpoints — thin compat layer.

Phase 2 refactor: implementation split into chat_context.py (context
builder + web search) and chat_proxy.py (LLM provider fan-out, SSE
streaming, models/providers endpoints). This module re-exports
everything and merges routers for backward compatibility.
"""

from __future__ import annotations

from fastapi import APIRouter

from chat_context import *  # noqa: F401,F403
from chat_context import router as _context_router
from chat_proxy import *  # noqa: F401,F403
from chat_proxy import router as _proxy_router

# Explicit re-exports for symbols imported by other modules
from chat_context import (
    OLLAMA_HOSTS,
    _ollama_hosts,
    _is_embed_model,
    _models_cache,
    _MODELS_CACHE_TTL,
    build_chat_context,
)
from chat_proxy import (
    _prepare_chat_messages,
    chat_proxy,
    list_models,
    list_providers,
)

router = APIRouter(tags=["chat"])
router.routes.extend(_context_router.routes)
router.routes.extend(_proxy_router.routes)
