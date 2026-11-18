"""Download USGS 3DEP elevation for the country around Lake Powell.

The lake DEM stops just above full pool, so the canyon rims and mesas come
from the USGS 3D Elevation Program service instead: 10 m cells, meters above
NAVD88, in 2,000-pixel tiles covering the scene frame set in common.py.
Tiles already on disk are skipped.

    py -I tools/powell/06_get_context.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import time
from concurrent.futures import ThreadPoolExecutor

import requests

from common import CELL, CONTEXT, CONTEXT_CELL, FRAME_COLS, FRAME_ROWS, FRAME_X0, FRAME_Y1, THREEDEP, USER_AGENT

TILE_PX = 2000          # the server allows more, but smaller tiles fail less often


def tiles():
    """Yield (row, col, bbox, width_px, height_px); row 0 is the north strip."""
    ratio = round(CELL / CONTEXT_CELL)
    cols, rows = FRAME_COLS * ratio, FRAME_ROWS * ratio
    for r, top in enumerate(range(0, rows, TILE_PX)):
        h = min(TILE_PX, rows - top)
        for c, left in enumerate(range(0, cols, TILE_PX)):
            w = min(TILE_PX, cols - left)
            x0 = FRAME_X0 + left * CONTEXT_CELL
            y1 = FRAME_Y1 - top * CONTEXT_CELL
            yield r, c, (x0, y1 - h * CONTEXT_CELL, x0 + w * CONTEXT_CELL, y1), w, h


def tile_path(r, c):
    return CONTEXT / f"3dep_10m_r{r:02d}_c{c:02d}.tif"


def fetch(job):
    r, c, bbox, w, h = job
    path = tile_path(r, c)
    if path.exists() and path.stat().st_size > 10000:
        return f"r{r} c{c}: have it"
    # 26912 (NAD83) is asked for because the service is known to honor it. It
    # differs from the lake DEM's NAD83(2011) by about a meter, far below a 10 m cell.
    params = {"bbox": ",".join(str(v) for v in bbox), "bboxSR": 26912, "imageSR": 26912, "size": f"{w},{h}",
              "format": "tiff", "pixelType": "F32", "noDataInterpretation": "esriNoDataMatchAny",
              "interpolation": "RSP_BilinearInterpolation", "f": "image"}
    for attempt in range(1, 9):     # the USGS servers return 500/502 now and then
        try:
            resp = requests.get(THREEDEP, params=params, headers=USER_AGENT, timeout=180)
            resp.raise_for_status()
            if resp.content[:1] == b"{":
                raise RuntimeError(resp.text[:200])
            part = path.with_name(path.name + ".part")
            part.write_bytes(resp.content)
            part.replace(path)
            return f"r{r} c{c}: {len(resp.content) / 1e6:.1f} MB"
        except Exception as exc:
            if attempt == 8:
                raise
            print(f"  retry {attempt} r{r} c{c}: {exc}", flush=True)
            time.sleep(6 * attempt)


def main():
    CONTEXT.mkdir(parents=True, exist_ok=True)
    jobs = list(tiles())
    print(f"{len(jobs)} tiles of 3DEP elevation at {CONTEXT_CELL:g} m")
    with ThreadPoolExecutor(3) as pool:
        for line in pool.map(fetch, jobs):
            print(" ", line, flush=True)


if __name__ == "__main__":
    main()
