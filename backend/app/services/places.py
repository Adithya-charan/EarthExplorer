"""Reference positions for well-known region names.

These are *display* positions only (approximate centre of each region, longitude/latitude in degrees). They are not
observations, not boundaries, and no statistic depends on them. They let a dataset with named regions but no coordinates
be shown as one marker per region. Anything shown from this table is labelled as approximate.
"""

from __future__ import annotations

# India Meteorological Department rainfall subdivisions, approximate centres (lon, lat).
IMD_SUBDIVISION_CENTRES: dict[str, tuple[float, float]] = {
    "andaman & nicobar islands": (92.7, 11.7),
    "arunachal pradesh": (94.7, 28.0),
    "assam & meghalaya": (92.0, 26.0),
    "bihar": (85.6, 25.7),
    "chhattisgarh": (82.0, 21.3),
    "coastal andhra pradesh": (81.0, 16.2),
    "coastal karnataka": (74.8, 13.5),
    "east madhya pradesh": (81.0, 23.5),
    "east rajasthan": (75.5, 26.5),
    "east uttar pradesh": (82.5, 26.3),
    "gangetic west bengal": (87.8, 23.4),
    "gujarat region": (72.2, 22.6),
    "haryana delhi & chandigarh": (76.3, 29.2),
    "himachal pradesh": (77.3, 31.9),
    "jammu & kashmir": (75.5, 34.0),
    "jharkhand": (85.3, 23.6),
    "kerala": (76.4, 10.4),
    "konkan & goa": (73.4, 17.2),
    "lakshadweep": (72.7, 10.6),
    "madhya maharashtra": (74.5, 18.7),
    "matathwada": (76.5, 19.3),
    "marathwada": (76.5, 19.3),
    "naga mani mizo tripura": (93.8, 24.0),
    "north interior karnataka": (76.0, 15.8),
    "orissa": (84.4, 20.5),
    "odisha": (84.4, 20.5),
    "punjab": (75.4, 31.0),
    "rayalseema": (78.2, 14.7),
    "saurashtra & kutch": (70.5, 22.4),
    "south interior karnataka": (76.3, 13.0),
    "sub himalayan west bengal & sikkim": (88.3, 26.9),
    "tamil nadu": (78.4, 11.0),
    "telangana": (79.0, 17.9),
    "uttarakhand": (79.2, 30.2),
    "vidarbha": (78.8, 20.9),
    "west madhya pradesh": (76.6, 23.3),
    "west rajasthan": (72.0, 27.0),
    "west uttar pradesh": (79.0, 28.0),
}

PLACES_NOTE = (
    "Positions are the approximate centre of each named region from a built-in reference table; they are not boundaries and not part of the dataset. "
    "Each marker's colour and height come from that region's own values."
)


def region_centre(name: str) -> tuple[float, float] | None:
    return IMD_SUBDIVISION_CENTRES.get(name.strip().lower())
