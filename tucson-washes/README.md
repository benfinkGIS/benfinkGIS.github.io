# Tucson Wash Corridors

Map how wildlife could move between the Tucson Mountains and the Santa
Catalinas through the washes, parks and canopy of northwest Tucson, at the
finest detail the data allows, and show where the gaps are.

Portfolio project #2 for the Second Nature Ecology + Design GIS Analyst
application. Brought into this repo on 14 November 2026 from an outline
written outside it (`02-tucson-wash-corridors.md`); this file replaces that
outline. Project 1 is `tucson-canopy/`.

## Where it stands (14 November 2026)

Stage 1, the wash field guide, is built: the channel network, its attributes,
and the page at `/tucson-washes/` with a full-page map at `/tucson-washes/map/`
and a home page entry. Stages 2 to 4 (barriers, connectivity, gaps) are not
started.

### Stage 1 results

| | |
| --- | --- |
| Wash channel traced from lidar, 2 ha and up | 3,335 km in 14,392 reaches |
| Of that, more than 15 m from any county-mapped wash | 1,657 km (50%) |
| Traced flow running down streets, kept apart | 429 km |
| County Wash Network in the box | 1,826 km, 84 named washes with at least 0.5 km of open channel |
| Share of the county network the lidar channels land on | 91% (89 to 98% by flow class) |
| Tree canopy within 10 m of a wash | 16.1%, against 11.0% across the study area |
| Wash length inside mapped riparian habitat | 30% |
| Records within 50 m of a wash | 180 of 393 bobcat, 619 of 1,512 flycatcher, 210 of 684 queen |

Canopy rule, set against Project 1's lidar canopy: NDVI 0.16 or more,
near-infrared brightness 70 or more, 5 m spread 7 or more. It agrees with
the lidar map on 91% of cells in Dunbar Spring and 95% in Western Hills II,
finds about three quarters of the lidar canopy, and 71 to 79% of what it
calls canopy is. Most of its false canopy is low vegetation.

Things that came up while building it:

- Saving the flow accumulation raster in place failed on the full area
  (ERROR 010240); copying it out with Copy Raster works. The whole channel
  build takes about 15 minutes, not the hour first estimated.
- With one 15 m tolerance, reaches of the Santa Cruz took the name of
  tributaries at their confluences, and the big rivers were found only 78%
  of the time. The tolerance now widens to 30 m and 60 m for the county's
  larger flow classes, and the larger wash wins where two names overlap.
- A named wash's length is the county centerline, not the sum of the lidar
  reaches that carry the name, which counted side threads in wide beds twice.
- The imagery was flown on three dates (3 September, 15 and 18 October
  2023), so greenness is not strictly comparable across the area.
- `work/first_look.jpg` and `work/first_look.json` are the pre-modelling
  check of the study area and the sightings.

Not done in stage 1, though the outline lists them under channel attributes:
channel width and channel type (natural, soil cement, concrete). Channel type
moves to stage 2 with the crossings, where it shares the hand-checked sample.

## Study area (Ben's pick, 14 November 2026)

A box 25 km east to west and 21 km north to south, 525 km2: from the north
end of the Tucson Mountains (southwest corner) to Pusch Ridge in the Santa
Catalinas (northeast corner), and from Grant Road (south) to Tangerine Road
(north). Defined in `study_area.json`, which every script reads.

The first draft was a box further south, from the Tucson Mountains to
downtown (kept in `study_area.json` as `bbox_first_draft`, and drawn in
`work/first_look_draft1.jpg`). Ben asked for one further north and wider, to
take in the urban washes. The northern box is the better study:

- It has wild land on two sides, and bajada washes off the Tortolitas coming
  in from the north, so the question becomes how animals get between
  mountain ranges across the city. That is the question connectivity models
  are built for; the first draft had one source and no clear destination.
- The three big channels (Santa Cruz, Rillito, Canada del Oro) and the small
  washes of Casas Adobes, Flowing Wells and the Catalina Foothills are all
  inside it.
- It costs area: 1.8 times the first draft, so twice the elevation to
  process and twice the crossings to type.
- It keeps only the northern half of the bobcat collar study's ground (see
  change 7).

## What the data check found

