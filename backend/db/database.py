"""
Database configuration and session management for WorldBase.
PostgreSQL + asyncpg with SQLAlchemy 2.0 async support.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# Load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
    AsyncEngine,
)
from sqlalchemy.pool import NullPool

try:
    from backend.db.models import Base
except ImportError:
    from models import Base


# Database URL from environment or default for development
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://worldbase:worldbase@localhost:5432/worldbase"
)

# Global engine instance (initialized once)
_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Get or create the async database engine.
    
    Uses connection pooling optimized for async operations.
    """
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            DATABASE_URL,
            echo=os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true",
            pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
            pool_pre_ping=True,
            pool_recycle=3600,
            future=True,
        )
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Get the async session factory.
    
    Creates sessions with:
    - expire_on_commit=False (for async safety)
    - autoflush=False (manual flush control)
    """
    engine = get_engine()
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# Convenience alias for FastAPI dependency injection
SessionLocal = get_session_maker


async def init_db() -> None:
    """Initialize the database by creating all tables.
    
    Safe to run multiple times - existing tables are not recreated.
    Should be called during application startup.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections and cleanup resources.
    
    Should be called during application shutdown.
    """
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions.
    
    Usage:
        @app.get("/items")
        async def read_items(db: AsyncSession = Depends(get_db)):
            ...
    
    Automatically handles session lifecycle:
    - Creates new session per request
    - Commits on success
    - Rolls back on exception
    - Closes session
    """
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions outside of FastAPI.
    
    Usage:
        async with get_db_context() as db:
            result = await db.execute(...)
    
    Automatically commits on successful exit, rolls back on exception.
    """
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def health_check() -> bool:
    """Check database connectivity.
    
    Returns True if database is accessible, False otherwise.
    """
    try:
        from sqlalchemy import text
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
