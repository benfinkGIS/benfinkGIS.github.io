"""Shared paths and settings for the Lake Powell drawdown animation.

Every numbered script imports this, so the folder layout, the data sources and
the reference elevations are defined in one place. Open-source tools only.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "lake-powell"
WORK = PROJECT / "work"                 # git-ignored
RAW = WORK / "raw"                      # downloads, never modified
RAW_LEVELS = RAW / "levels"
RAW_DEM = RAW / "tbdem"
PROCESSED = WORK / "processed"          # derived rasters and cleaned tables
BLENDER = WORK / "blender"
RENDERS = WORK / "renders"

USER_AGENT = {"User-Agent": "lake-powell-drawdown/0.1"}

# Bureau of Reclamation, Upper Colorado Region HydroData. Site 919 is Lake
# Powell. The same series are in RISE (data.usbr.gov) as catalog items 508
# (elevation) and 509 (storage); both read from the same database (uchdb2).
HYDRODATA = "https://www.usbr.gov/uc/water/hydrodata/reservoir_data/919/csv/{code}.csv"
SERIES = {"elevation_ft": 49, "storage_af": 17}

# USGS data release: Jones and Root, 2021, Modified topobathymetric elevation
# data for Lake Powell, https://doi.org/10.5066/P9H60YCF
SCIENCEBASE_ITEM = "60a58d8ad34ea221ce48cce3"
SCIENCEBASE_JSON = "https://www.sciencebase.gov/catalog/item/{item}?format=json"
SCIENCEBASE_FILE = "https://www.sciencebase.gov/catalog/file/get/{item}"

# Lake Powell reference elevations in feet, Reclamation's datum (see METADATA.md)
FULL_POOL_FT = 3700.0
MIN_POWER_POOL_FT = 3490.0
DEAD_POOL_FT = 3370.0

FT_TO_M = 0.3048                        # international foot
EPSG_DEM = 6341                         # NAD83(2011) / UTM zone 12N, the DEM's own CRS

# --- Vertical datum -------------------------------------------------------
# Reclamation reports Lake Powell elevations in feet above NGVD29. The DEM is
# meters above NAVD88. USGS (Jones and Root, 2022, doi 10.5066/P9O3IPG3) add
# 2.913 ft to go from NGVD29 to NAVD88, taken from NOAA VERTCON at the USGS
# reservoir gauge by the dam (09379901); Reclamation's 2022 area and capacity
# tables adopt the same figure. One constant is right for the whole lake
# because the water surface is level and is measured at the dam.
NGVD29_TO_NAVD88_FT = 2.913


def reclamation_ft_to_dem_m(ft):
    """Reclamation elevation (ft, NGVD29) to the DEM's meters above NAVD88."""
    return (ft + NGVD29_TO_NAVD88_FT) * FT_TO_M


def dem_m_to_reclamation_ft(m):
    return m / FT_TO_M - NGVD29_TO_NAVD88_FT


# USGS elevation-area-capacity tables for the 2018 lake bed (same authors)
EAC_ITEM = "614ccd07d34e0df5fb9868e2"
EAC_FILE = "Lake_Powell_2018_ElevAreaCap_calc.csv"

# --- Scene frame ----------------------------------------------------------
# The DEM's own grid (origin 445521 E, 4206543 N) grown by 4.5 km on every
# side, in whole 30 m cells, so coarse cells line up with the 1 m cells.
DEM_X0, DEM_Y1 = 445521.0, 4206543.0
CELL = 30.0                              # whole-lake terrain cell, meters
PAD_CELLS = 150
DEM_COLS, DEM_ROWS = 4340, 4331          # 30 m cells that cover the 1 m DEM
FRAME_COLS, FRAME_ROWS = DEM_COLS + 2 * PAD_CELLS, DEM_ROWS + 2 * PAD_CELLS
FRAME_X0 = DEM_X0 - PAD_CELLS * CELL     # west edge
FRAME_Y1 = DEM_Y1 + PAD_CELLS * CELL     # north edge
FRAME_X1 = FRAME_X0 + FRAME_COLS * CELL
FRAME_Y0 = FRAME_Y1 - FRAME_ROWS * CELL

CONTEXT = RAW / "context"                # USGS 3DEP tiles around the lake
CONTEXT_CELL = 10.0
THREEDEP = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
NCAT = "https://geodesy.noaa.gov/api/ncat/llh"
