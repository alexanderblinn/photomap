from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Fast, header-only EXIF parsing (preferred) ---
import exifread

# --- Pillow fallback (handles HEIC if pillow-heif is installed) ---
from PIL import Image, UnidentifiedImageError
from PIL.ExifTags import GPSTAGS, TAGS

# Optional HEIC support
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

# Avoid DecompressionBomb warnings when Pillow opens very large images
Image.MAX_IMAGE_PIXELS = None
warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)

from geo_utils import dms_to_decimal
from types_ import PhotoMeta


# ---------- Helpers for exifread ----------
def _ratios_to_decimal(parts: List[Any], ref: Optional[str]) -> Optional[float]:
    """
    exifread returns a list like [34/1, 3/1, 30/1].
    Convert to decimal degrees and apply N/S/E/W sign.
    """
    try:
        # exifread Ratio has num/den; str() is like "34/1". Do safe eval:
        def to_float(x):
            s = str(x)
            if "/" in s:
                num, den = s.split("/")
                return float(num) / float(den)
            return float(s)

        deg, minute, second = [to_float(p) for p in parts]
        val = deg + minute / 60.0 + second / 3600.0
        if ref in ("S", "W"):
            val = -val
        return val
    except Exception:
        return None


def _exifread_extract(path: Path) -> Optional[PhotoMeta]:
    """
    Try to read EXIF using exifread without loading image pixels.
    Returns PhotoMeta (lat/lon possibly None). If file unreadable, returns None.
    """
    try:
        with path.open("rb") as f:
            tags = exifread.process_file(f, details=False)

        # GPS tags names in exifread
        lat_vals = tags.get("GPS GPSLatitude")
        lat_ref = str(tags.get("GPS GPSLatitudeRef", "")).strip() or None
        lon_vals = tags.get("GPS GPSLongitude")
        lon_ref = str(tags.get("GPS GPSLongitudeRef", "")).strip() or None

        lat = lon = None
        if lat_vals and lon_vals:
            lat = _ratios_to_decimal(
                list(lat_vals.values)
                if hasattr(lat_vals, "values")
                else list(lat_vals),
                lat_ref,
            )
            lon = _ratios_to_decimal(
                list(lon_vals.values)
                if hasattr(lon_vals, "values")
                else list(lon_vals),
                lon_ref,
            )

        dt = None
        for key in ("EXIF DateTimeOriginal", "Image DateTime"):
            if key in tags:
                dt = str(tags[key])
                break

        make = str(tags.get("Image Make", "")) or None
        model = str(tags.get("Image Model", "")) or None

        return PhotoMeta(
            path=path, lat=lat, lon=lon, datetime=dt, make=make, model=model, extra={}
        )
    except Exception:
        return None


