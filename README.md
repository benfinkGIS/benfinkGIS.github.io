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

## External services

The Catalinas page loads three.js 0.170.0 from jsDelivr through an import map with integrity hashes.

The map pages load Leaflet from cdnjs (pinned version, with integrity hashes) and basemap tiles from
Esri's public tile servers (satellite imagery and labels on the golf map, the light gray canvas on the
Loop pages), with the attribution Esri requires. The site itself sets no
cookies, but visitors' browsers do contact those two services when the map loads. If the site ever
becomes commercial, re-read Esri's terms for those tiles.

## Preview locally

From this folder, run any static file server, for example:

```
python -m http.server 8000
```

then open <http://localhost:8000>. Links use root-relative paths (`/assets/...`),
so opening the HTML files directly from disk will not load the styles.
