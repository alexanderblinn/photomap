from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class PhotoMeta:
    path: Path
    lat: Optional[float]
    lon: Optional[float]
    datetime: Optional[str]
    make: Optional[str]
    model: Optional[str]
    extra: Dict[str, str]
