"""Async SQLAlchemy engine/session management.

PostgreSQL is the intended system of record. The same ORM models run unchanged on
SQLite so the prototype boots with no infrastructure; ``dialect_name`` lets the few
places that need dialect-specific SQL (JSONB, upsert) branch explicitly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.core.errors import PersistenceError
from app.core.logging import get_logger

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _create_engine(settings: Settings) -> AsyncEngine:
    kwargs: dict = {"echo": settings.db_echo, "future": True}
    if settings.is_sqlite:
        # SQLite has no pool sizing and needs explicit FK enforcement.
        engine = create_async_engine(settings.database_url, **kwargs)

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # pragma: no cover - driver callback
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine
    kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_size,
        pool_pre_ping=True,
    )
    return create_async_engine(settings.database_url, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _create_engine(get_settings())
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, autoflush=False, class_=AsyncSession
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope. Commits on success, rolls back and re-raises on failure."""
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session


async def check_database() -> tuple[bool, str | None]:
    """Readiness probe. Returns ``(ok, error_message)``; never raises."""
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # pragma: no cover - environment dependent
        log.warning("database_unavailable", extra={"error": str(exc)})
        return False, str(exc)


async def require_database() -> None:
    ok, err = await check_database()
    if not ok:
        raise PersistenceError("decision store unavailable", details={"reason": err})


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def dialect_name() -> str:
    return get_engine().dialect.name
