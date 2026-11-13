# Fink Geospatial

Portfolio and sandbox site for Fink Geospatial: personal GIS projects. Published with GitHub Pages at <https://finkgeo.com>.

Plain HTML and CSS, no build step. Edit a file, commit, push, and Pages redeploys.

## Layout

| Path | What it is |
| --- | --- |
| `index.html` | Home page, with the About, Projects, and Contact sections |
| `tucson-golf-water/index.html` | Tucson golf course water map page: satellite map, course list, data notes |
| `tucson-golf-water/map.js` | Map code (Leaflet). Loads the GeoJSON and wires up the toolbar, popups and course list |
| `tucson-golf-water/data/courses.geojson` | Active course boundaries, built from OpenStreetMap by `tools/build_courses.py` |
| `tools/build_courses.py` | Refreshes `courses.geojson` (needs Python and `pip install shapely`). Not used by the site at runtime |
| `tools/pima_golf_water_memo.json` | The Pima County water-use table, typed from the memo (see below). `build_courses.py` merges it into the GeoJSON |
| `tucson-loop-access/index.html` | Tucson Loop Access, page 1: who lives far from The Loop (headline figures, split bar, map, communities) |
| `tucson-loop-access/grow/index.html` | Tucson Loop Access, page 2: where The Loop could grow (candidate segments and combined build-outs) |
| `tucson-loop-access/loop.js`, `loop.css` | Charts and map for both Loop pages (Leaflet), in the site's look |
| `tucson-loop-access/data/*.json` | What the Loop pages read. Written by `tools/publish_loop_access.py`; don't edit by hand |
| `tools/build_loop.py`, `build_network.py`, `build_access.py`, `test_segments.py`, `publish_loop_access.py` | The Loop analysis, run in that order (see below). Not used by the site at runtime |
| `tucson-loop-beer/index.html` | A Beer Off The Loop: places licensed to pour within a short ride of The Loop (map, list, long-way-round table) |
| `tucson-loop-beer/beer.js`, `beer.css` | Map and list for that page (Leaflet). Also loads `tucson-loop-access/loop.css` and `data/loop.json` |
| `tucson-loop-beer/data/spots.json` | What the page reads. Written by `tools/build_loop_beer.py`; don't edit by hand |
| `tools/build_loop_beer.py`, `loop_beer_edits.json` | Builds `spots.json` from the state liquor licence list and the Loop network (see below). The JSON file holds hand edits: places to drop, re-class or move |
| `catalinas-3d/index.html` | Santa Catalinas 3D page: the interactive model, two rendered stills, data notes |
| `catalinas-3d/viewer.js`, `catalinas.css` | The 3D viewer (three.js). Lifts a flat grid from the height image and works out light and shadows in the shader |
| `catalinas-3d/data/` | What the viewer loads: `height.png`, `texture_4k.jpg`, `texture_8k.jpg`, `meta.json`. Written by `tools/export_catalinas_web.py`; don't edit by hand |
| `catalinas-3d/img/` | Stills rendered in Blender |
| `tools/build_catalinas.py`, `deshade_catalinas.py`, `blender_catalinas.py`, `export_catalinas_web.py` | The Catalinas model pipeline (see below). Not used by the site at runtime |
| `kit-fox-release/index.html` | Kit Fox Release Sites page: the step-by-step wizard, weight sliders, shortlist table, data notes |
| `kit-fox-release/kitfox.js`, `kitfox.css` | The wizard and map (Leaflet). Recomputes the weighted score in the browser when a weight changes |
| `kit-fox-release/data/` | What the page reads: `crit1.png` to `crit3.png` (the eight criterion scores) and `model.json`. Written by `tools/publish_kitfox.py`; don't edit by hand |
| `tools/build_kitfox_shortlist.py`, `publish_kitfox.py` | The kit fox shortlist and page data (see below). Not used by the site at runtime |
| `tools/kitfox-review/` | Local review map of the shortlisted areas at full detail. Git-ignored on purpose: never publish it |
| `kxci-signal/index.html` | KXCI Signal Reach page: headline counts, signal map, town table, data notes |
| `kxci-signal/kxci.js`, `kxci.css` | The map (Leaflet), figures and tables. Colours the signal layer in the browser from `data/field.png` |
| `kxci-signal/data/` | What the page reads: `kxci.json` (licence, counts, contours) and `field.png` (the modelled field as a data image). Written by `tools/publish_kxci.py`; don't edit by hand |
| `kxci-signal/kxci-reach.png` | Static map, also written by `tools/publish_kxci.py` |
| `tools/build_kxci.py`, `model_kxci_terrain.py`, `publish_kxci.py`, `kxci_drive_logger.py` | The KXCI pipeline and the drive-test logger (see below). Not used by the site at runtime |
| `tools/loop-review/` | Working pages for checking the Loop analysis (a satellite review map and a plain draft of the charts). Marked noindex; not linked from the site |
| `404.html` | Not-found page |
| `assets/style.css` | Shared styles (late-90s desktop look; plain CSS, no web fonts) |
| `assets/*.svg` | Pixel-style icons. `globe.svg` doubles as the favicon. |
| `CNAME` | Tells GitHub Pages the custom domain (`finkgeo.com`). Don't delete it. |
| `.nojekyll` | Tells Pages to serve the files as-is, skipping Jekyll |

