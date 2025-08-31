from typing import Iterable, List, Optional, Tuple


def dms_to_decimal(
    dms: Iterable[Tuple[float, float]], ref: Optional[str]
) -> Optional[float]:
    """Convert EXIF DMS to decimal degrees. dms is iterable of rationals (num, den)."""
    try:
        d = [n / d for n, d in dms]  # degrees, minutes, seconds
        deg = d[0] + d[1] / 60 + d[2] / 3600
        if ref in ("S", "W"):
            deg = -deg
        return deg
    except Exception:
        return None


def bounds_from_points(points: List[Tuple[float, float]]):
    if not points:
        return None
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return (min(lats), min(lons), max(lats), max(lons))
