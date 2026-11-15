# Tucson Wash Corridors

Map how wildlife could move between the Tucson Mountains and the Santa
Catalinas through the washes, parks and canopy of northwest Tucson, at the
finest detail the data allows, and show where the gaps are.

Portfolio project #2 for the Second Nature Ecology + Design GIS Analyst
application. Brought into this repo on 14 November 2026 from an outline
written outside it (`02-tucson-wash-corridors.md`); this file replaces that
outline. Project 1 is `tucson-canopy/`.

## Where it stands (15 November 2026)

Stages 1 and 2 are built. The page at `/tucson-washes/` (with `/map/` and a
home page entry) shows the wash network, its attributes and the road
crossings, and reports a hand check of all three. Stage 1 was published on
14 November; the stage 2 version of the page is built and checked locally.
Stages 3 and 4 (connectivity, gaps) are not started.

### Results

| | |
| --- | --- |
| Flow line traced from lidar, 2 ha and up | 3,765 km in 14,392 reaches |
| Kept as wash (cut 20 cm or more into the ground, or county-mapped) | 2,522 km in 9,378 reaches |
| Flow paths with no channel | 814 km |
| Storm water running down streets | 429 km |
| Wash more than 15 m from any county-mapped wash | 921 km (37%) |
| County Wash Network in the box | 1,826 km, 83 named washes with at least 0.5 km of open channel |
| Share of the county network the lidar channels land on | 91% (89 to 98% by flow class) |
| Tree canopy within 10 m of a wash | 16.7%, against 11.0% across the study area |
| Wash length inside mapped riparian habitat | 38% |
| Road crossings on washes | 2,637: 102 open spans, 996 culverts, 1,539 at-grade |

### The hand check (14 and 15 November 2026)

Ben labelled 340 items from the 30 cm imagery without seeing what the rules
had said: 160 channel reaches (at their midpoints) and 180 crossings. One
reach and four crossings were "can't tell". The labelling took about 37
minutes of active time, a median of 2.5 seconds an item. Figures below are
weighted back to the population each stratum was drawn from; brackets are
95% ranges from resampling within strata.

**What it found, before any rule was changed.** 79% (69 to 87) of traced
reaches were washes to the eye; the rest were yards, lots and road edges.
The first-pass colour rule for concrete was right on 3 of the 60 reaches it
flagged. Of 60 points first typed at-grade, 37 were labelled "no crossing
here".

**What was changed because of it** (`12_check_score.py` writes `rules.json`):

- A reach is a wash only if its line sits at least 20 cm below the average
  ground within 7 m, or at least half of it is on the county wash layer or
  riparian map; and under a fifth of it is on street pavement. The 20 cm was
  chosen from the labels (grid 10 to 30 cm); the other three numbers were
  set by looking at the labels and not cross-validated.
- Crossing cut-offs moved from a 1.2 m step and 0.6 m hump to 1.8 m and
  1.2 m.
- Crossings are found only on reaches kept as washes.
- Bed material is not mapped. It is reported as shares from the sample.

**How the changed rules score**, leave-one-out (each item typed by cut-offs
chosen without it):

| | |
| --- | --- |
| Reaches the wash rule keeps that are washes | 86% (76 to 94) |
| Real washes the rule keeps | 90% (81 to 98) |
| Reaches it drops that are not washes | 57% (33 to 83) |
| Wash rule agrees with the label | 81% (71 to 89) |
| Mapped crossings on kept reaches that are real crossings | 68% (57 to 79) |
| ... typed open span | 97% (89 to 100) |
| ... typed culvert | 68% (50 to 84) |
| ... typed at-grade | 66% (50 to 82) |
| Type agrees with the label, where the crossing is real | 77% (66 to 88); 72% with the first cut-offs |
| Beds of real washes: natural | 80% (69 to 90) |
| Beds of real washes: natural bed, built banks | 17% (8 to 27) |
| Beds of real washes: concrete | 3% (0 to 7) |

Against the inventories, after the change: 39 of 46 inventoried bridges come
out as open span (85%), and 119 of 142 inventoried culverts as culvert, with
15 more as open span (the Bridge Inventory lists only culverts of 20 ft and
over).

Limits of the check:

- The same labels chose the cut-offs and scored them. Leave-one-out guards
  the 20 cm, the step and the hump, but not the form of the rule or the
  three numbers set by eye.