## TODO

- Replace the About placeholder text in `index.html` (search for `TODO`).
- Tucson golf map: water use is in popups and the table only. Next: map layers (for example colour by supply, size by use).
- Tucson Loop Access: check the draft Loop extent section by section (use `tools/loop-review/`), then count traffic stress in the ride times.
- Santa Catalinas 3D: close-up views from 1 m lidar; roads, trails and canyon names; test touch gestures on a real phone.
- Kit Fox Release Sites: the center is left unnamed until they agree (keep its name out of the page, the scripts and this file); say what the soil score is based on (`TODO` in `kitfox.js`); decide whether wilderness and monument land should be screened out of the shortlist.
- KXCI Signal Reach: run drive tests with `tools/kxci_drive_logger.py` (not yet tried on a real dongle), then compare measured signal with the two predictions.
- Bump the "Last updated" date in each page footer when content changes.

## Refreshing the golf course data

```
py tools/build_courses.py
```

This queries OpenStreetMap (Overpass API, which is sometimes busy; the script retries) for golf courses
inside Pima County and rewrites `tucson-golf-water/data/courses.geojson`. OpenStreetMap does not mark closed courses here, so
the script keeps a hand-maintained list of closed courses to leave out (`EXCLUDE_CLOSED`). Re-check
that list on each refresh, and update the "Data sources and methods" text on the page if it changes.

## Refreshing the Loop access data

```
py tools/build_loop.py
py tools/build_network.py
py tools/build_access.py
py tools/test_segments.py
py tools/publish_loop_access.py
```

Needs Python with numpy, scipy and shapely. In order, these assemble a draft extent of The Loop from
OpenStreetMap, build the street-and-path network and attach 2020 Census blocks to it, summarise residents
by ride time, score candidate new segments, and copy the results into `tucson-loop-access/data/`.
Downloads are cached in the system temp folder (`finkgeo_loop_cache`), and the network itself is kept
there, not in the repo. If the main Overpass servers are down, pass
`--server https://overpass.openstreetmap.fr/api/interpreter` to the first, second and fourth scripts;
that server's copy of the map can be weeks old.

The numbers are a first cut: ride times ignore traffic, the Loop extent is a draft, and candidate
segments get generous entrances. Each script's header says what it assumes. If a rebuild changes the
picture, re-read the two notes boxes on the pages, which describe the 20-minute results in words.

## Refreshing the Loop beer stops

```
py tools/build_loop_beer.py --refresh
```

Run it after the Loop access scripts above, because it reuses their network (`network.npz` in the temp
cache) and the draft Loop. It downloads the City of Tucson's "Liquor License - Active" layer (the state
licence list for Pima County, read-only queries, business name and address only, never the licensee
names), keeps the licences to pour on the premises, tidies the names against OpenStreetMap, and works
out the ride from the Loop to each place. The licence points are the City's geocoding and a few are
wrong: the script moves the ones OpenStreetMap can vouch for and lists every move in `spots.json`.
Fix the rest, drop closed places, or change a place's kind in `tools/loop_beer_edits.json`.

## Water-use data

The per-course water figures in the popups come from one public record: the Pima County memo
"Water Use by Golf Courses in Pima County Based on 2023 Reporting" (County Administrator to the Board
of Supervisors, 26 December 2024). Its attachment table is transcribed in `tools/pima_golf_water_memo.json`,
with each row's reporting year. `WATER_MATCH` and `NO_WATER` in `build_courses.py` say which memo rows
belong to which mapped course, and the script refuses to run if a mapped course has no decision.

