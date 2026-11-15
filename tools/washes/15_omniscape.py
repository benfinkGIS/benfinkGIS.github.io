"""Step 8c: run Omniscape on each species' surfaces.

Omniscape moves a circular window across the grid. At each stop it injects
current at every source cell in the window, in proportion to its source
strength, and draws it out at the centre; the current through each cell,
summed over all stops, is the output. Run with resistance 1 everywhere, the
same sum is the "flow potential"; current divided by flow potential shows
where the ground concentrates or blocks movement.

Needs Julia with the Omniscape package (tools/washes/julia/Project.toml).
Radius and block size per species come from tucson-washes/resistance.json.

Run:  py tools/washes/15_omniscape.py [run ...]     (default: every run)
      set JULIA to the julia executable if it is not on PATH
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from common import PROJECT, ROOT, WORK

OUT = WORK / "connectivity"
P = json.loads((PROJECT / "resistance.json").read_text(encoding="utf-8"))
# run name: (species settings, resistance surface, source surface). The two
# bobcat variants bracket the typed culverts (all useless, all as good as a
# bridge); they are compared with each other, at a coarser step to save time.
RUNS = {
    "bobcat": ("bobcat", "bobcat_resistance.tif", "bobcat_source.tif"),
    "flycatcher": ("flycatcher", "flycatcher_resistance.tif", "flycatcher_source.tif"),
    "queen": ("queen", "queen_resistance.tif", "queen_source.tif"),
    "bobcat_closed": ("bobcat", "bobcat_closed_resistance.tif", "bobcat_source.tif"),
    "bobcat_open": ("bobcat", "bobcat_open_resistance.tif", "bobcat_source.tif"),
}
VARIANTS = ("bobcat_closed", "bobcat_open")
THREADS = str(max(1, (os.cpu_count() or 2) - 2))


def julia():
    exe = os.environ.get("JULIA") or shutil.which("julia")
    if not exe:
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Julia"
        found = sorted(local.glob("julia-*/bin/julia.exe"))
        exe = str(found[-1]) if found else None
    if not exe:
        raise SystemExit("Julia not found: install it, or set JULIA to julia.exe")
    return exe


def run(name):
    species, resistance, source = RUNS[name]
    p = P[species]
    block = p["variant_block"] if name in VARIANTS else p["block"]
    folder = OUT / f"run_{name}"
    if folder.exists():
        shutil.rmtree(folder)
    ini = OUT / f"{name}.ini"
    ini.write_text("\n".join([
        "[Required]",
        f"resistance_file = {(OUT / resistance).as_posix()}",
        f"source_file = {(OUT / source).as_posix()}",
        f"radius = {round(p['radius_m'] / P['cell_m'])}",
        f"block_size = {block}",
        f"project_name = {folder.as_posix()}",
        "",
        "[General options]",
        "source_from_resistance = false",
        "calc_normalized_current = true",
        "calc_flow_potential = true",
        "parallelize = true",
        "parallel_batch_size = 20",
        "solver = cg+amg",        # double precision: single fails the solver's accuracy check
        "",
        "[Output options]",
        "write_raw_currmap = true",
        ""]))
    t = time.time()
    code = 'using Omniscape; run_omniscape(ARGS[1])'
    env = dict(os.environ, JULIA_NUM_THREADS=THREADS)
    subprocess.run([julia(), f"--project={ROOT / 'tools' / 'washes' / 'julia'}", "-e", code, str(ini)],
                   check=True, env=env)
    took = round((time.time() - t) / 60, 1)
    print(name, "done in", took, "min", flush=True)
    return dict(radius_m=p["radius_m"], block=block, minutes=took, threads=int(THREADS))


def main():
    names = sys.argv[1:] or list(RUNS)
    log_path = OUT / "runs.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else {}
    for name in names:
        log[name] = run(name)
        log_path.write_text(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
