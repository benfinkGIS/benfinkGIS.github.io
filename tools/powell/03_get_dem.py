"""Download the Modified Lake Powell topobathymetric DEM from USGS ScienceBase.

Fetches every file attached to the data release (the 3.2 GB raster zip, the
spatial metadata shapefile and the FGDC metadata record) into
lake-powell/work/raw/tbdem/, checks sizes and MD5 sums where ScienceBase gives
them, then unzips into raw/tbdem/extracted/. Finished files are skipped, and an
interrupted download resumes where it stopped if the server allows it.

    py -I tools/powell/03_get_dem.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hashlib
import json
import shutil
import time
import zipfile

import requests

from common import RAW_DEM, SCIENCEBASE_FILE, SCIENCEBASE_ITEM, SCIENCEBASE_JSON, USER_AGENT


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def download(name, size, dest):
    if dest.exists() and dest.stat().st_size == size:
        print(f"  have {name}")
        return
    part = dest.with_name(dest.name + ".part")
    url = SCIENCEBASE_FILE.format(item=SCIENCEBASE_ITEM)
    for attempt in range(1, 9):
        done = part.stat().st_size if part.exists() else 0
        headers = dict(USER_AGENT)
        if done:
            headers["Range"] = f"bytes={done}-"
        try:
            with requests.get(url, params={"name": name}, headers=headers, stream=True, timeout=120) as r:
                r.raise_for_status()
                if done and r.status_code != 206:     # server ignored the range: start over
                    done = 0
                mode = "ab" if done else "wb"
                t0, last = time.time(), time.time()
                with open(part, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        if time.time() - last > 30:
                            last = time.time()
                            print(f"  {name}: {done / 1e9:.2f} of {size / 1e9:.2f} GB", flush=True)
            if done == size:
                part.replace(dest)
                print(f"  got {name} ({size / 1e6:.0f} MB, {time.time() - t0:.0f} s)")
                return
            print(f"  {name}: stopped at {done} of {size} bytes, retrying ({attempt})", flush=True)
        except requests.RequestException as e:
            print(f"  {name}: {e}, retrying ({attempt})", flush=True)
        time.sleep(10)
    raise SystemExit(f"could not download {name}")


def main():
    RAW_DEM.mkdir(parents=True, exist_ok=True)
    item = requests.get(SCIENCEBASE_JSON.format(item=SCIENCEBASE_ITEM), headers=USER_AGENT, timeout=60).json()
    (RAW_DEM / "sciencebase_item.json").write_text(json.dumps(item, indent=1), encoding="utf-8")
    print(item["title"])
    print(item.get("citation", ""))
    files = [f for link in item["distributionLinks"] for f in link.get("files", [])]
    for f in sorted(files, key=lambda f: f["size"]):
        dest = RAW_DEM / f["name"]
        download(f["name"], f["size"], dest)
        want = (f.get("checksum") or {}).get("value")
        if want:
            got = md5(dest)
            print(f"    md5 {'ok' if got == want else 'MISMATCH: ' + got}")
            if got != want:
                raise SystemExit(f"{f['name']} does not match the ScienceBase checksum")
    out = RAW_DEM / "extracted"
    for z in sorted(RAW_DEM.glob("*.zip")):
        target = out / z.stem
        if target.exists():
            print(f"  already unzipped {z.name}")
            continue
        with zipfile.ZipFile(z) as zf:
            need = sum(i.file_size for i in zf.infolist())
            free = shutil.disk_usage(RAW_DEM).free
            print(f"  {z.name} unzips to {need / 1e9:.1f} GB ({free / 1e9:.0f} GB free)")
            if need > free - 10e9:                      # keep 10 GB spare
                raise SystemExit(f"not enough disk space to unzip {z.name}")
            bad = zf.testzip()
            if bad:
                raise SystemExit(f"{z.name} is damaged at {bad}")
            zf.extractall(target)
        print(f"  unzipped {z.name}: {sum(1 for _ in target.rglob('*'))} entries")


if __name__ == "__main__":
    main()
