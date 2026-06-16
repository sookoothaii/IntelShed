"""ISO3 / name hints → lat/lon for humanitarian layers (no paid geocoder)."""

from __future__ import annotations

# Centroids (lat, lon) — civic OSINT, approximate
ISO3: dict[str, tuple[float, float]] = {
    "AFG": (33.9, 67.7),
    "BGD": (23.7, 90.4),
    "BRA": (-10.0, -55.0),
    "CAF": (6.6, 20.9),
    "CHN": (35.0, 103.0),
    "COD": (-2.5, 23.5),
    "COL": (4.5, -74.0),
    "ETH": (9.1, 40.5),
    "DEU": (51.1, 10.4),
    "GRC": (39.0, 22.0),
    "HTI": (18.9, -72.3),
    "IND": (22.0, 78.0),
    "IDN": (-2.5, 118.0),
    "IRN": (32.5, 53.5),
    "IRQ": (33.0, 44.0),
    "ISR": (31.5, 34.8),
    "JOR": (31.0, 36.0),
    "KEN": (0.2, 37.9),
    "LBN": (33.9, 35.9),
    "LBY": (26.3, 17.2),
    "MDG": (-18.8, 46.9),
    "MEX": (23.6, -102.5),
    "MMR": (21.9, 96.0),
    "THA": (13.75, 100.5),
    "MOZ": (-18.7, 35.5),
    "NGA": (9.1, 8.7),
    "PAK": (30.4, 69.3),
    "PSE": (31.9, 35.2),
    "PHL": (12.9, 121.8),
    "RUS": (55.8, 37.6),
    "SDN": (15.5, 32.5),
    "SOM": (5.2, 46.2),
    "SSD": (7.9, 30.0),
    "SYR": (35.0, 38.5),
    "TUR": (39.0, 35.0),
    "UKR": (48.4, 31.2),
    "USA": (39.8, -98.5),
    "VEN": (8.0, -66.0),
    "YEM": (15.6, 48.5),
    "ZWE": (-19.0, 29.2),
}

# Keywords in disaster titles → centroid
_NAME_HINTS: list[tuple[str, tuple[float, float]]] = [
    ("ukraine", (48.4, 31.2)),
    ("gaza", (31.5, 34.5)),
    ("sudan", (15.5, 32.5)),
    ("haiti", (18.9, -72.3)),
    ("myanmar", (21.9, 96.0)),
    ("syria", (35.0, 38.5)),
    ("afghan", (33.9, 67.7)),
    ("ethiopia", (9.1, 40.5)),
    ("somalia", (5.2, 46.2)),
    ("congo", (-2.5, 23.5)),
    ("mali", (17.5, -2.0)),
    ("niger", (17.6, 8.1)),
    ("lebanon", (33.9, 35.9)),
    ("venezuela", (8.0, -66.0)),
    ("pakistan", (30.4, 69.3)),
    ("bangladesh", (23.7, 90.4)),
    ("thailand", (13.75, 100.5)),
    ("bangkok", (13.75, 100.5)),
    ("turkey", (39.0, 35.0)),
    ("türkiye", (39.0, 35.0)),
    ("turkiye", (39.0, 35.0)),
    ("greenland", (72.0, -40.0)),
    ("philippines", (12.9, 121.8)),
    ("indonesia", (-2.5, 118.0)),
    ("mexico", (23.6, -102.5)),
    ("peru", (-9.2, -75.0)),
    ("chile", (-35.7, -71.5)),
    ("argentina", (-34.6, -58.4)),
    ("nepal", (28.4, 84.1)),
    ("sri lanka", (7.9, 80.8)),
]


_COUNTRY_NAMES: dict[str, tuple[float, float]] = {
    "italy": (41.9, 12.5),
    "japan": (36.2, 138.3),
    "colombia": (4.5, -74.0),
    "austria": (47.5, 14.5),
    "united states": (39.8, -98.5),
    "vanuatu": (-15.4, 166.9),
    "chile": (-35.7, -71.5),
    "germany": (51.1, 10.4),
    "france": (46.2, 2.2),
    "spain": (40.4, -3.7),
    "thailand": (13.75, 100.5),
    "china": (35.0, 103.0),
    "mexico": (23.6, -102.5),
    "brazil": (-10.0, -55.0),
    "canada": (56.0, -96.0),
    "australia": (-25.0, 135.0),
}


def resolve_lat_lon(
    *,
    name: str = "",
    iso3: str | None = None,
    countries: list | None = None,
) -> tuple[float | None, float | None]:
    if iso3 and iso3.upper() in ISO3:
        lat, lon = ISO3[iso3.upper()]
        return lat, lon
    if countries:
        for c in countries:
            code = None
            if isinstance(c, dict):
                code = c.get("iso3") or c.get("iso")
            elif isinstance(c, str):
                code = c
            if code and code.upper() in ISO3:
                lat, lon = ISO3[code.upper()]
                return lat, lon
    low = (name or "").lower()
    import re

    m = re.search(r"\bin\s+([a-z][a-z\s]{2,40}?)(?:\s+\d|\s+region|\s+islands|$)", low)
    if m:
        place = m.group(1).strip()
        if place in _COUNTRY_NAMES:
            return _COUNTRY_NAMES[place]
        for hint, (lat, lon) in _NAME_HINTS:
            if hint in place or place in hint:
                return lat, lon
    for hint, (lat, lon) in _NAME_HINTS:
        if hint in low:
            return lat, lon
    for country, (lat, lon) in _COUNTRY_NAMES.items():
        if country in low:
            return lat, lon
    return None, None
