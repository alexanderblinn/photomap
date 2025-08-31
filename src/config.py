from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class MapStyle:
    # default basemap to show on load (must exist in BASEMAPS keys below)
    default: str = "CartoDB Positron"


# Common, attribution-compliant XYZ sources.
# NOTE: Respect providers’ terms & attribution.
BASEMAPS: Dict[str, Dict] = {
    "CartoDB Positron": {
        "url": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "attr": "&copy; OpenStreetMap contributors &copy; CARTO",
        "subdomains": "abcd",
        "max_zoom": 20,
    },
    "CartoDB Dark Matter": {
        "url": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "attr": "&copy; OpenStreetMap contributors &copy; CARTO",
        "subdomains": "abcd",
        "max_zoom": 20,
    },
    "OpenStreetMap": {
        "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attr": "&copy; OpenStreetMap contributors",
        "subdomains": "abc",
        "max_zoom": 19,
    },
    "Esri WorldImagery (Satellite)": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
        "max_zoom": 20,
    },
}


@dataclass(frozen=True)
class AppConfig:
    recurse: bool = True
    allowed_exts: tuple = (".jpg", ".jpeg", ".png", ".heic", ".heif")
    # Heatmap settings
    heat_min_opacity: float = 0.55
    heat_radius: int = 16
    heat_blur: int = 10
    heat_max_zoom: int = 18
    # Marker settings
    point_radius: int = 6
    cluster: bool = True
    include_heat: bool = True
    # Default map view
    default_zoom_start: int = 2
    map_style: MapStyle = MapStyle()
