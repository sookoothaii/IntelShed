"""
SQLAlchemy 2.0 async ORM models for WorldBase.
PostgreSQL + asyncpg compatible.
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    String,
    Float,
    DateTime,
    Boolean,
    Integer,
    ForeignKey,
    Index,
    JSON,
    Text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.ext.asyncio import AsyncAttrs


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all async SQLAlchemy models."""

    pass


class NodeState(Base):
    """Represents the current state of a mesh network node."""

    __tablename__ = "node_state"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    sensors_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    health_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    mesh_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    pihole_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    briefings: Mapped[List["Briefing"]] = relationship(
        back_populates="node",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    sensor_alerts: Mapped[List["SensorAlert"]] = relationship(
        back_populates="node",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    commands: Mapped[List["NodeCommand"]] = relationship(
        back_populates="node",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    sensor_history: Mapped[List["SensorHistory"]] = relationship(
        back_populates="node",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_node_state_last_seen", "last_seen"),
        Index("idx_node_state_location", "lat", "lon"),
    )


class Briefing(Base):
    """AI-generated briefings for nodes."""

    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("node_state.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    node: Mapped["NodeState"] = relationship(back_populates="briefings")

    __table_args__ = (
        Index("idx_briefings_node_id", "node_id"),
        Index("idx_briefings_generated_at", "generated_at"),
        Index("idx_briefings_expires_at", "expires_at"),
    )


class SensorAlert(Base):
    """Sensor-based alerts from nodes."""

    __tablename__ = "sensor_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("node_state.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    node: Mapped["NodeState"] = relationship(back_populates="sensor_alerts")

    __table_args__ = (
        Index("idx_sensor_alerts_node_id", "node_id"),
        Index("idx_sensor_alerts_created_at", "created_at"),
        Index("idx_sensor_alerts_acknowledged", "acknowledged"),
        Index("idx_sensor_alerts_severity", "severity"),
        Index("idx_sensor_alerts_type", "alert_type"),
    )


class NodeCommand(Base):
    """Commands issued to nodes."""

    __tablename__ = "node_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("node_state.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    command: Mapped[str] = mapped_column(String(128), nullable=False)
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    node: Mapped["NodeState"] = relationship(back_populates="commands")

    __table_args__ = (
        Index("idx_node_commands_node_id", "node_id"),
        Index("idx_node_commands_status", "status"),
        Index("idx_node_commands_created_at", "created_at"),
    )


class SensorHistory(Base):
    """Historical sensor data from nodes."""

    __tablename__ = "sensor_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("node_state.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    temp_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cpu_temp_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ram_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    node: Mapped["NodeState"] = relationship(back_populates="sensor_history")

    __table_args__ = (
        Index("idx_sensor_history_node_id", "node_id"),
        Index("idx_sensor_history_recorded_at", "recorded_at"),
        Index("idx_sensor_history_node_recorded", "node_id", "recorded_at"),
    )


class FeedCache(Base):
    """Cache for external feed data."""

    __tablename__ = "feed_cache"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)

    __table_args__ = (
        Index("idx_feed_cache_cached_at", "cached_at"),
        Index("idx_feed_cache_ttl", "ttl_seconds"),
    )


class Aircraft(Base):
    """ADS-B aircraft tracking data."""

    __tablename__ = "aircraft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    icao24: Mapped[str] = mapped_column(String(8), nullable=False)
    callsign: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    altitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    track: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("idx_aircraft_icao24", "icao24"),
        Index("idx_aircraft_callsign", "callsign"),
        Index("idx_aircraft_recorded_at", "recorded_at"),
        Index("idx_aircraft_location", "lat", "lon"),
        Index("idx_aircraft_icao_recorded", "icao24", "recorded_at"),
    )


class Satellite(Base):
    """Satellite TLE (Two-Line Element) data."""

    __tablename__ = "satellites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    tle1: Mapped[str] = mapped_column(String(80), nullable=False)
    tle2: Mapped[str] = mapped_column(String(80), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("idx_satellites_name", "name"),
        Index("idx_satellites_recorded_at", "recorded_at"),
    )
