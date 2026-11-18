# Lake Powell drawdown animation: data and processing record

Processing started 2026-11-15. Open-source tools only (Python, rasterio/GDAL, Blender, ffmpeg). No ArcGIS.

## Folders

| Path | Holds |
|---|---|
| `tools/powell/` | Numbered scripts, `common.py`, `run.py`, this file (tracked in git) |
| `lake-powell/work/raw/` | Downloads, never modified (git-ignored) |
| `lake-powell/work/processed/` | Derived rasters, cleaned tables, check pictures (git-ignored) |
| `lake-powell/work/blender/` | Blender scenes (git-ignored) |
| `lake-powell/work/renders/` | Frames and video (git-ignored) |

Run everything with `py tools/powell/run.py`.

## Water level series

- Source: Bureau of Reclamation, Upper Colorado Region HydroData, site 919 (Lake Powell).
  - Elevation: `https://www.usbr.gov/uc/water/hydrodata/reservoir_data/919/csv/49.csv`
  - Storage: `https://www.usbr.gov/uc/water/hydrodata/reservoir_data/919/csv/17.csv`
  - The same series are in RISE (data.usbr.gov) as catalog items 508 (elevation) and 509 (storage). Both read from the same Reclamation database (`uchdb2`).
- Downloaded 2026-11-15 by `01_get_levels.py`; the fetch time is in `raw/levels/source.json`.
- Units: feet. Vertical datum: not stated in the files. To be settled in the datum step below.
- Elevation runs 1963-12-28 to 2026-11-14, one value a day, 22,968 days, none missing.
- Storage runs 1963-06-28 to 2026-11-14. It starts at zero, which is the day the lake reached dead pool (3,370 ft). There is no daily record at all between the start of filling in March 1963 and 1963-06-28, and no elevation record until 1963-12-28 (3,409.0 ft).
- Recent data are provisional (Reclamation's own note).

Values read from the download (refresh by re-running step 1):

| | Feet | Date |
|---|---|---|
| First reached full pool (3,700) | | 1980-06-22 |
| Record high | 3,708.34 | 1983-07-14 |
| Record low since filling | 3,516.62 | 2026-09-15 |
| Previous record low | 3,519.92 | 2023-04-13 |
| Latest | 3,539.85 | 2026-11-14 |

Reference elevations (feet, Reclamation's datum): full pool 3,700; minimum power pool 3,490; dead pool 3,370.

## Terrain

- Source: Jones, D.K., and Root, J.C., 2021, Modified topobathymetric elevation data for Lake Powell: U.S. Geological Survey data release, https://doi.org/10.5066/P9H60YCF (ScienceBase item `60a58d8ad34ea221ce48cce3`). Companion report: https://doi.org/10.3133/sir20225017.
- It is a corrected version of Poppenga and others, 2020 (https://doi.org/10.5066/P9XX0J1Y).
- Downloaded 2026-11-15 by `03_get_dem.py`. Raster zip 3.19 GB (no checksum published); spatial metadata zip and FGDC record matched their MD5 sums.
- File: `Lake_Powell_TBDEM_Modified_1m.tif`, one GeoTIFF, 3.39 GB, LZW, 32-bit float, 130,174 x 129,927 cells, built-in overviews down to 1/1017.

Read from the file by `04_inspect_dem.py` and checked against the FGDC record:

| | |
|---|---|
| Horizontal CRS | NAD83(2011) / UTM zone 12N, EPSG:6341 |
| Horizontal units | meters |
| Cell size | 1 m |
| Extent (m) | E 445,521 to 575,695; N 4,076,616 to 4,206,543 |
| Vertical datum | NAVD88, Geoid 12B (from the FGDC record and the Esri sidecar; the GeoTIFF itself carries no vertical CRS) |
| Vertical units | meters |
| Elevation range | 948.28 to 1,440.94 m |
| Nodata | -3.4028235e+38 |
| Ground dates | bathymetry autumn 2017, lidar spring 2018, pre-dam contour maps 1947 and 1959 in gaps |

Things the file showed that the plan has to allow for:

- **It covers the reservoir only.** 5.6% of the bounding box has data (about 945 km2): the lake bed and a rim that mostly stops 15 to 30 m above full pool. The canyon rims, mesas and Navajo Mountain are not in it. Any view wider than a close-up needs a second DEM around it (USGS 3DEP 10 m).
- **The lake bed is the 2017 bed.** Sediment has filled the Colorado and San Juan deltas, so a replay of the 1963 fill floods today's bottom, not the original canyon. Say so in the video.
- The river channels above both deltas were patched from other DEMs (2015 0.5 m lidar, 2007 Utah 5 m). See the spatial metadata shapefile for which source covers where.
- Without any datum shift, the area at or below 3,700 ft is about 632 km2 on a 60 m sample, which is the right size for Lake Powell at full pool.
- The lowest cell (955.7 m) is at E 456,951, N 4,087,833, the river just below Glen Canyon Dam.

## Vertical datum conversion

Settled 2026-11-15 by `05_datum.py`; the numbers are in `processed/datum.json`.

- Reclamation's Lake Powell elevations are feet above **NGVD29**. The DEM is meters above **NAVD88**.
- Conversion used: **NAVD88 = NGVD29 + 2.913 ft (0.888 m)**, then feet to meters at 0.3048.
- Source: Jones and Root, 2022, Elevation-area-capacity tables for Lake Powell, 2018 (https://doi.org/10.5066/P9O3IPG3). They took it from NOAA VERTCON at the USGS reservoir gauge beside the dam (09379901, 36.9369326, -111.4837694). Reclamation's 2022 area and capacity report adopts the same figure (its Appendix A), and the USGS lake extent polygons (https://doi.org/10.5066/P13OE7QW) use it too.
- One constant is right for the whole lake: the water surface is level and is measured at the dam.
- Check against NOAA's service today (VERTCON 3.0): +0.885 m at the dam gauge, 3 mm from the value used. Elsewhere along the lake NOAA gives +0.870 m (San Juan arm) to +0.994 m (Bullfrog), which is how the two datums differ over land there. It does not apply to the water surface.

| | Feet, NGVD29 (Reclamation) | Meters, NAVD88 (DEM) |
|---|---|---|
| Full pool | 3,700 | 1,128.648 |
| Minimum power pool | 3,490 | 1,064.640 |
| Dead pool | 3,370 | 1,028.064 |

The 1 m DEM shows Glen Canyon Dam, and the full pool contour runs along its crest (`processed/dam_check.png`).

## Whole-lake terrain

Built 2026-11-15 by `06_get_context.py` and `07_build_terrain.py`.

- Frame: the lake DEM's extent grown by 4.5 km on every side. E 441,021 to 580,221; N 4,072,113 to 4,211,043 (EPSG:6341). 4,640 x 4,631 cells of 30 m, lined up with the 1 m grid.
- Lake DEM at 30 m: mean of the 2 m overview level, up to 225 values per cell, with the share of each cell it covers.
- Surroundings: USGS 3D Elevation Program, `3DEPElevation` image service, 10 m, meters above NAVD88, 49 tiles, averaged to 30 m. Requested in EPSG:26912 (NAD83), which differs from EPSG:6341 by about a meter. Kept as `processed/context_10m.tif`.
- Merge: lake DEM wherever it has data, 3DEP elsewhere, weighted by coverage in partly covered cells. On dry ground both cover, lake DEM minus 3DEP has a median of 0.09 m (5th to 95th percentile -3.5 to +3.9 m).
- Glen Canyon Dam is burned back in: cells along its crest take the highest 1 m value inside them.
- Reservoir mask: cells at or below the record high (3,708.34 ft) plus 2 m that connect to the lake above the dam. The water sheet is drawn only there, so the canyon below the dam never floods.
- Outputs: `processed/terrain_30m.tif` (float32, EPSG:6341), `terrain_30m.npy`, `reservoir_30m.npy`, `lake_cover_30m.npy`, `terrain.json`. Elevation range 932.4 to 3,473.7 m.

## Checks

- **Area at full pool:** 639.7 km2 from the 30 m terrain; 644.5 km2 in the USGS elevation-area-capacity table for the same survey (0.7% low, from 30 m cells).
- **Landsat, independent of the DEM** (`10_check_landsat.py`, scenes read from Microsoft Planetary Computer, lower lake only). The terrain height at Landsat's shoreline on gentle ground, read back as a Reclamation elevation:

| Scene date | Reclamation that day | Read from Landsat shoreline | Difference | Shore cells |
|---|---|---|---|---|
| 1984-07-04 (Landsat 5) | 3,702.04 ft | 3,700.1 ft | -2.0 ft | 294 |
| 2023-04-11 (Landsat 8) | 3,520.11 ft | 3,515.4 ft | -4.7 ft | 55 |

  Both are inside what a 30 m cell can resolve. Water area is not used as the test: Landsat misses water in cliff shadow and in canyons narrower than a pixel (240 against 259 km2 in 1984, 84 against 104 km2 in 2023), while open shorelines agree (`processed/landsat_check_*.png`).

## Blender scene and year slider

- `08_blender_scene.py`, Blender 5.2, Cycles. One unit is 1 km. Vertical exaggeration 2.5. Sun azimuth 235, elevation 28.
- Ground color is procedural (height and steepness). Ground inside the reservoir between the water and full pool is drawn pale. Water color is by depth.
- Yearly table: `09_yearly_levels.py`, calendar-year mean of the daily elevations, 1964 onward. The current year is a year to date.
- Slider page: `lake-powell/index.html` with `frames/<year>.jpg` and `data/years.json`, written by `11_publish_slider.py`.

## Target CRS for Blender

Keep the DEM's own CRS (EPSG:6341, meters). No reprojection is needed.
