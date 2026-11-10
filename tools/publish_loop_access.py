#!/usr/bin/env python3
"""Copy the Loop access results into the site folder the project pages read.

Usage (from the repo root, after build_loop.py, build_network.py, build_access.py and
test_segments.py):
    py tools/publish_loop_access.py

The build scripts write their working files to tools/loop-review/. The pages under
/tucson-loop-access/ read only what this script puts in tucson-loop-access/data/:

    access.json    residents by ride time: bands, communities, map cells
    segments.json  candidate new segments and the combined build-outs
    loop.json      the draft Loop as plain lines, thinned for drawing

Nothing is recomputed here, so the site shows exactly what the last build produced.
"""
import json
from pathlib import Path

from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "loop-review"
DST = ROOT / "tucson-loop-access" / "data"
THIN_DEG = 0.00004            # about 4 m: invisible at the zooms the map allows


def main():
    DST.mkdir(parents=True, exist_ok=True)
    for name in ("access.json", "segments.json"):
        data = json.loads((SRC / name).read_text(encoding="utf-8"))
        (DST / name).write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        print("%-14s %7.0f KB" % (name, (DST / name).stat().st_size / 1024))

    loop = json.loads((SRC / "loop_draft.geojson").read_text(encoding="utf-8"))
    lines = []
    for f in loop["features"]:
        thin = LineString(f["geometry"]["coordinates"]).simplify(THIN_DEG)
        lines.append([[round(x, 5), round(y, 5)] for x, y in thin.coords])
    out = {"miles": loop["metadata"]["miles_total"], "generated": loop["metadata"]["generated"], "lines": lines}
    (DST / "loop.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print("%-14s %7.0f KB  (%d lines, %s mi)" % ("loop.json", (DST / "loop.json").stat().st_size / 1024, len(lines), out["miles"]))


if __name__ == "__main__":
    main()
