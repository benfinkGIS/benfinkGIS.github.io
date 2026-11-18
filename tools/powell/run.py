"""Run the Lake Powell drawdown pipeline from raw downloads to the finished video.

    py tools/powell/run.py              every step that exists so far
    py tools/powell/run.py --from 3     start at step 3
    py tools/powell/run.py --only 2     one step

Each step is a script in this folder. Steps that download skip files they
already have, so a second run is quick. The run ends with the year-slider
page's pictures and data in lake-powell/. The continuous video (keyframed
water, overlay, encode) is still to come.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

BLENDER_EXE = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
YEARLY = str(HERE.parents[1] / "lake-powell" / "work" / "processed" / "levels_yearly.csv")

# number, script, arguments, what it does. Scripts named *_blender_* run inside Blender.
STEPS = [
    (1, "01_get_levels.py", [], "Download Reclamation's daily elevation and storage"),
    (2, "02_plot_levels.py", [], "Draw the elevation check chart"),
    (3, "03_get_dem.py", [], "Download and unzip the USGS Modified topobathymetric DEM"),
    (4, "04_inspect_dem.py", ["--preview"], "Report the DEM's coordinate system and draw a preview"),
    (5, "05_datum.py", [], "Record the NGVD29 to NAVD88 conversion and fetch the USGS capacity table"),
    (6, "06_get_context.py", [], "Download USGS 3DEP terrain around the lake"),
    (7, "07_build_terrain.py", [], "Merge the lake DEM and 3DEP into the 30 m whole-lake terrain"),
    (8, "09_yearly_levels.py", [], "Make the one-row-per-year level table"),
    (9, "10_check_landsat.py", [], "Check the modeled shoreline against Landsat on two days"),
    (10, "08_blender_scene.py", ["--view", "dam", "--levels", YEARLY], "Render one picture per year in Blender"),
    (11, "11_publish_slider.py", ["--view", "dam"], "Write the slider page's pictures and data"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--only", type=int)
    args = ap.parse_args()
    for number, script, extra, what in STEPS:
        if args.only is not None and number != args.only:
            continue
        if args.only is None and number < args.start:
            continue
        print(f"\n=== {number}. {what} ===", flush=True)
        t0 = time.time()
        # -I keeps Python from importing anything out of the working folder or the downloads
        if "blender" in script:
            command = [BLENDER_EXE, "-b", "--factory-startup", "-P", str(HERE / script), "--", *extra]
        else:
            command = [sys.executable, "-I", str(HERE / script), *extra]
        result = subprocess.run(command)
        if result.returncode:
            raise SystemExit(f"step {number} ({script}) failed")
        print(f"    done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