# ---------- Google Takeout / sidecar JSON ----------
def _read_takeout_sidecar(
    path: Path,
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    If Google Takeout JSON exists next to the image, try to read coords & datetime.
    Looks for:
      - geoData{ latitude, longitude }
      - geoDataExif{ latitude, longitude }
      - photoTakenTime{ timestamp } or { formatted }
    """
    # Try common variants: IMG_1234.JPG.json, or IMG_1234.json
    candidates = [
        path.with_suffix(path.suffix + ".json"),
        path.with_suffix(".json"),
    ]
    for c in candidates:
        if not c.exists():
            continue
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
        except Exception:
            continue

        def pick_latlon(d: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
            lat = d.get("latitude")
            lon = d.get("longitude")
            try:
                lat = float(lat) if lat is not None else None
                lon = float(lon) if lon is not None else None
            except Exception:
                lat = lon = None
            return lat, lon

        lat = lon = None
        if isinstance(data, dict):
            for key in ("geoDataExif", "geoData", "location"):
                gd = data.get(key)
                if isinstance(gd, dict):
                    lat, lon = pick_latlon(gd)
                    if lat is not None and lon is not None:
                        break

            dt = None
            ptt = data.get("photoTakenTime")
            if isinstance(ptt, dict):
                dt = ptt.get("formatted") or ptt.get("timestamp")
            else:
                dt = data.get("creationTime") or data.get("creationTimestamp")

            if lat is not None and lon is not None or dt is not None:
                return lat, lon, (str(dt) if dt is not None else None)

    return None, None, None


# ---------- Pillow fallback EXIF ----------
def _pillow_extract(path: Path) -> Optional[PhotoMeta]:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            data: Dict = {}
            if exif:
                for tag_id, val in exif.items():
                    tag = TAGS.get(tag_id, tag_id)
                    data[tag] = val

            gps_info_raw = data.get("GPSInfo", {})
            gps_data = {}
            if gps_info_raw:
                for key in gps_info_raw.keys():
                    name = GPSTAGS.get(key, key)
                    gps_data[name] = gps_info_raw[key]

            lat = lon = None
            if gps_data:
                lat = dms_to_decimal(
                    gps_data.get("GPSLatitude", []), gps_data.get("GPSLatitudeRef")
                )
                lon = dms_to_decimal(
                    gps_data.get("GPSLongitude", []), gps_data.get("GPSLongitudeRef")
                )

            dt = (
                str(data.get("DateTimeOriginal") or data.get("DateTime"))
                if (data.get("DateTimeOriginal") or data.get("DateTime"))
                else None
            )
            make = str(data.get("Make")) if data.get("Make") else None
            model = str(data.get("Model")) if data.get("Model") else None

            extra = {}
            if gps_data.get("GPSAltitude") is not None:
                try:
                    num, den = gps_data["GPSAltitude"]
                    extra["altitude_m"] = str(num / den)
                except Exception:
                    pass

            return PhotoMeta(
                path=path,
                lat=lat,
                lon=lon,
                datetime=dt,
                make=make,
                model=model,
                extra=extra,
            )
    except UnidentifiedImageError:
        return None
    except Exception:
        return None


def _drop_if_zero_coord(
    lat: Optional[float], lon: Optional[float]
) -> Tuple[Optional[float], Optional[float]]:
    """
    Treat (0,0) as invalid GPS and drop it.
    Using a tiny epsilon to avoid float noise.
    """
    if lat is None or lon is None:
        return lat, lon
    if abs(lat) < 1e-9 and abs(lon) < 1e-9:
        return None, None
    return lat, lon


def read_photo_meta(path: Path) -> PhotoMeta:
    """
    Strategy:
      1) exifread (fast, safe)
      2) Google Takeout sidecar JSON
      3) Pillow fallback (including HEIC if plugin registered)
    """
    # 1) exifread
    m = _exifread_extract(path)
    lat = m.lat if m else None
    lon = m.lon if m else None
    dt = m.datetime if m else None
    make = m.make if m else None
    model = m.model if m else None
    extra: Dict[str, str] = {}

    # 2) sidecar JSON (fill gaps; prefer EXIF coords if present)
    s_lat, s_lon, s_dt = _read_takeout_sidecar(path)
    if lat is None and s_lat is not None:
        lat = s_lat
    if lon is None and s_lon is not None:
        lon = s_lon
    if dt is None and s_dt is not None:
        dt = s_dt

    # If we still have nothing meaningful, try Pillow
    if (lat is None or lon is None) and (m is None):
        pm = _pillow_extract(path)
        if pm:
            if lat is None:
                lat = pm.lat
            if lon is None:
                lon = pm.lon
            if dt is None:
                dt = pm.datetime
            if make is None:
                make = pm.make
            if model is None:
                model = pm.model
            extra.update(pm.extra or {})

    lat, lon = _drop_if_zero_coord(lat, lon)

    return PhotoMeta(
        path=path, lat=lat, lon=lon, datetime=dt, make=make, model=model, extra=extra
    )
