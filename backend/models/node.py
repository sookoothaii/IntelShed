"""WorldBase — Pydantic v2 models for node_sync system.

This module defines type-safe models for edge node telemetry ingestion,
mesh networking, health monitoring, and briefing responses.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


# =============================================================================
# Sensor Models
# =============================================================================


class SensorData(BaseModel):
    """Environmental sensor readings from edge nodes.

    Captures temperature and humidity data from attached sensors like
    BME280, DHT22, or SHT30 modules.
    """

    model_config = ConfigDict(
        title="Sensor Data",
        json_schema_extra={
            "examples": [
                {"temp_c": 22.5, "humidity_pct": 65.0},
                {"temp_c": -5.2, "humidity_pct": 82.3},
            ]
        },
    )

    temp_c: Optional[float] = Field(
        default=None,
        ge=-40.0,
        le=85.0,
        description="Temperature in Celsius (typical sensor range -40 to +85°C)",
        examples=[22.5, -5.2, 38.7],
    )
    humidity_pct: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Relative humidity percentage (0-100%)",
        examples=[65.0, 45.2, 88.0],
    )

    @field_validator("temp_c")
    @classmethod
    def validate_temp_range(cls, v: Optional[float]) -> Optional[float]:
        """Validate temperature is within realistic sensor bounds."""
        if v is not None and not -40.0 <= v <= 125.0:
            raise ValueError("Temperature must be between -40.0 and 125.0°C")
        return v

    @computed_field(description="Heat index in Celsius (feels-like temperature)")
    @property
    def heat_index_c(self) -> Optional[float]:
        """Calculate heat index using simplified formula (valid for temp > 27°C, humidity > 40%)."""
        if self.temp_c is None or self.humidity_pct is None:
            return None
        if self.temp_c < 27 or self.humidity_pct < 40:
            return None
        # Simplified heat index formula
        T, R = self.temp_c, self.humidity_pct
        HI = (
            -8.784695
            + 1.61139411 * T
            + 2.338549 * R
            - 0.14611605 * T * R
            - 0.012308094 * T**2
            - 0.016424828 * R**2
            + 0.002211732 * T**2 * R
            + 0.00072546 * T * R**2
            - 0.000003582 * T**2 * R**2
        )
        return round(HI, 2)


class HealthData(BaseModel):
    """System health metrics from the edge node.

        Monitors CPU temperature, memory usage, and disk utilization
    to ensure the Pi is operating within safe parameters.
    """

    model_config = ConfigDict(
        title="Health Data",
        json_schema_extra={
            "examples": [
                {"cpu_temp_c": 45.2, "ram_pct": 68.0, "disk_pct": 72.0},
                {"cpu_temp_c": 62.5, "ram_pct": 88.0, "disk_pct": 91.5},
            ]
        },
    )

    cpu_temp_c: float = Field(
        ...,
        ge=0.0,
        le=125.0,
        description="CPU temperature in Celsius (Raspberry Pi typical range 30-85°C)",
        examples=[45.2, 62.5, 38.0],
    )
    ram_pct: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="RAM utilization percentage (0-100%)",
        examples=[68.0, 45.0, 92.0],
    )
    disk_pct: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Root filesystem utilization percentage (0-100%)",
        examples=[72.0, 55.0, 95.0],
    )
    services: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional status of key services (e.g., {'pihole': 'running', 'meshtastic': 'running'})",
    )

    @field_validator("cpu_temp_c")
    @classmethod
    def validate_cpu_temp(cls, v: float) -> float:
        """Warn if CPU temperature is in critical range."""
        if v > 85.0:
            raise ValueError("CPU temperature exceeds safe operating limit (85°C)")
        return v

    @computed_field(description="Overall system health score (0-100)")
    @property
    def health_score(self) -> int:
        """Calculate overall health score based on metrics.

        - CPU temp: optimal <55°C, critical >70°C
        - RAM: optimal <70%, critical >95%
        - Disk: optimal <70%, critical >92%
        """
        scores = []

        # CPU temp score (inverse - lower is better)
        temp_score = max(0, min(100, 100 - (self.cpu_temp_c - 30) * 2.5))
        scores.append(temp_score)

        # RAM score (inverse - lower is better)
        ram_score = max(0, min(100, 100 - self.ram_pct))
        scores.append(ram_score)

        # Disk score (inverse - lower is better)
        disk_score = max(0, min(100, 100 - self.disk_pct * 1.1))
        scores.append(disk_score)

        return int(sum(scores) / len(scores))

    @computed_field(description="True if any metric is in warning or critical state")
    @property
    def has_issues(self) -> bool:
        """Check if any health metric is in warning or critical state."""
        return self.cpu_temp_c >= 55.0 or self.ram_pct >= 88.0 or self.disk_pct >= 85.0


# =============================================================================
# Network Models
# =============================================================================


class MeshNode(BaseModel):
    """A single node in the Meshtastic mesh network.

    Represents a peer device visible to the edge node via LoRa mesh.
    """

    model_config = ConfigDict(
        title="Mesh Node",
        json_schema_extra={
            "examples": [
                {
                    "id": "!a1b2c3d4",
                    "name": "Tracker",
                    "lat": 52.5205,
                    "lon": 13.4055,
                    "battery_pct": 78.0,
                    "snr": 12.5,
                }
            ]
        },
    )

    id: str = Field(
        ...,
        min_length=2,
        max_length=32,
        pattern=r"^[!]?[a-f0-9]+$",
        description="Meshtastic node ID (hex string, optionally prefixed with !)",
        examples=["!a1b2c3d4", "deadbeef"],
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=40,
        description="Human-readable node name",
        examples=["Tracker", "Field Node Alpha", "Base Station"],
    )
    lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Latitude in decimal degrees (-90 to +90)",
        examples=[52.5205, -33.8688, 0.0],
    )
    lon: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Longitude in decimal degrees (-180 to +180)",
        examples=[13.4055, 151.2093, 0.0],
    )
    battery_pct: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Battery level percentage (0-100%) if available",
        examples=[78.0, 45.5, 12.0],
    )
    snr: Optional[float] = Field(
        default=None,
        ge=-20.0,
        le=30.0,
        description="Signal-to-noise ratio in dB from last received packet",
        examples=[12.5, -5.2, 18.0],
    )
    last_seen: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of last contact with this node",
        examples=["2026-06-09T12:34:56Z"],
    )

    @field_validator("lat")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        """Ensure latitude is within valid range."""
        if not -90 <= v <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("lon")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        """Ensure longitude is within valid range."""
        if not -180 <= v <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v


class PiholeStats(BaseModel):
    """Pi-hole DNS filtering statistics.

    Tracks DNS query volume and ad/tracker blocking performance.
    """

    model_config = ConfigDict(
        title="Pi-hole Statistics",
        json_schema_extra={
            "examples": [
                {"queries": 12345, "blocked": 5678, "percent": 45.9},
                {"queries": 987654, "blocked": 321456, "percent": 32.5},
            ]
        },
    )

    queries: int = Field(
        ...,
        ge=0,
        description="Total DNS queries processed",
        examples=[12345, 987654],
    )
    blocked: int = Field(
        ...,
        ge=0,
        description="Number of queries blocked (ads, trackers, malware)",
        examples=[5678, 321456],
    )
    percent: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Percentage of queries that were blocked",
        examples=[45.9, 32.5],
    )

    @model_validator(mode="after")
    def validate_percent_matches(self) -> Self:
        """Ensure percent field roughly matches blocked/queries ratio."""
        if self.queries > 0:
            calculated = (self.blocked / self.queries) * 100
            # Allow 5% tolerance for rounding differences
            if abs(calculated - self.percent) > 5.0:
                raise ValueError(
                    f"Percent ({self.percent}) doesn't match blocked/queries ratio "
                    f"({calculated:.1f}%)"
                )
        return self

    @computed_field(description="Queries that were allowed (not blocked)")
    @property
    def allowed(self) -> int:
        """Calculate number of allowed (non-blocked) queries."""
        return self.queries - self.blocked


# =============================================================================
# Location Models
# =============================================================================


class GPSData(BaseModel):
    """GPS/GNSS positioning data.

    Location information from GPS module or other positioning source.
    """

    model_config = ConfigDict(
        title="GPS Data",
        json_schema_extra={
            "examples": [
                {"lat": 52.5200, "lon": 13.4050, "altitude_m": 34.0, "accuracy_m": 5.2},
                {
                    "lat": -33.8688,
                    "lon": 151.2093,
                    "altitude_m": 58.5,
                    "accuracy_m": 12.0,
                },
            ]
        },
    )

    lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Latitude in decimal degrees (-90 to +90)",
        examples=[52.5200, -33.8688],
    )
    lon: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Longitude in decimal degrees (-180 to +180)",
        examples=[13.4050, 151.2093],
    )
    altitude_m: Optional[float] = Field(
        default=None,
        ge=-500.0,
        le=10000.0,
        description="Altitude above sea level in meters",
        examples=[34.0, 58.5, -12.0],
    )
    accuracy_m: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=10000.0,
        description="Horizontal accuracy (HDOP) in meters",
        examples=[5.2, 12.0, 2.5],
    )
    satellites: Optional[int] = Field(
        default=None,
        ge=0,
        le=50,
        description="Number of satellites used in fix",
        examples=[8, 12, 4],
    )
    fix_type: Optional[Literal["none", "2d", "3d", "dgps", "rtk"]] = Field(
        default=None,
        description="GPS fix quality/type",
        examples=["3d", "dgps", "rtk"],
    )

    @field_validator("lat")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        """Ensure latitude is within valid range."""
        if not -90 <= v <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("lon")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        """Ensure longitude is within valid range."""
        if not -180 <= v <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v

    @computed_field(description="Approximate location accuracy quality")
    @property
    def accuracy_quality(
        self,
    ) -> Literal["excellent", "good", "fair", "poor", "unknown"]:
        """Classify GPS accuracy quality based on HDOP."""
        if self.accuracy_m is None:
            return "unknown"
        if self.accuracy_m <= 3:
            return "excellent"
        if self.accuracy_m <= 8:
            return "good"
        if self.accuracy_m <= 15:
            return "fair"
        return "poor"


# =============================================================================
# Ingestion Models
# =============================================================================


class NodeIngestPayload(BaseModel):
    """Main payload for node telemetry ingestion (Pi -> PC).

    This is the primary model for the POST /api/node/ingest endpoint.
    The Pi periodically pushes its complete state to WorldBase using this schema.
    """

    model_config = ConfigDict(
        title="Node Ingest Payload",
        json_schema_extra={
            "examples": [
                {
                    "node_id": "offgrid-pi",
                    "name": "Off-Grid Pi",
                    "lat": 52.5200,
                    "lon": 13.4050,
                    "sensors": {"temp_c": 22.5, "humidity_pct": 65.0},
                    "health": {"cpu_temp_c": 45.2, "ram_pct": 68.0, "disk_pct": 72.0},
                    "mesh": [
                        {
                            "id": "!a1b2c3d4",
                            "name": "Tracker",
                            "lat": 52.5205,
                            "lon": 13.4055,
                        }
                    ],
                    "pihole": {"queries": 1234, "blocked": 567, "percent": 45.9},
                }
            ]
        },
    )

    node_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Unique node identifier (alphanumeric, hyphens, underscores)",
        examples=["offgrid-pi", "field-node-alpha", "base_001"],
    )
    name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Human-readable node name (defaults to node_id if not provided)",
        examples=["Off-Grid Pi", "Field Station Alpha"],
    )
    lat: Optional[float] = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Node latitude in decimal degrees",
        examples=[52.5200, -33.8688],
    )
    lon: Optional[float] = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Node longitude in decimal degrees",
        examples=[13.4050, 151.2093],
    )
    sensors: Optional[SensorData] = Field(
        default=None,
        description="Environmental sensor readings",
    )
    health: Optional[HealthData] = Field(
        default=None,
        description="System health metrics",
    )
    mesh: Optional[list[MeshNode]] = Field(
        default=None,
        max_length=100,
        description="List of visible mesh network peers",
    )
    pihole: Optional[PiholeStats] = Field(
        default=None,
        description="Pi-hole DNS filtering statistics",
    )
    gps: Optional[GPSData] = Field(
        default=None,
        description="GPS/GNSS positioning data (alternative to top-level lat/lon)",
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of payload generation (defaults to server time)",
        examples=["2026-06-09T12:34:56.789Z"],
    )
    version: Optional[str] = Field(
        default=None,
        description="Software/firmware version string",
        examples=["1.2.3", "v2.0.0-beta"],
    )

    @field_validator("lat")
    @classmethod
    def validate_latitude(cls, v: Optional[float]) -> Optional[float]:
        """Ensure latitude is within valid range."""
        if v is not None and not -90 <= v <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("lon")
    @classmethod
    def validate_longitude(cls, v: Optional[float]) -> Optional[float]:
        """Ensure longitude is within valid range."""
        if v is not None and not -180 <= v <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v

    @model_validator(mode="after")
    def validate_location_present(self) -> Self:
        """Ensure at least one location source is provided (lat/lon or gps)."""
        has_top_level = self.lat is not None and self.lon is not None
        has_gps = self.gps is not None
        if not has_top_level and not has_gps:
            raise ValueError("Either lat/lon or gps must be provided")
        return self

    @computed_field(description="Normalized GPS coordinates (from gps or top-level)")
    @property
    def location(self) -> GPSData:
        """Get location as GPSData, preferring gps field over top-level lat/lon."""
        if self.gps is not None:
            return self.gps
        return GPSData(lat=self.lat or 0.0, lon=self.lon or 0.0)

    @computed_field(description="Total number of visible mesh peers")
    @property
    def mesh_peer_count(self) -> int:
        """Count visible mesh peers."""
        return len(self.mesh) if self.mesh else 0


# =============================================================================
# Response Models
# =============================================================================


class NodeBriefing(BaseModel):
    """Situation briefing returned to the node (PC -> Pi).

    The Pi pulls this via GET /api/node/pull to display global
    situational awareness even when offline from the internet.
    """

    model_config = ConfigDict(
        title="Node Briefing",
        json_schema_extra={
            "examples": [
                {
                    "generated_at": "2026-06-09T12:34:56.789Z",
                    "briefing": "Space weather calm (Kp=2). No critical fusion hotspots. "
                    "Edge nodes: all online. 12,345 DNS queries processed, 5,678 blocked.",
                    "briefing_at": "2026-06-09T12:30:00Z",
                    "alerts": [],
                }
            ]
        },
    )

    generated_at: str = Field(
        ...,
        description="ISO 8601 timestamp when this response was generated",
        examples=["2026-06-09T12:34:56.789Z"],
    )
    briefing: str = Field(
        ...,
        max_length=10000,
        description="Human-readable situational awareness briefing",
        examples=[
            "Space weather calm (Kp=2). No critical fusion hotspots. "
            "Edge nodes: all online."
        ],
    )
    briefing_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when the briefing content was generated",
        examples=["2026-06-09T12:30:00Z"],
    )
    alerts: list["NodeAlert"] = Field(
        default_factory=list,
        description="List of current critical alerts affecting this node",
    )
    mesh_compressed: Optional[str] = Field(
        default=None,
        max_length=230,
        description="Compressed briefing for LoRa/Meshtastic (<230 bytes)",
        examples=["[M]HF radio/GPS may degrade|[L]volcanoes active|Space calm"],
    )

    @computed_field(description="Number of active alerts")
    @property
    def alert_count(self) -> int:
        """Count active alerts."""
        return len(self.alerts)

    @computed_field(description="Highest severity level among alerts")
    @property
    def highest_severity(
        self,
    ) -> Optional[Literal["critical", "high", "medium", "low"]]:
        """Determine highest severity among active alerts."""
        if not self.alerts:
            return None
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        min_severity = min(self.alerts, key=lambda a: severity_order.get(a.severity, 9))
        return min_severity.severity


class NodeAlert(BaseModel):
    """Individual sensor or system alert.

    Generated when sensor readings exceed configured thresholds
    or when system health issues are detected.
    """

    model_config = ConfigDict(
        title="Node Alert",
        json_schema_extra={
            "examples": [
                {
                    "id": 1,
                    "node_id": "offgrid-pi",
                    "sensor": "cpu_temp_c",
                    "severity": "warning",
                    "value": 62.5,
                    "threshold": 55.0,
                    "message": "CPU temperature elevated — consider ventilation",
                    "created_at": "2026-06-09T12:34:56Z",
                }
            ]
        },
    )

    id: Optional[int] = Field(
        default=None,
        ge=1,
        description="Database alert ID (if stored)",
        examples=[1, 42, 999],
    )
    node_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Node that generated this alert",
        examples=["offgrid-pi", "field-node-alpha"],
    )
    sensor: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Sensor or metric name that triggered the alert",
        examples=["cpu_temp_c", "battery_pct", "disk_pct"],
    )
    severity: Literal["critical", "high", "warning", "medium", "low"] = Field(
        ...,
        description="Alert severity level",
        examples=["critical", "warning"],
    )
    value: float = Field(
        ...,
        description="Current sensor value that triggered the alert",
        examples=[62.5, 15.0, 92.0],
    )
    threshold: Optional[float] = Field(
        default=None,
        description="Threshold value that was exceeded",
        examples=[55.0, 30.0, 85.0],
    )
    message: str = Field(
        ...,
        max_length=500,
        description="Human-readable alert message with remediation guidance",
        examples=["CPU temperature elevated — consider ventilation"],
    )
    created_at: str = Field(
        ...,
        description="ISO 8601 timestamp when alert was generated",
        examples=["2026-06-09T12:34:56Z"],
    )
    lat: Optional[float] = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Node latitude for geographic alert display",
        examples=[52.5200, -33.8688],
    )
    lon: Optional[float] = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Node longitude for geographic alert display",
        examples=[13.4050, 151.2093],
    )

    @field_validator("lat")
    @classmethod
    def validate_latitude(cls, v: Optional[float]) -> Optional[float]:
        """Ensure latitude is within valid range."""
        if v is not None and not -90 <= v <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("lon")
    @classmethod
    def validate_longitude(cls, v: Optional[float]) -> Optional[float]:
        """Ensure longitude is within valid range."""
        if v is not None and not -180 <= v <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v

    @computed_field(description="Severity numeric rank (0=critical, 4=low)")
    @property
    def severity_rank(self) -> int:
        """Get numeric severity rank for sorting (lower = more severe)."""
        return {"critical": 0, "high": 1, "warning": 2, "medium": 3, "low": 4}.get(
            self.severity, 9
        )


# =============================================================================
# Additional Response/Utility Models
# =============================================================================


class NodeStatus(BaseModel):
    """Node status response from list endpoints."""

    model_config = ConfigDict(
        title="Node Status",
        json_schema_extra={
            "examples": [
                {
                    "node_id": "offgrid-pi",
                    "name": "Off-Grid Pi",
                    "lat": 52.5200,
                    "lon": 13.4050,
                    "updated_at": "2026-06-09T12:34:56Z",
                    "age_seconds": 45,
                    "online": True,
                }
            ]
        },
    )

    node_id: str = Field(..., description="Unique node identifier")
    name: str = Field(..., description="Human-readable node name")
    lat: Optional[float] = Field(default=None, description="Node latitude")
    lon: Optional[float] = Field(default=None, description="Node longitude")
    updated_at: str = Field(..., description="Last update timestamp")
    age_seconds: Optional[float] = Field(
        default=None, description="Seconds since last update"
    )
    online: bool = Field(default=False, description="Whether node is considered online")
    sensors: dict[str, Any] = Field(default_factory=dict, description="Raw sensor data")
    mesh: list[dict[str, Any]] = Field(
        default_factory=list, description="Raw mesh node data"
    )
    pihole: dict[str, Any] = Field(default_factory=dict, description="Raw pihole data")
    health: dict[str, Any] = Field(default_factory=dict, description="Raw health data")


class NodeListResponse(BaseModel):
    """Response from GET /api/nodes endpoint."""

    count: int = Field(..., description="Number of nodes returned")
    nodes: list[NodeStatus] = Field(..., description="List of node statuses")


class AlertListResponse(BaseModel):
    """Response from GET /api/alerts endpoint."""

    count: int = Field(..., description="Number of alerts returned")
    alerts: list[NodeAlert] = Field(..., description="List of alerts")


class CommandPayload(BaseModel):
    """Command sent from PC to Pi."""

    model_config = ConfigDict(
        title="Command Payload",
        json_schema_extra={
            "examples": [
                {"command": "reboot", "args": {}},
                {"command": "restart_service", "args": {"service": "pihole"}},
            ]
        },
    )

    command: Literal[
        "reboot", "shutdown", "restart_service", "update_config", "exec"
    ] = Field(
        ...,
        description="Command type to execute on the node",
        examples=["reboot", "restart_service"],
    )
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Command arguments (varies by command type)",
        examples=[{"service": "pihole"}, {"script": "maintenance.sh"}],
    )


class CommandAck(BaseModel):
    """Command acknowledgment from Pi."""

    status: Literal["done", "failed", "pending"] = Field(
        ..., description="Command execution status"
    )
    result: Optional[str] = Field(
        default=None, description="Command output or error message"
    )


class SensorHistoryPoint(BaseModel):
    """Single sensor history data point."""

    t: str = Field(..., description="ISO 8601 timestamp")
    v: float = Field(..., description="Sensor value")


class SensorHistoryResponse(BaseModel):
    """Response from GET /api/node/{id}/sensors/history endpoint."""

    node_id: str = Field(..., description="Node identifier")
    sensor: str = Field(..., description="Sensor name or 'all'")
    hours: int = Field(..., description="Hours of history requested")
    series: dict[str, list[SensorHistoryPoint]] = Field(
        ..., description="Time series data keyed by sensor name"
    )


class LatestSensorsResponse(BaseModel):
    """Response from GET /api/node/{id}/sensors/latest endpoint."""

    node_id: str = Field(..., description="Node identifier")
    sensors: dict[str, dict[str, Any]] = Field(
        ..., description="Latest sensor values with timestamps"
    )


class MeshNodesResponse(BaseModel):
    """Response from GET /api/mesh/nodes endpoint."""

    count: int = Field(..., description="Total mesh nodes across all Pis")
    nodes: list[dict[str, Any]] = Field(..., description="Mesh node details")
