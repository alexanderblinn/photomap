from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from types_ import PhotoMeta


def _safe_rel(from_dir: Path, file_path: Path) -> Optional[str]:
    """
    Compute a browser-friendly relative path from the HTML output directory
    to the original image. Allow '../' since img/ is typically a sibling of output/.
    """
    try:
        rel = os.path.relpath(file_path, start=from_dir)
        return rel.replace("\\", "/")
    except Exception:
        return None


class PhotoRepository:
    """Single-responsibility: store & export PhotoMeta records."""

    def __init__(self):
        self._items: List[PhotoMeta] = []
        self._skipped: List[Path] = []

    def add(self, meta: PhotoMeta):
        self._items.append(meta)

    def skip(self, path: Path):
        self._skipped.append(path)

    def items(self) -> List[PhotoMeta]:
        return list(self._items)

    def points(self) -> List[Tuple[float, float]]:
        return [
            (m.lat, m.lon)
            for m in self._items
            if m.lat is not None and m.lon is not None
        ]

    def to_geojson(self, out_html_path: Path, thumbs: Dict[Path, str] | None = None):
        """
        out_html_path = full path to output HTML (e.g., output/map.html).
        We compute img_rel relative to out_html_path.parent so that the HTML can load originals if needed.
        """
        features = []
        html_dir = out_html_path.parent

        for m in self._items:
            if m.lat is None or m.lon is None:
                continue

            # Prefer thumbnail if available; also add a safe relative original path as fallback
            thumb_rel = thumbs.get(m.path) if thumbs else None
            img_rel = _safe_rel(html_dir, m.path)

            props: Dict[str, Optional[str]] = {
                "path": str(m.path.name),  # short name for UI/tooltips
                "datetime": m.datetime,
                "make": m.make,
                "model": m.model,
                **m.extra,
                "thumb": thumb_rel,
                "img_rel": img_rel,
            }

            feat = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [m.lon, m.lat]},
                "properties": props,
            }
            features.append(feat)

        geo = {"type": "FeatureCollection", "features": features}
        # Write next to HTML (photos.geojson)
        (out_html_path.parent / "photos.geojson").write_text(
            json.dumps(geo, indent=2), encoding="utf-8"
        )

    def to_csv(self, out_path: Path):
        rows = []
        for m in self._items:
            rows.append(
                {
                    "path": str(m.path),
                    "lat": m.lat,
                    "lon": m.lon,
                    "datetime": m.datetime,
                    "make": m.make,
                    "model": m.model,
                    **m.extra,
                }
            )
        df = pd.DataFrame(rows)
        df.to_csv(out_path, index=False)

    def write_reports(self, out_html_path: Path, thumbs: Dict[Path, str] | None = None):
        out_dir = out_html_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        self.to_geojson(out_html_path, thumbs=thumbs)
        self.to_csv(out_dir / "photos.csv")
        (out_dir / "skipped.txt").write_text(
            "\n".join(map(str, self._skipped)), encoding="utf-8"
        )