| Outline item | What is there | Consequence |
| --- | --- | --- |
| Wash names from NHD | The county Wash Network has 1,552 segments in the box, 1,826 km, with 94 wash names on 593 km of it. NHD has 115 named flowlines | Names come from the county layer; NHD is a cross-check. Two thirds of the mapped length has no name |
| Riparian classes | County layer "Riparian classifications, 2005", with edits dated up to 2020. Class codes H, A, B, C, D, some carrying an IRA prefix. 11% of the box | The codes need reading against the county's metadata page before the map legend puts words on them |
| Culverts for hydro-enforcement | No complete public culvert layer. The county flood maps list 166 structures here (43 bridges, 43 culverts, 41 levees, the rest channels and others); the National Bridge Inventory has 225 bridges and long culverts | Small culverts have to be found from the lidar itself, where a wash meets a road embankment |
| Lidar elevation | USGS 1 m bare-ground tiles from the 2021 flight: twelve tiles, about 300 MB each, on a fast server | The channel network runs on these, not on the raw point cloud |
| Land cover and canopy from Project 1 | Project 1 covers two neighborhoods of about half a square kilometre each, and neither is in this area | It cannot be extended. See change 1 below |
| iNaturalist records, research grade, open position | Bobcat 552, vermilion flycatcher 2,110, queen 893. GBIF adds 59,791 eBird records for the flycatcher and 575 eButterfly records for the queen | Enough to work with; eBird records sit on hotspot pins, not where the bird was |
| Circuitscape or Omniscape | Both need Julia, which is not installed on this machine | Needs Ben's go-ahead to install |

Two things the first look showed about the records:

- **They do not follow the washes.** Of the records placed to within 100 m,
  22% of bobcats, 21% of flycatchers and 19% of queens are within 50 m of a
  county wash. So is 30% of the whole box. People photograph animals where
  people are, so validation by counting sightings along washes (outline
  step 6) will mostly measure observers unless effort is corrected for.
- **The flycatcher is a park and river bird here.** Its records cluster at
  Sweetwater Wetlands, Christopher Columbus Park and along the Rillito and
  the Santa Cruz, and are thin along the foothill washes. Its map will be about
  stepping stones of turf, trees and water, not about washes off the
  mountain. That is a fair contrast with the bobcat, but it is a different
  story from the one in the outline.

## Changes to the outline

