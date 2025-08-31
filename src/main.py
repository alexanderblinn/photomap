from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import AppConfig
from data_store import PhotoRepository
from exif_loader import read_photo_meta
from map_builder import MapBuilder
from thumbnails import make_thumbnails


def scan_images(images_dir: Path, allowed_exts, recurse=True, limit: int = 0):
    count = 0
    it = images_dir.rglob("*") if recurse else images_dir.glob("*")
    for p in it:
        if p.is_file() and p.suffix.lower() in allowed_exts:
            yield p
            count += 1
            if limit and count >= limit:
                break


def generate_demo_points(n: int = 1000):
    import random

    pts = []
    clusters = [(48.85, 2.35), (40.71, -74.01), (34.05, -118.24), (35.68, 139.69)]
    for _ in range(n):
        base = random.choice(clusters)
        lat = base[0] + random.uniform(-1.5, 1.5)
        lon = base[1] + random.uniform(-1.5, 1.5)
        pts.append((lat, lon))
    return pts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Photo map with viewport gallery")
    parser.add_argument(
        "--images", type=str, default="./img", help="Folder containing photos"
    )
    parser.add_argument(
        "--out", type=str, default="./output/map.html", help="Output HTML path"
    )
    parser.add_argument(
        "--point-radius", type=int, default=6, help="Circle marker radius"
    )
    parser.add_argument(
        "--cluster",
        dest="cluster",
        action="store_true",
        default=True,
        help="Enable clustering",
    )
    parser.add_argument(
        "--no-cluster", dest="cluster", action="store_false", help="Disable clustering"
    )
    parser.add_argument(
        "--include-heat",
        dest="include_heat",
        action="store_true",
        default=True,
        help="Include heatmap layer",
    )
    parser.add_argument(
        "--no-include-heat",
        dest="include_heat",
        action="store_false",
        help="Exclude heatmap layer",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Limit photos processed (0=no limit)"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Generate a map with synthetic points (no photos)",
    )
    args = parser.parse_args(argv)

    cfg = AppConfig(
        point_radius=args.point_radius,
        cluster=args.cluster,
        include_heat=args.include_heat,
    )  # type: ignore
    out_html = Path(args.out)
    out_dir = out_html.parent
    images_dir = Path(args.images)

    if args.demo:
        pts = generate_demo_points()
        features = []
        for i, (lat, lon) in enumerate(pts, 1):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "path": f"demo/photo_{i:05d}.jpg",
                        "datetime": None,
                        "make": None,
                        "model": None,
                        "thumb": None,
                        "img_rel": None,
                    },
                }
            )
        gj = {"type": "FeatureCollection", "features": features}
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "photos.geojson").write_text(json.dumps(gj), encoding="utf-8")
        mb = MapBuilder(default_zoom_start=cfg.default_zoom_start)
        mb.build_map(
            points=pts,
            geojson_file=out_dir / "photos.geojson",
            out_html=out_html,
            include_heat=cfg.include_heat,
            heat_min_opacity=cfg.heat_min_opacity,
            heat_radius=cfg.heat_radius,
            heat_blur=cfg.heat_blur,
            heat_max_zoom=cfg.heat_max_zoom,
            cluster=cfg.cluster,
            point_radius=cfg.point_radius,
        )
        print(f"Demo map written to {out_html}")
        return 0

    if not images_dir.exists():
        print(f"Images directory not found: {images_dir}", file=sys.stderr)
        return 2

    repo = PhotoRepository()
    total, with_gps, without_gps = 0, 0, 0
    for p in scan_images(images_dir, cfg.allowed_exts, cfg.recurse, limit=args.limit):
        total += 1
        m = read_photo_meta(p)
        if m.lat is None or m.lon is None:
            repo.skip(p)
            without_gps += 1
            if args.verbose:
                print(f"NO GPS: {p}")
        else:
            with_gps += 1
            if args.verbose:
                print(f"OK: {p} -> ({m.lat:.6f},{m.lon:.6f})")
        repo.add(m)

    out_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir = out_dir / "thumbs"
    gps_paths = [
        m.path for m in repo.items() if m.lat is not None and m.lon is not None
    ]
    thumb_map = make_thumbnails(gps_paths, thumbs_dir, size=(256, 256))

    # Write reports (GeoJSON next to HTML; includes thumb + img_rel)
    repo.write_reports(out_html, thumbs=thumb_map)

    # Build the map
    pts = repo.points()
    mb = MapBuilder(default_zoom_start=cfg.default_zoom_start)
    mb.build_map(
        points=pts,
        geojson_file=out_dir / "photos.geojson",
        out_html=out_html,
        include_heat=cfg.include_heat,
        heat_min_opacity=cfg.heat_min_opacity,
        heat_radius=cfg.heat_radius,
        heat_blur=cfg.heat_blur,
        heat_max_zoom=cfg.heat_max_zoom,
        cluster=cfg.cluster,
        point_radius=cfg.point_radius,
    )

    print(f"Scanned: {total}, With GPS: {with_gps}, Without GPS: {without_gps}")
    print(f"Map written to {out_html}")
    print(f"CSV/GeoJSON written to {out_dir}")
    print(f"Skipped list at {out_dir / 'skipped.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
