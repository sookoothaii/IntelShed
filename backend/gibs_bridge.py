"""NASA GIBS WMTS layer catalog for the globe (no API key)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

router = APIRouter(prefix="/api/gibs", tags=["gibs"])

# EPSG:4326 best-quality WMTS templates (time placeholder {time})
_LAYERS = [
    {
        "id": "modis_terra_fires",
        "label": "MODIS Terra Thermal (Fires)",
        "wmts": "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/MODIS_Terra_Thermal_Anomalies_All/default/{time}/250m/{z}/{y}/{x}.jpg",
        "format": "image/jpeg",
        "tileMatrixSet": "250m",
    },
    {
        "id": "goes_east_abi",
        "label": "GOES-East ABI (visible)",
        "wmts": "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/GOES-East_ABI_GeoColor/default/{time}/250m/{z}/{y}/{x}.jpg",
        "format": "image/jpeg",
        "tileMatrixSet": "250m",
    },
    {
        "id": "viirs_snpp_corrected",
        "label": "VIIRS SNPP Corrected Reflectance",
        "wmts": "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/{time}/250m/{z}/{y}/{x}.jpg",
        "format": "image/jpeg",
        "tileMatrixSet": "250m",
    },
]


@router.get("/latest")
def gibs_latest():
    """Suggested WMTS date token (yesterday UTC — GIBS latency)."""
    day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    return {"date": day, "format": "YYYY-MM-DD"}


@router.get("/layers")
def gibs_layers():
    """WMTS layer definitions for optional Cesium imagery overlay."""
    day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    return {
        "provider": "NASA GIBS",
        "epsg": 4326,
        "default_date": day,
        "time_hint": "Use ISO date YYYY-MM-DD in WMTS URL",
        "layers": _LAYERS,
        "docs": "https://nasa-gibs.github.io/gibs-api-docs/",
    }
