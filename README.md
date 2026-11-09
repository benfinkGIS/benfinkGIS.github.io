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
| `404.html` | Not-found page |
| `assets/style.css` | Shared styles (late-90s desktop look; plain CSS, no web fonts) |
| `assets/*.svg` | Pixel-style icons. `globe.svg` doubles as the favicon. |
| `CNAME` | Tells GitHub Pages the custom domain (`finkgeo.com`). Don't delete it. |
| `.nojekyll` | Tells Pages to serve the files as-is, skipping Jekyll |

## TODO

- Replace the About placeholder text in `index.html` (search for `TODO`).
- Tucson golf map: water use is in popups and the table only. Next: map layers (for example colour by supply, size by use).
- Tucson golf map: the SaddleBrooke Ranch outline in OpenStreetMap is incomplete (flagged on the map). Fix it in OSM, or digitize it by hand, then refresh the data.
- Bump the "Last updated" date in each page footer when content changes.

## Refreshing the golf course data

```
py tools/build_courses.py
```

This queries OpenStreetMap (Overpass API, which is sometimes busy; the script retries) and rewrites
`tucson-golf-water/data/courses.geojson`. OpenStreetMap does not mark closed courses here, so
the script keeps a hand-maintained list of closed courses to leave out (`EXCLUDE_CLOSED`). Re-check
that list on each refresh, and update the "Data sources and methods" text on the page if it changes.

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

## External services

The map page loads Leaflet from cdnjs (pinned version, with integrity hashes) and satellite imagery
and labels from Esri's public tile servers, with the attribution Esri requires. The site itself sets no
cookies, but visitors' browsers do contact those two services when the map loads. If the site ever
becomes commercial, re-read Esri's terms for those tiles.

## Preview locally

From this folder, run any static file server, for example:

```
python -m http.server 8000
```

then open <http://localhost:8000>. Links use root-relative paths (`/assets/...`),
so opening the HTML files directly from disk will not load the styles.
