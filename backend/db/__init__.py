"""
WorldBase Database Module

SQLAlchemy 2.0 async ORM with PostgreSQL + asyncpg support.
"""

try:
    from .models import (
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
    from .database import (
        get_engine,
        get_db,
        get_db_context,
        init_db,
        close_db,
        health_check,
        SessionLocal,
    )
except ImportError:
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
    "Base",
    "NodeState",
    "Briefing",
    "SensorAlert",
    "NodeCommand",
    "SensorHistory",
    "FeedCache",
    "Aircraft",
    "Satellite",
    "get_engine",
    "get_db",
    "get_db_context",
    "init_db",
    "close_db",
    "health_check",
    "SessionLocal",
]
