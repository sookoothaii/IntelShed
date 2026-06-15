"""
WorldBase Database Module

SQLAlchemy 2.0 async ORM with PostgreSQL + asyncpg support.
"""

from backend.db.models import (
    Base,
    NodeState,
    Briefing,
    SensorAlert,
    NodeCommand,
    SensorHistory,
    FeedCache,
    Aircraft,
    Satellite,
)
from backend.db.database import (
    get_engine,
    get_db,
    get_db_context,
    init_db,
    close_db,
    health_check,
    SessionLocal,
)

__all__ = [
    # Models
    "Base",
    "NodeState",
    "Briefing",
    "SensorAlert",
    "NodeCommand",
    "SensorHistory",
    "FeedCache",
    "Aircraft",
    "Satellite",
    # Database utilities
    "get_engine",
    "get_db",
    "get_db_context",
    "init_db",
    "close_db",
    "health_check",
    "SessionLocal",
]
