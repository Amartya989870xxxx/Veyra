"""SQLAlchemy declarative base and portable column types."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, MetaData, Numeric, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB on PostgreSQL (indexable, typed); plain JSON on SQLite.
JSONType = JSON().with_variant(JSONB(), "postgresql")

Money = Numeric(14, 2)


class UtcDateTime(TypeDecorator):
    """Timezone-aware datetimes that survive SQLite's naive storage.

    SQLite drops tzinfo, so a naive value read back would silently compare wrong against
    an aware value. Normalising on both sides keeps window arithmetic correct.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def id_column(primary_key: bool = False, nullable: bool = False, index: bool = False):
    return mapped_column(String(128), primary_key=primary_key, nullable=nullable, index=index)


def utcnow() -> datetime:
    return datetime.now(UTC)