1. **Canopy and land cover.** Rebuilding Project 1's half-metre land cover
   over 525 km2 would take on the order of 900 lidar tiles (roughly 50 GB
   at the server's speed, then many hours of processing). Instead: a 1 m canopy and
   pavement layer from the 2023 NAIP imagery, with its thresholds set and
   scored against Project 1's hand-checked canopy at the two sites. Lidar
   canopy height is added only in a strip along the channels if time allows.
2. **Channel network.** Flow accumulation on the 1 m elevation, with the
   county Wash Network as a known skeleton. The lidar adds the small channels
   the county layer lacks, and the county layer scores the lidar network: how
   much of each mapped wash the lidar finds, and how far off.
3. **Culverts.** Where a county wash or a lidar channel meets a road and the
   ground rises across it, cut the embankment down to the channel. Flood-map
   structures and bridge inventory points confirm the big ones.
4. **Crossings.** There are 16,631 street segments over 1,826 km of wash, so
   crossings are typed by rule first: embankment height from the lidar
   (bridge or culvert against at-grade dip crossing), opening size where the
   inventories give it, road class for traffic. Then a sample is checked by
   hand on the imagery, using the same labelling page as Project 1's accuracy
   check, so the crossing types come with an accuracy figure.
5. **Channel type.** No layer says natural, soil cement or concrete. It comes
   from what covers the channel floor in the imagery and elevation (flat,
   uniform and unvegetated reads as lined), with the same hand-checked
   sample.
6. **Connectivity.** Omniscape for the current-flow maps the outline wants,
   if Julia can be installed. Everything else stays in ArcPy, as in
   Project 1. Without Julia, ArcGIS Pro's own corridor tools give least-cost
   corridors but no current-flow picture.
7. **Validation.** Two checks instead of one. Sightings are compared with all
   iNaturalist records of the same group (all mammals, all birds, all
   butterflies) in the same places, which takes out most of the observer
   effect. And the bobcat result is compared with the Bobcats in Tucson
   collar study, which tracked cats caught along the east side of the Tucson
   Mountains between El Camino del Cerro and 36th Street. The box reaches
   south only to Grant Road, so about half of that ground is inside it. Only
   the study's published findings are used, not its data.
8. **Sightings on the public map.** Many bobcat records are in people's
   yards. The map shows counts per wash reach and leaves the dots out.
9. **Gap ranking.** "Connectivity gain if fixed" means re-running the model
   with each candidate gap repaired. That is practical for 10 to 20
   candidates per species on a 10 m grid, so candidates are shortlisted
   first from pinch points, lined reaches and poor crossings.
10. **Field guide blurbs.** 94 named washes is a lot of pop-ups to write
    well. The first release writes up the 20 or so that matter most as
    corridors; the rest get their figures without a blurb.

## Stages

Each stage ends in something that can go on the site by itself.

| Stage | What it builds | Outline steps |
| --- | --- | --- |
| 1 Wash field guide | Channel network from lidar and county data, names, riparian class, canopy share, length, sightings per reach; the clickable map | 1, 2 |
| 2 Barriers | Crossings typed and scored, channel type, hand-checked sample | 3 |
| 3 Connectivity | Resistance surfaces, Omniscape runs per species, composite, validation | 4, 5, 6 |
| 4 Gaps | Shortlist, repair runs, ranked list with a recommended action each; hero map | 7 |

## Workflow

Scripts live in `tools/washes/`, numbered in run order. Large files go in
git-ignored `tucson-washes/work/`. Downloads run in the system Python (`py`);
raster work will run in ArcGIS Pro's Python, as in Project 1.

| Step | Script | Runs in | What it does |
| --- | --- | --- | --- |
| 1a | `01_get_context.py` | py | County washes, riparian habitat, streets, parks, protected lands, flood-map structures; NHD named flowlines; National Bridge Inventory |
| 1b | `02_get_sightings.py` | py | Research-grade iNaturalist records of the three species, and GBIF record counts by dataset |
| 1c | `03_first_look.py` | py | First-look map and counts |
| 1d | `04_get_elevation.py` | py | The twelve USGS 1 m elevation tiles |
| 2a | `05_get_imagery.py` | py | 2023 NAIP, four bands at 1 m, over the study area and over Project 1's two neighborhoods |
| 2b | `06_channels.py` | propy | Culvert cuts at county wash crossings, pit filling, flow direction and accumulation, channels of 2 ha and up split into reaches. `--window x0 y0 x1 y1` runs a small box for testing |
| 2c | `07_canopy.py` | propy | Sets the imagery canopy rule against Project 1's lidar canopy, applies it to the study area, and writes the canopy share within 10 m |
| 3 | `08_reaches.py` | propy | Name, county and street share, riparian class, canopy and sightings for every reach; the county-network completeness check; `data/channels.geojson` and `data/washes.json` for the page |

`propy` is ArcGIS Pro's Python:

    "%LOCALAPPDATA%\Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"

Still to build (stages 2 to 4): crossings and channel type, resistance
surfaces, connectivity runs, validation, gap ranking.

### Geodatabase (`work/washes.gdb`)

| Layer | What it is |
| --- | --- |
| `washes`, `streets`, `railroads`, `riparian`, `parks`, `protected`, `structures`, `nhd_named`, `bridges_nbi` | Source layers over the study area |
| `crossings_county` | Points where a county wash meets a street or the railroad |
| `culvert_cuts` | The strips lowered to channel-bed level at those crossings |
| `channels_raw` | Lidar channels, one line per reach, with Strahler order and drainage area |
| `reaches` | The same lines with every attribute the page uses |
| `sightings_bobcat`, `sightings_flycatcher`, `sightings_queen` | iNaturalist records placed to 100 m or better |

Rasters sit beside it in `work/dem/` (elevation, cut and filled versions,
flow direction and accumulation, reach ids, Strahler order, and the county
layers as grids) and `work/canopy/`.

## Focal species

| Species | Why | Movement |
| --- | --- | --- |
| Bobcat (*Lynx rufus*) | Ground traveler; known to use Tucson washes; blocked by roads and culverts | Terrestrial |
| Vermilion flycatcher (*Pyrocephalus rubinus*) | Riparian bird; tests canopy and water stepping stones | Patch-hopping |
| Queen butterfly (*Danaus gilippus*) | Pollinator; depends on native milkweeds in washes | Floral resource |

Native bees are ecologically the most important pollinators, but iNaturalist
identifications are mostly to genus. A fuller study would add them.

## Needs from Ben

- Go-ahead to install Julia and Omniscape.
- About an hour of hand-checking crossings and channel types on imagery,
  once the sample is drawn.

## Limits to state in the write-up

- Lidar flow paths in flat built-up ground depend on the culvert cuts and the
  pavement mask.
- The riparian classes were adopted in 2005 and edited since; spot-check
  against the 2023 imagery.
- Resistance values are assigned by judgement; the write-up lists them.
- iNaturalist records are presence-only and follow where people go.
- Canopy over the whole area comes from imagery, not lidar, and is scored
  only at Project 1's two sites.
- Crossing and channel types are rule-based with a hand-checked sample, not
  a field survey.

## Site page rules

The page goes at `/tucson-washes/` in the site's look, with a `/map/`
full-page map, a toolbar link to it and a home page entry. No draft or
under-construction labels. The outline asks for MapLibre, which suits this
map (thousands of channel lines and raster overlays); the site's other maps
use Leaflet.
