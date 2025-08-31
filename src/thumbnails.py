from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from PIL import Image, UnidentifiedImageError

# Optional HEIC support
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

# Use piexif to preserve Orientation (and other EXIF when possible)
try:
    import piexif
except Exception:
    piexif = None  # we'll still preserve Orientation via PIL if we can

EXIF_ORIENTATION_TAG = 274  # 0th IFD


def _safe_thumb_name(src: Path) -> str:
    h = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:12]
    return f"{src.stem}_{h}.jpg"


def _load_exif_from_jpeg_file(path: Path) -> Optional[dict]:
    """
    For JPEGs, load EXIF dict straight from file (best way to keep tags intact).
    Returns piexif-style dict, or None.
    """
    if not piexif:
        return None
    try:
        return piexif.load(str(path))
    except Exception:
        return None


def _get_orientation_from_image(im: Image.Image) -> Optional[int]:
    try:
        exif = im.getexif()
        if exif:
            ori = exif.get(EXIF_ORIENTATION_TAG)
            if isinstance(ori, int) and 1 <= ori <= 8:
                return ori
    except Exception:
        pass
    return None


def _ensure_orientation_in_exif_dict(
    exif_dict: Optional[dict], orientation: Optional[int]
) -> Optional[bytes]:
    """
    Given a piexif dict (or None) and an orientation int, return exif bytes
    with Orientation preserved. If piexif is missing, returns None.
    """
    if not piexif:
        return None
    try:
        if exif_dict is None:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        if orientation:
            exif_dict["0th"][piexif.ImageIFD.Orientation] = int(orientation)
        return piexif.dump(exif_dict)
    except Exception:
        return None


def make_thumbnails(
    paths: Iterable[Path],
    out_dir: Path,
    size: Tuple[int, int] = (768, 768),  # big thumbs
) -> Dict[Path, str]:
    """
    Create JPEG thumbnails WITHOUT rotating pixels.
    Preserve the original image's EXIF Orientation in the saved thumbnail.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping: Dict[Path, str] = {}

    for p in paths:
        try:
            thumb_name = _safe_thumb_name(p)
            rel = f"thumbs/{thumb_name}"
            dst = out_dir / thumb_name
            if not dst.exists():
                with Image.open(p) as im:
                    # Capture original Orientation before any conversions
                    ori = _get_orientation_from_image(im)

                    # Try to keep the whole EXIF (JPEG only) for best fidelity
                    exif_dict = (
                        _load_exif_from_jpeg_file(p)
                        if p.suffix.lower() in (".jpg", ".jpeg")
                        else None
                    )

                    # Convert after reading EXIF; do NOT exif_transpose
                    if im.mode not in ("RGB", "L"):
                        im = im.convert("RGB")

                    # Resize preserving aspect (no rotation, no transpose)
                    im.thumbnail(size, Image.LANCZOS)

                    # Build exif bytes with Orientation preserved (or None if piexif missing)
                    exif_bytes = _ensure_orientation_in_exif_dict(exif_dict, ori)

                    if exif_bytes:
                        im.save(
                            dst,
                            format="JPEG",
                            quality=85,
                            optimize=True,
                            progressive=True,
                            exif=exif_bytes,
                        )
                    else:
                        # Fallback: try passing through original EXIF if PIL kept it; otherwise save without EXIF
                        pil_exif = im.info.get("exif")
                        if pil_exif:
                            im.save(
                                dst,
                                format="JPEG",
                                quality=85,
                                optimize=True,
                                progressive=True,
                                exif=pil_exif,
                            )
                        else:
                            im.save(
                                dst,
                                format="JPEG",
                                quality=85,
                                optimize=True,
                                progressive=True,
                            )

            mapping[p] = rel

        except (UnidentifiedImageError, OSError, ValueError):
            # Skip unreadable files silently
            continue
        except Exception:
            continue

    return mapping
