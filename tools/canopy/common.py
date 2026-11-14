"""Shared paths and settings for the canopy scenario workflow.

Every numbered script imports this, so the folder layout and the site list
are defined in one place. Works in both the system Python and ArcGIS Pro's.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "tucson-canopy"
WORK = PROJECT / "work"            # git-ignored: lidar, imagery, geodatabases
LIDAR = WORK / "lidar"
CONFIG = json.loads((PROJECT / "sites.json").read_text(encoding="utf-8"))
EPSG = CONFIG["crs_epsg"]
BUFFER = CONFIG["buffer_m"]


def sites(only=None):
    """Site entries from sites.json, optionally just the ids given."""
    out = [s for s in CONFIG["sites"] if not only or s["id"] in only]
    if only and len(out) != len(only):
        known = [s["id"] for s in CONFIG["sites"]]
        raise SystemExit(f"unknown site in {only}; sites.json has {known}")
    return out


def site_dir(site):
    d = WORK / site["id"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_bbox(site):
    """The site's bounding box grown by the buffer, snapped out to whole metres."""
    x0, y0, x1, y1 = site["bbox_utm12n"]
    return (x0 - BUFFER, y0 - BUFFER, x1 + BUFFER, y1 + BUFFER)