Not used on purpose: ADWR's Industrial "Source Data" query has newer and more detailed per-facility
records (turf acres, allotments, later years), but ADWR's data disclaimer
(<https://www.azwater.gov/ama/ama-data>) asks that its data not be passed on for re-use and says to
request copies from the department. Get ADWR's OK (earp@azwater.gov) before publishing any of it.

When the county publishes a newer memo, add its rows to the JSON and re-run the build.

## Rebuilding the Santa Catalinas 3D model

Needs Python with `numpy`, `scipy`, `pillow`, `pyproj` and `matplotlib`, and Blender (built with 5.2)
for the stills. The big working files go to `catalinas-3d/work/`, which is not in the repository
(about 2 GB).

```
py tools/build_catalinas.py          # USGS elevation (10 m) and NAIP imagery (4 m) for a 46 x 42 km frame
py tools/deshade_catalinas.py        # takes the photos' own sunlight out of the imagery
blender -b --factory-startup -P tools/blender_catalinas.py -- --view front --sun-el 7 --haze 150
blender -b --factory-startup -P tools/blender_catalinas.py -- --view south --sun-el 7 --exposure -2.8
py tools/export_catalinas_web.py     # writes catalinas-3d/data/ for the viewer
```

- The USGS image servers time out on large requests, so the build script asks for 2000-pixel tiles
  and retries. Tiles are cached in `catalinas-3d/work/tiles/`.
- The aerial photos were flown at different times, so there is no single sun direction to remove.
  `deshade_catalinas.py` fits brightness against slope direction in a moving window instead, and
  recolours fully shadowed slopes from the sunlit ground beside them. Its docstring lists the limits.
- `blender_catalinas.py --draft` renders a quick look in a few seconds. The stills in
  `catalinas-3d/img/` are the 4K renders scaled to 1920 pixels.
- Summit positions come from the USGS Geographic Names service; heights shown are read from the
  elevation grid at those points.

## Refreshing the kit fox page

```
py tools/build_kitfox_shortlist.py
py tools/publish_kitfox.py
```

Needs Python with numpy, scipy, geopandas, pyogrio, pyproj, pillow and rasterio, and the ArcGIS Pro
project the model was built in (read only). Its folder and layer names are read from
`tools/kitfox-review/project.json`, which is git-ignored so the repo does not name the project. The model itself lives in that project: change weights or scores there, in the
Suitability Modeler, then re-run both scripts.

- `build_kitfox_shortlist.py` reads the finished suitability surface, finds the best 3 km circles, and
  screens them by land manager (BLM Arizona surface management, fetched and cached in the system temp
  folder `finkgeo_kitfox_cache`), slope and distance from highways. It also reports which wilderness
  areas, national monuments and other designations each area touches, without screening on them. The limits are command-line flags
  and are first guesses. It writes `tools/kitfox-review/`, which has a review map on satellite imagery.
- `publish_kitfox.py` scores the eight criteria the way the model does, averages them to 500 m cells,
  and writes `kit-fox-release/data/`. It prints how closely the rebuilt surface matches the model's.
- The page gives shortlisted areas only as rounded positions (0.1 degree) with a direction and distance.
  Keep it that way, and keep `tools/kitfox-review/` out of git: neither the page nor the repo should
  point at a spot where a released animal could be found.
- The step text and scoring tables on the page are written out in `kitfox.js` (`CRIT`). If a class
  break or score changes in the model, change it there too.

## Refreshing the KXCI signal page

```
py tools/build_kxci.py
py tools/model_kxci_terrain.py
py tools/publish_kxci.py
```

Needs Python with requests, pandas, geopandas, shapely, numpy, scipy, pillow, pyproj, matplotlib and
itmlogic. Downloads go to `kxci-signal/work/`, which is not in the repository (about 500 MB).

- `build_kxci.py` reads the station's licence from the FCC's FM Query, asks the FCC Contours API for
  the 60 dBu contour computed from those figures, and counts 2020 Census residents and households
  inside it (blocks cut by the contour count by area).
- Do not fetch the contour by call sign: as of November 2026 the API answers with a 1991 licence on
  Mt. Bigelow. The script keeps that contour only for the comparison on the page.
- `model_kxci_terrain.py` downloads USGS 3DEP elevation and runs the Irregular Terrain Model
  (Longley-Rice) along 720 radials at two receiver heights, then reads the result at every block.
- `publish_kxci.py` writes `kxci-signal/data/` and the static map.
- `kxci_drive_logger.py` records signal strength from an RTL-SDR dongle on a drive (`log`), and adds
  positions from a GPX track afterwards (`join`). Its logs go to `kxci-signal/drives/`; keep them
  out of the repository, because they trace where the vehicle has been.

## External services

The Catalinas page loads three.js 0.170.0 from jsDelivr through an import map with integrity hashes.

The map pages load Leaflet from cdnjs (pinned version, with integrity hashes) and basemap tiles from
Esri's public tile servers (satellite imagery and labels on the golf map, the light gray canvas on the
Loop and kit fox pages), with the attribution Esri requires. The site itself sets no
cookies, but visitors' browsers do contact those two services when the map loads. If the site ever
becomes commercial, re-read Esri's terms for those tiles.

## Preview locally

From this folder, run any static file server, for example:

```
python -m http.server 8000
```

then open <http://localhost:8000>. Links use root-relative paths (`/assets/...`),
so opening the HTML files directly from disk will not load the styles.
