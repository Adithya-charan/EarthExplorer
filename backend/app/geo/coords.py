"""Parsing and validating user-entered coordinates (WGS84 latitude / longitude)."""

from __future__ import annotations

import math
import re

from app.errors import AppError

_SYMBOLS = str.maketrans({"′": "'", "’": "'", "‘": "'", "″": '"', "”": '"', "“": '"', "º": "°", "˚": "°", "–": "-", "−": "-"})

# 34.05, -118.25   |   34.05N 118.25W   |   N 34.05 W 118.25   |   geo:34.05,-118.25
_NUM = r"[+-]?\d+(?:\.\d+)?"
_DEC_SUFFIX = re.compile(
    rf"^\s*({_NUM})\s*°?\s*([NSns])?\s*[,;/\s]\s*({_NUM})\s*°?\s*([EWew])?\s*$"
)
_DEC_PREFIX = re.compile(
    rf"^\s*([NSns])\s*({_NUM})\s*°?\s*[,;/\s]?\s*([EWew])\s*({_NUM})\s*°?\s*$"
)
# 40°26'46"N 79°58'56"W   |   40 26 46 N, 79 58 56 W   |   40°26.767'N 79°58.933'W
_DMS = re.compile(
    r"^\s*(\d{1,3})\s*[°\s]\s*(\d{1,2}(?:\.\d+)?)?\s*'?\s*(\d{1,2}(?:\.\d+)?)?\s*\"?\s*([NSns])\s*[,;/\s]?\s*"
    r"(\d{1,3})\s*[°\s]\s*(\d{1,2}(?:\.\d+)?)?\s*'?\s*(\d{1,2}(?:\.\d+)?)?\s*\"?\s*([EWew])\s*$"
)
_ONLY_COORD_CHARS = re.compile(r"^[\d\s.,;:/+\-°'\"NSEWnsew]+$")


def looks_like_coordinates(text: str) -> bool:
    """True when the text is made only of the characters coordinates are written with."""
    s = text.strip().translate(_SYMBOLS)
    if s.lower().startswith("geo:"):
        return True
    return bool(s) and bool(_ONLY_COORD_CHARS.match(s)) and sum(c.isdigit() for c in s) >= 2


def _dms(deg: str, minutes: str | None, seconds: str | None, hemi: str) -> float:
    value = float(deg) + float(minutes or 0) / 60 + float(seconds or 0) / 3600
    return -value if hemi.upper() in ("S", "W") else value


def validate_latlon(lat: float, lon: float) -> tuple[float, float]:
    """Raise a 422 ``invalid_coordinates`` error unless lat/lon are finite and in range."""
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise AppError(422, "invalid_coordinates", "Latitude and longitude must be finite numbers.")
    if not -90.0 <= lat <= 90.0:
        raise AppError(422, "invalid_coordinates", f"Latitude {lat:g} is outside -90 to 90 degrees.")
    if not -180.0 <= lon <= 180.0:
        raise AppError(
            422,
            "invalid_coordinates",
            f"Longitude {lon:g} is outside -180 to 180 degrees (use negative values for degrees west).",
        )
    return lat, lon


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Parse text such as ``34.05, -118.25`` or ``40°26'46"N 79°58'56"W``.

    Returns ``None`` when the text is not coordinate-shaped (so it can be treated as a place name) and raises
    ``AppError(422, 'invalid_coordinates')`` when it *is* coordinate-shaped but out of range or inconsistent.
    """
    if not looks_like_coordinates(text):
        return None
    s = text.strip().translate(_SYMBOLS)
    if s.lower().startswith("geo:"):
        s = s[4:]
        s = s.split(";", 1)[0]  # drop uncertainty parameters such as ;u=35

    lat: float
    lon: float
    if m := _DMS.match(s):
        lat = _dms(m.group(1), m.group(2), m.group(3), m.group(4))
        lon = _dms(m.group(5), m.group(6), m.group(7), m.group(8))
        if float(m.group(2) or 0) >= 60 or float(m.group(3) or 0) >= 60 or float(m.group(6) or 0) >= 60 or float(m.group(7) or 0) >= 60:
            raise AppError(422, "invalid_coordinates", "Minutes and seconds must be below 60.")
    elif m := _DEC_PREFIX.match(s):
        lat = float(m.group(2)) * (-1 if m.group(1).upper() == "S" else 1)
        lon = float(m.group(4)) * (-1 if m.group(3).upper() == "W" else 1)
    elif m := _DEC_SUFFIX.match(s):
        lat = float(m.group(1))
        lon = float(m.group(3))
        if m.group(2) and m.group(2).upper() == "S":
            lat = -abs(lat)
        if m.group(4) and m.group(4).upper() == "W":
            lon = -abs(lon)
    else:
        return None
    return validate_latlon(lat, lon)


def format_coordinates(lat: float, lon: float, decimals: int = 4) -> str:
    """'48.8583°N, 2.2945°E' - hemisphere letters instead of signs."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.{decimals}f}°{ns}, {abs(lon):.{decimals}f}°{ew}"


def coordinate_id(lat: float, lon: float) -> str:
    return f"coord:{lat:.6f},{lon:.6f}"


_COORD_ID = re.compile(rf"^coord:({_NUM}),({_NUM})$")


def parse_coordinate_id(location_id: str) -> tuple[float, float] | None:
    m = _COORD_ID.match(location_id)
    if not m:
        return None
    return validate_latlon(float(m.group(1)), float(m.group(2)))
