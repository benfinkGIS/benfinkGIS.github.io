"""Shared paths and settings for the wash corridor workflow.

Every numbered script imports this, so the folder layout and the study area
are defined in one place. Works in both the system Python and ArcGIS Pro's.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "tucson-washes"
WORK = PROJECT / "work"            # git-ignored: downloads and intermediate files
CONTEXT = WORK / "context"
SIGHTINGS = WORK / "sightings"
CONFIG = json.loads((PROJECT / "study_area.json").read_text(encoding="utf-8"))
EPSG = CONFIG["crs_epsg"]
BBOX = tuple(CONFIG["bbox_utm12n"])          # x0, y0, x1, y1 in metres
SPECIES = CONFIG["species"]
USER_AGENT = {"User-Agent": "wash-corridor-study/0.1"}


def bbox_lonlat():
    """The study box in longitude and latitude, grown to cover its corners."""
    from pyproj import Transformer
    t = Transformer.from_crs(EPSG, 4326, always_xy=True)
    x0, y0, x1, y1 = BBOX
    lons, lats = zip(*(t.transform(x, y) for x in (x0, x1) for y in (y0, y1)))
    return (min(lons), min(lats), max(lons), max(lats))