- One labeller, working fast, from photos. "No crossing here" covers several
  things: no visible wash, a wash that runs alongside, and county street
  lines that are driveways.
- The sample was drawn before the wash rule existed, so each item's measures
  were frozen when drawn (`work/check/sample_attrs.json`) and the scoring
  reads those, not the current geodatabase.
- Channel-bed marks under a bridge or road were labelled as the channel is on
  either side. They were going to be scored apart from the rest; with only
  7 concrete labels in 160 there was no bed rule to score, so they are not.

Labelling rules agreed while labelling:

- A channel-bed mark that lands on a bridge deck or a road over the wash is
  labelled as the channel is on either side of it; "can't tell" if the sides
  differ or neither can be seen.

### Things that came up while building it

- Saving the flow accumulation raster in place failed on the full area
  (ERROR 010240); copying it out with Copy Raster works. The whole channel
  build takes about 15 minutes.
- With one 15 m tolerance, reaches of the Santa Cruz took the name of
  tributaries at their confluences, and the big rivers were found only 78%
  of the time. The tolerance now widens to 30 m and 60 m for the county's
  larger flow classes, and the larger wash wins where two names overlap.
- A named wash's length is the county centerline, not the sum of the lidar
  reaches that carry the name, which counted side threads in wide beds twice.
- The imagery was flown on three dates (3 September, 15 and 18 October
  2023), so greenness is not strictly comparable across the area.
- Crossings: the bed line is fitted from 15 to 80 m either side with samples
  on the road fill trimmed out, because a flat 20 to 40 m window sat on top
  of wide fills. The step is tested before the hump and searched further
  along the road on big washes, because long bridges put the abutment 100 m
  from the channel line.
- The pale granite sand in the washes off the Catalinas is as grey and as
  bright as concrete in the imagery. Texture, lidar bed roughness and
  straightness are stored per reach (`10_channel_type.py`) but nothing was
  fitted to them.
- `work/first_look.jpg` and `work/first_look.json` are the pre-modelling
  check of the study area and the sightings.

Still open from the outline: channel width; culvert size; permeability scores
per species, which belong with the resistance surfaces in stage 3 and will
have to carry the crossing uncertainty above.

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
| 3 | `08_reaches.py` | propy | Name, county and street share, riparian class, canopy, channel depth and sightings for every reach; wash, flow path or street by the cut-offs in `rules.json`; the county-network completeness check |
| 4 | `09_crossings.py` | propy | Every wash and road crossing, measured on the lidar and typed open span, culvert or at-grade; compared with the flood-map structures and the National Bridge Inventory |
| 5 | `10_channel_type.py` | propy | First-pass bed type from imagery colour, plus texture, lidar bed roughness and straightness for each reach |
| 6a | `11_check_sample.py` | propy | Stratified hand-check sample of crossings and channel beds, with image chips from the 30 cm imagery |
| 6a | `label_server.py` + `tools/washes-label/` | py | Local page for labelling the sample without seeing the rule's answer |
| 6b | `12_check_score.py` | py | Scores the rules against the labels, re-chooses the cut-offs with leave-one-out, writes `rules.json` and `work/check/results.json` |
| 7 | `08_reaches.py --export` | propy | Writes `data/channels.geojson`, `data/crossings.geojson` and `data/washes.json` for the page |

`propy` is ArcGIS Pro's Python:

    "%LOCALAPPDATA%\Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"

Run order after a change to `rules.json`: 08, 09, 10, then 08 with
`--export`. Steps 11 and 12 are the one-off hand check; do not redraw the
sample.

Still to build: resistance surfaces, connectivity runs, validation and gap
ranking (stages 3 and 4).

### Geodatabase (`work/washes.gdb`)

| Layer | What it is |
| --- | --- |
| `washes`, `streets`, `railroads`, `riparian`, `parks`, `protected`, `structures`, `nhd_named`, `bridges_nbi` | Source layers over the study area |
| `crossings_county` | Points where a county wash meets a street or the railroad |
| `culvert_cuts` | The strips lowered to channel-bed level at those crossings |
| `channels_raw` | Lidar channels, one line per reach, with Strahler order and drainage area |
| `reaches` | The same lines with every attribute the page uses, plus `bed_rule` and the bed measures |
| `crossings` | Wash and road crossings: road class, hump and step from the lidar, rule type, inventory type where there is one |
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
