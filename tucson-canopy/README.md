# Tucson Neighborhood Canopy Scenario

Compare a well-shaded Tucson neighborhood with one that could be improved, then
simulate planting native shade trees and measure what changes: shade, heat,
carbon and habitat.

A personal portfolio project, started 13 November 2026. The page is at
<https://finkgeo.com/tucson-canopy/>.

## Study sites (chosen 13 November 2026)

| | Site | Role | Area | Green cover in the screen |
| --- | --- | --- | --- | --- |
| A | Dunbar Spring | Reference | 0.61 km2 | 17.2% |
| B | Western Hills | Improvement candidate | 0.47 km2 | 7.1% |

Both were picked from a screen of all 154 City of Tucson neighborhood
associations (`tools/screen_canopy_sites.py`): share of each neighborhood with
NDVI above 0.2 in the 18 October 2023 NAIP imagery, on a 4 m grid. That figure
counts any green vegetation, so it ranks neighborhoods but is not a canopy
figure. Lidar gives the real one.

Why these two:

- **Dunbar Spring** is the reference because its street trees are native
  trees planted by residents and watered by street runoff. The Dunbar/Spring
  Neighborhood Foresters say planting "began in 1996 with a neighborhood tree
  planting of 208 native trees", that over 1,700 native trees have gone in
  since, and that curb cuts and curb cores send street water to the plantings,
  over a million gallons a year
  (<https://dunbarspringneighborhoodforesters.org/be-a-neighborhood-forester/>,
  <https://dunbarspringneighborhoodforesters.org/welcome/accomplishments/>,
  read 13 November 2026). It is a working local example of the scenario being
  modelled, not an irrigated lawn-and-shade-tree neighborhood. Those are the
  group's own figures; the species list on their home page (mesquites, palo
  verde, desert hackberry) still needs reading in full before the page names
  species.
- **Western Hills** is about the same size, single-family, among the
  sparsest residential areas in the city, and has a vegetated wash on its
  southeast edge, so new trees can be scored on how they connect to existing
  habitat.

Western Hills is the name residents use (Ben, 14 November); the city's
neighborhood association layer registers it as "Western Hills II", and that
is the name `sites.json` uses to fetch the boundary.

Site definitions live in `sites.json`. Every script reads it, so a third site
is one more entry, not a new workflow.

## Results so far (13 November 2026)

Steps 0 to 9c and step 4 have run for both sites, and the land cover has been scored
against 300 hand-labelled points. Still to do: canopy change over time, and the remaining products.

Land cover inside each neighborhood boundary. "Mapped" is what the map says;
"corrected" is the share after allowing for the errors the accuracy check
found, and is the figure to quote.

| | Dunbar Spring mapped | corrected | Western Hills mapped | corrected |
| --- | --- | --- | --- | --- |
| Tree canopy | 18.5% | 21.4% | 10.3% | 10.0% |
| Roof | 16.8% | 17.9% | 17.4% | 18.0% |
| Pavement | 33.7% | 21.2% | 20.9% | 21.6% |
| Open ground (low vegetation + bare) | 30.9% | 39.5% | 51.3% | 50.4% |
| Water | under 0.1% | under 0.1% | under 0.1% | under 0.1% |

Tree canopy is the lidar canopy from step 2 (16.6% and 9.3%) plus its fringe:
green vegetation at least 1 m tall within 1 m of a crown, which gives back the
crown edges that the power-line cleanup trims.

### Accuracy

Ben labelled all 300 points from the 2023 photo on 13 November without seeing
the map. Six were marked "can't tell" and are left out, leaving 294.

| Question | Both sites | Dunbar Spring | Western Hills |
| --- | --- | --- | --- |
| Tree canopy or not | 95.4% (93.4 to 97.4) | 94.2% | 97.0% |
| Impervious or not | 81.4% (75.9 to 86.9) | 79.0% | 84.6% |
| Five classes, open ground merged | 75.4% (69.7 to 81.1) | 70.2% | 82.3% |
| All six classes | 72.1% (66.3 to 78.0) | 66.7% | 79.3% |

Overall accuracy, weighted by each class's mapped area, with 95% intervals.
Kappa for the six classes is 0.67.

By class, both sites together:

| Class | User's accuracy | Producer's accuracy |
| --- | --- | --- |
| Tree canopy | 90% | 82% |
| Roof | 89% | 85% |
| Pavement | 54% | 69% |
| Open ground | 78% | 72% |
| Low vegetation alone | 18% | 39% |
| Bare ground alone | 82% | 67% |
| Water | 83% | 100% |

What that means for using the map:

- **Tree canopy can be trusted.** Nine in ten cells mapped as canopy are
  canopy. The map misses about a fifth of what a person sees as canopy in the
  photo, mostly crown edges, some of it because tall trees lean in the photo.
- **Pavement is over-mapped inside parcels.** Of 28 pavement points that were
  right, 23 were in the street right-of-way; of 16 that were really bare
  ground, 14 were inside parcels: compacted dirt lots, rail ballast, shaded
  yards. Grey-tan dirt and faded asphalt overlap in every input the classifier
  has. For the planting scenario this errs on the safe side: it hides plantable
  ground and does not invent it.
- **Bare ground mapped where there is pavement** is the error that could put a
  tree on concrete: 7 of 48 bare-ground points, mostly sidewalks in the
  right-of-way. The planting rules have to keep clear of the street edge
  regardless of what the map says there.
- **Low vegetation is not usable as its own class.** Fewer than one in five
  cells mapped as low vegetation are; most are shade on bare soil. It is
  merged with bare ground as "open ground" from here on.

How the check was run, and its limits:

- The sample is stratified random: 25 points in each mapped class in each
  neighborhood (`07_accuracy_points.py`). The labelling page shows natural
  colour, colour infrared and a wide view, and not the map, the lidar or the
  class a point was drawn from.
- The map was revised once after the first scoring. The first map scored
  69.3% on six classes, 95.4% on tree canopy and 81.0% on impervious. The
  disagreements showed shade being mapped as low vegetation, so the rule for
  what counts as sunlit foliage was tightened and the map re-scored against
  the same labels (72.1%, 95.4%, 81.4%). The labels were not changed and
  canopy was not touched, but the ground-class scores of the revised map are
  no longer a fully independent test. First-map results are kept in
  `work/accuracy/accuracy_first_map.json`.
- The 300 labels took ten and a half minutes, a median of 1.4 seconds each.
  Of 16 disagreements looked at afterwards, the label was right in most. A
  slower repeat of a random subset would show how consistent the labelling is.
- Labelling rules agreed while labelling: go by the surface in the photo, not
  the use of the place (dry or dormant turf is bare ground); on an edge, label
  whichever surface fills more of the half-metre square.
- The lidar is from 2021 and the photo from 2023, so a tree planted or removed
  in between counts as a map error.

Things the data turned up:

- The point cloud already has a building class, so roofs come straight from
  the lidar and the machine-drawn county footprints are only a cross-check.
- There is no vegetation class. Trees are in "unclassified" along with cars,
  walls, poles and wires, which is why canopy needs greenness or porosity as
  well as height.
- Lidar intensity separates asphalt from pale soil and has no shadows, but
  does not separate asphalt from dark, compacted dirt.
- Cars parked in 2023 sit on ground the 2021 lidar saw empty, and leave
  speckle in parking lots.

`work/first_look_canopy.jpg` and `work/land_cover_both_sites.jpg` show both
sites side by side at one scale.

### Planting scenario

Plantable ground is open ground where a trunk would be 3 m from any roof, 1 m
from pavement, 2 m from an existing crown, 3 m from overhead lines (found in
the lidar), and, in the street, 10 m from an intersection. Street trees stay
within 5 m of street pavement. Yards are residential parcels only; parks and
schools take trees on their outer 10 m; commercial, industrial, rail and other
government land is left out. These distances are planning assumptions, not a
code or utility standard.

| Plantable ground, share of neighborhood | Dunbar Spring | Western Hills |
| --- | --- | --- |
| Street strip | 1.6% (0.97 ha) | 5.0% (2.34 ha) |
| Home yards | 1.5% (0.94 ha) | 14.4% (6.72 ha) |
| Park and school edges | 0.3% (0.19 ha) | none |

Trees are the four natives in `species.json`, at the mature sizes the Arizona
Municipal Water Users Association publishes: velvet mesquite 25 x 25 ft, blue
palo verde 30 x 30 ft, foothill palo verde 15 x 15 ft, desert willow 25 ft
tall and 20 ft wide. New trunks are at least 8 m apart. Spots that collect the
most roof and street runoff are filled first. A species must fit clear of
roofs and wires; among those that fit, the one furthest below its target
share is planted (30% mesquite, 25% each palo verde, 20% desert willow), and
desert willow goes only where runoff collects. The target shares and the
runoff rule are modelling choices.

| | Dunbar Spring | | Western Hills | |
| --- | --- | --- | --- | --- |
| | Trees | Canopy | Trees | Canopy |
| Today | | 18.5% | | 10.3% |
| 1 Street trees | 754 | 22.7% | 1,317 | 20.9% |
| 2 Streets and homes (two per home lot, park edges) | 1,140 | 24.4% | 2,039 | 25.9% |
| 3 Full build-out (upper bound) | 1,298 | 25.1% | 2,871 | 31.2% |

Canopy is at mature size, on the mapped (not error-corrected) base. Street
trees alone would take Western Hills from about half of Dunbar Spring's
canopy to slightly above where Dunbar Spring is today, and would cover 17% of
the pavement that is exposed now.

Runoff: a tree counts as runoff-fed when at least 50 m2 of roof and pavement
drains to within 2 m of it, which a basin or curb cut could tap. That is 81%
of the street trees in Western Hills and 61% in Dunbar Spring. The 50 m2
threshold is an assumption: at Tucson's 10.61 inches of rain a year it sheds
about 3,500 gallons before losses, the same order as the 4,500 gallons a year
the Dunbar Spring foresters say one of their basins harvests.

For scale: the Dunbar Spring foresters report over 1,700 trees planted since
1996, so 1,317 street trees for Western Hills is a programme of that size.

Known weaknesses of the placement:

- It trusts the land cover. Where a driveway or sidewalk is mapped as bare
  ground, a tree can land on it.
- There is no sidewalk layer, no underground utilities, no driveway sight
  lines, and no ownership check beyond parcel use codes.
- Which native suits which spot is decided by room and runoff only. Soil,
  frost pockets and the species' natural habitats are not considered.
- `work/scenario_both_sites.jpg` shows trees outside the boundaries too; the
  counts above are inside the boundaries only.

### Afternoon shade

Shadows are cast for 4 p.m. on 15 July (sun 42 degrees above the horizon,
due west), from tree crowns and roofs treated as solid. Share of each surface
in shade, inside the boundary:

| | Dunbar Spring | | | Western Hills | | |
| --- | --- | --- | --- | --- | --- | --- |
| | Street edge | Pavement | All open ground | Street edge | Pavement | All open ground |
| Today | 50.5% | 16.3% | 37.7% | 17.4% | 11.7% | 25.1% |
| 1 Street trees | 74.4% | 23.6% | 44.9% | 77.9% | 42.8% | 45.5% |
| 2 Streets and homes | 75.2% | 25.4% | 47.6% | 78.5% | 46.4% | 54.6% |
| 3 Full build-out | 75.5% | 26.3% | 48.9% | 79.1% | 49.9% | 63.7% |

"Street edge" is the 2 m band just outside street pavement, both sides: 26.5
km of it in Dunbar Spring and 20.4 km in Western Hills. There is no
sidewalk layer for either neighborhood, and on many of these streets that
band is where people walk. Today half of Dunbar Spring's street edge is
shaded at 4 p.m. and a sixth of Western Hills's (3.5 km of 20.4). Street
trees would shade 15.9 km of it.

Check on the method: the 2023 photo has shadows of its own but no published
time of day. Casting shadows from today's surface for each quarter hour of
the flight date and comparing with where bare ground is dark in the photo
gives a clear best match at 12:45 for Western Hills (shaded ground half as
bright as sunlit, 88% of cells agree) and at 10:45 for Dunbar Spring (weaker:
shaded ground about a quarter darker, 71% agree). Both are plausible flying
times, two hours apart on different flight lines. The weaker match at Dunbar
Spring is expected where more of the "bare ground" is mislabelled and crowns
overlap.

Limits: trees are solid in the model, so this is the footprint of shade and
not its quality; palo verde shade is thin. Low sun gets in under real crowns.
Wires, poles, walls and cars cast no shade here. New trees are at mature size.
The first run used the raw lidar height model and overhead wires cast solid
shadows along every street (Dunbar Spring's street edge read 70% shaded
today); the surface is now crowns and roofs only.

Tucson's normal annual rainfall is 10.61 inches (1991 to 2020 normals,
National Weather Service Tucson; Ben supplied a screenshot of the table on
14 November, page address still to be noted). At that rainfall, 50 m2 of roof
and pavement sheds about 13 cubic metres a year before losses, roughly 3,500
gallons.

### Carbon

Estimated from canopy area, not tree by tree: the canopy each scenario adds,
at mature size, times the carbon held per square metre of urban tree cover
in Nowak and others (2013), read from the paper on 14 November.

| | Dunbar Spring | | Western Hills | |
| --- | --- | --- | --- | --- |
| | Stored, t C | Net uptake, t C a year | Stored, t C | Net uptake, t C a year |
| 1 Street trees | 196 (79 to 360) | 6.7 | 383 (154 to 702) | 13.0 |
| 2 Streets and homes | 277 (112 to 508) | 9.4 | 561 (226 to 1,028) | 19.1 |
| 3 Full build-out | 314 (126 to 575) | 10.7 | 753 (303 to 1,380) | 25.6 |

Stored carbon uses the US average of 7.69 kg C per m2 of tree cover (standard
error 1.36). The bracketed range uses the lowest and highest city in the
paper, 3.1 and 14.1. None of its 28 cities is in the Sonoran Desert, and
open-crowned desert trees probably sit toward the low end, so the low figure
is the safer one to quote. Uptake uses the paper's Arizona rate of 0.354 kg C
per m2 a year, gross; net is 74% of gross. Multiply carbon by 3.667 for
carbon dioxide: 383 t C is about 1,400 t CO2.

This is for the trees once mature, decades out, and counts only the trees:
not soil, not energy saved by shade, not the emissions of planting and
watering. It works out at roughly 240 to 290 kg C a tree.

### Surface temperature

Landsat 8 and 9 surface temperature, pulled through Google Earth Engine
(`13_surface_temperature.py`): the median of 28 scenes from June to August
of 2021 to 2023, cloud-masked, at about 10:58 a.m. local time. Neighborhood
means are 53.1 C in Dunbar Spring and 53.7 C in Western Hills (128 and
129 F). Those are the temperatures of roofs, pavement, soil and leaves, not
of the air.

`14_heat.py` sums the land cover into 90 m blocks (309 across both sites)
and regresses temperature on the share of each block under tree canopy, roof
and pavement, with open ground as the baseline and a separate level for each
site. A block fully covered by a class differs from a block of open ground
by:

| Class | Difference | Standard error |
| --- | --- | --- |
| Tree canopy | -1.9 C | 0.8 |
| Pavement | +2.6 C | 0.4 |
| Roof | +2.9 C | 0.6 |

Applied to what the new crowns cover, the neighborhood's mean late-morning
surface temperature changes by:

| | Dunbar Spring | Western Hills |
| --- | --- | --- |
| 1 Street trees | -0.13 C | -0.28 C (-0.42 to -0.13) |
| 2 Streets and homes | -0.17 C | -0.39 C (-0.61 to -0.16) |
| 3 Full build-out | -0.19 C | -0.49 C (-0.79 to -0.20) |

That is a few tenths of a degree, half a degree Fahrenheit for street trees
in Western Hills. Report it as "slightly cooler", not as a number to lean
on:

- The fit is weak. Land cover explains 23% of the variation in temperature
  within the sites, and the leftover scatter (1.05 C) is larger than every
  change in the table.
- The canopy effect is not stable. Fitted separately it is -2.5 C in Dunbar
  Spring and -0.5 C in Western Hills, where canopy varies little from
  block to block (2% to 20%). Pavement and roof effects are steadier.
- The thermal sensor sees 100 m, so each block borrows from its neighbours.
  That pulls every coefficient toward zero and makes the intervals above too
  narrow.
- It is surface temperature at 11 a.m. The shade table is the better guide
  to what a person walking at 4 p.m. would feel.
- The original plan was a citywide canopy-to-temperature relationship.
  Canopy at this detail exists only for the two sites, so the fit comes from
  those two neighborhoods.

Check: in `work/lst_check.jpg` the coolest pixels sit on the irrigated turf
fields and the wash, so the temperature grid is in the right place.

### Habitat context and species records

Where each neighborhood sits (`16_context.py`, county layers):

| | Dunbar Spring | Western Hills |
| --- | --- | --- |
| Washes through or along it | Tucson Arroyo, West University Wash | 18th Street Wash, Greyhound Wash |
| Next nearest | Santa Cruz River, 367 m | Sunland Vista Wash, 172 m |
| Nearest mapped riparian habitat | 330 m | 4 m |
| Riparian habitat within 1 km | 196 ha | 65 ha |
| Adjoining open space | Estevan Park, Anza Park | Ajo Detention Basin, Willie Blake Jr. Community Park |

How broken up the canopy is. Crowns no more than 10 m apart count as one
cluster:

| | Dunbar Spring | | | Western Hills | | |
| --- | --- | --- | --- | --- | --- | --- |
| | Mean distance to a crown | Canopy in largest cluster | Linked to riparian | Mean distance to a crown | Canopy in largest cluster | Linked to riparian |
| Today | 6.3 m | 73% | 0% | 6.3 m | 5% | 1% |
| 1 Street trees | 4.4 m | 77% | 0% | 3.4 m | 98% | 98% |
| 2 Streets and homes | 4.1 m | 77% | 0% | 2.4 m | 99% | 99% |
| 3 Full build-out | 4.0 m | 78% | 0% | 1.8 m | 99% | 99% |

Dunbar Spring's canopy already hangs together: three-quarters of it is one
cluster. Western Hills' is scattered, with its largest cluster holding 5% of
its canopy and 1% reaching the riparian habitat mapped along the 18th Street
Wash on its edge. A row of street trees every 8 m joins nearly all of it into
one network that reaches the wash. This is a threshold effect: the 10 m gap
is a round number for illustration, not a crossing distance for any animal,
and a different gap would move these figures a long way. It describes how
broken up the canopy is, not habitat for a named species.

Species records (`17_species_records.py`): GBIF occurrence records since
2015, queried 14 November 2026. GBIF carries iNaturalist's research-grade
observations and eBird's observation dataset.

| | Dunbar Spring | | Western Hills | |
| --- | --- | --- | --- | --- |
| | Inside | Within 1 km | Inside | Within 1 km |
| All records | 1,833 | 18,236 | 2 | 109,208 |
| Species | 152 | 646 | 2 | 391 |
| Bird records | 1,698 | 16,732 | 0 | 108,870 |
| Bird species | 61 | 182 | 0 | 246 |
| Vascular plant species | 38 | 201 | 2 | 61 |
| Insect species | 33 | 178 | 0 | 63 |
| Reptile species | 5 | 27 | 0 | 7 |

These are records, not wildlife counts, and the table is mostly a picture of
where people look. Western Hills has two records inside it and 109,000
within a kilometre, 99% of them eBird checklists, almost all from the
detention basin next door (the insect list there is led by dragonflies,
which fits standing water). Nothing can be said about what lives on Western
Hills' own streets from this; nobody has recorded there. What it does show
is that a place with 246 recorded bird species sits a street's width from a
neighborhood whose canopy does not reach it.

All four trees in the planting have been recorded within a kilometre of both
neighborhoods.

Limits: GBIF's search API has no citable DOI; a formal report should repeat
the query as a GBIF download and cite that. Riparian class letters are the
county's and have not been looked up. The Ajo Detention Basin is named as
the county's park layer names it.

## Data

| Layer | Source | Notes |
| --- | --- | --- |
| Lidar point cloud | USGS 3DEP `AZ_PimaCounty_2021_B21` / `AZ_PimaCo_2_2021` | Flown 27 September to 17 November 2021, quality level 1 (8 or more points per m2), so mesquite was still in leaf. LAZ tiles (about 55 MB each) download straight from USGS, slowly; OpenTopography (Ben has an account) is the fallback. A second flight from February 2015 (leaf-off, quality level 2) covers the same ground and can show canopy change |
| Aerial imagery | NAIP 4-band, 30 cm, 18 October 2023, from the USGS NAIPPlus image service | Older years for the historical comparison |
| Neighborhood boundaries | City of Tucson open data | Name, status and ward only. The layer also carries officers' contact details, which are never requested |
| Building footprints | Pima County / City of Tucson, or Microsoft footprints | Exclusion layer |
| Street centerlines, right-of-way, parcels | Pima County GIS | Pavement mask and public/private split. No owner names are kept |
| Washes and riparian habitat, parks | Pima County GIS | Landscape context |
| Species occurrences | GBIF (which carries research-grade iNaturalist records and eBird's dataset) | Record counts follow where people look, so report them as records, not abundance |
| Land surface temperature | Landsat 8/9 thermal, summer scenes | 100 m thermal resampled to 30 m; surface, not air, temperature |
| Sanity checks | Pima Association of Governments resiliency maps | Compare canopy and temperature figures |

## Workflow

Scripts live in `tools/canopy/`, numbered in run order. Each takes optional
site ids and otherwise runs every site in `sites.json`. Large files go in
git-ignored `tucson-canopy/work/`.

Two Pythons are used. Downloads run in the system Python (`py`). Everything
that touches the geodatabase runs in ArcGIS Pro's Python (ArcPy, with Spatial
Analyst and 3D Analyst), shown below as `propy`:

    "%LOCALAPPDATA%\Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"

| Step | Script | Runs in | What it does |
| --- | --- | --- | --- |
| 0 | `tools/screen_canopy_sites.py` | py | Citywide neighborhood screen that picked the sites |
| 1a | `01_get_lidar.py` | py | Finds and downloads the USGS lidar tiles over each site |
| 1b | `02_get_imagery.py` | py | Site boundary and 4-band NAIP tiles at 0.3 m |
| 1c | `03_get_context.py` | py | County buildings, parcels, streets, washes, riparian habitat, parks, protected lands |
| 2 | `04_build_surfaces.py` | propy | Builds `work/<site>/<site>.gdb`: vectors, bare ground, top surface, canopy height, lidar porosity, NAIP mosaic, NDVI, first-pass canopy |
| 2b | `05_check_and_document.py` | propy | Tests every layer (CRS, coverage, geometry, grid, value range) into `qa_report.csv` and writes layer metadata |
| 3 | `06_land_cover.py` | propy | Six-class land cover. Lidar decides trees and roofs; a Random Trees classifier, trained on samples the script draws itself, decides pavement, low vegetation and bare ground |
| 3b | `07_accuracy_points.py` | propy | Stratified random accuracy sample (25 points per mapped class per site) and an image chip for each point |
| 3b | `label_server.py` + `tools/canopy-label/` | py | Local page for labelling the points from the 2023 photo without seeing the map. Preview config `canopy-label`, <http://localhost:8770/> |
| 3c | `08_accuracy.py` | propy | Error matrix, user's and producer's accuracy, area-weighted overall accuracy with a 95% interval, kappa, and error-corrected class shares |
| 5 | `09_plantable.py` | propy | Plantable ground by zone (street strip, home yard, park edge) after setbacks, and the roof and pavement area draining to each spot |
| 6-8 | `10_scenarios.py` | propy | Places trees from `species.json`, grows them to mature size, and builds three nested scenarios with canopy cover for each |
| 9b | `12_carbon.py` | py | Carbon stored and taken up by the canopy each scenario adds, from `carbon_factors.json` |
| 9c | `ee_signin.py`, `13_surface_temperature.py` | py | One-time Earth Engine sign-in; median June to August Landsat surface temperature for each site |
| 9c | `14_heat.py` | propy | Fits surface temperature to land cover in 90 m blocks and applies it to the scenarios |
| 4 | `16_context.py` | propy | Washes, riparian habitat and parks within 1 km, and how broken up the canopy is today and under each scenario |
| 4b | `17_species_records.py` | py | GBIF occurrence records since 2015 inside each boundary and within 1 km, by group |
| 10b | `18_layouts.py` | propy | Builds an ArcGIS Pro project from the blank one that ships with Pro, styles the maps, and exports four 16:9 layouts as PDF and PNG |
| 10c | `19_summary_workbook.py` | py | The Excel summary: every result, with gains, carbon and totals as formulas pointing at an Assumptions sheet |
| 10d | `20_package.py` | propy | Hand-over copy of each site's GIS files in open formats: a GeoPackage, GeoTIFFs and a layer list |
| 10a | `15_publish_web.py` | propy | Writes `tucson-canopy/data/`: the page's figures and its overlay images |
| 9a | `11_shade.py` | propy | Casts shadows for a date and time (default 15 July, 4 p.m.) today and under each scenario; `--check-photo` tests the shadow caster against the shadows in the 2023 photo |

Still to build:

4. **Baseline change over time.** Canopy change since the February 2015
   lidar flight and across older NAIP years. Not done; the 2015 flight was
   leaf-off, so it would undercount mesquite.
9. **Outcomes**, per site and scenario: canopy %, shaded sidewalk length at a
   July 4 p.m. sun, estimated surface temperature change (from the citywide
   canopy to Landsat temperature relationship), carbon stored at maturity,
   native share of canopy, canopy gap distances and connection to the wash,
   trees added by species, habitat score.
10. **Products.** Web page with before/after swipe map and full-page map; Pro
    layouts; Excel summary; geodatabase and GeoPackage; Blender render per
    site, before and after.

### Geodatabase layout

Every site gets the same layer names, so nothing downstream is site-specific.

| Layer | What it is |
| --- | --- |
| `boundary`, `work_area` | Neighborhood polygon; its box plus a 150 m buffer, which every raster covers |
| `buildings`, `parcels`, `streets` | County layers over the work area. Parcels carry number and use code only |
| `washes`, `riparian`, `parks`, `protected` | County layers out to 1 km |
| `dtm`, `dsm`, `chm` | Bare ground, top surface, and height above ground, 0.5 m cells |
| `multi_return` | Share of lidar returns in a cell from multi-return pulses. High in tree crowns, near zero on roofs |
| `naip_2023`, `ndvi` | Imagery at 0.3 m; NDVI on the lidar grid |
| `intensity` | Lidar return strength of single-return ground points: ground brightness with no shadows |
| `canopy_first` | First-pass canopy: 2.5 m or taller, and green or porous. Replaced by the land cover |
| `land_cover`, `land_cover_seeds` | The six-class map and the training points it was given |
| `accuracy_points` | The accuracy sample: `Classified` is the mapped class, `GrndTruth` the hand label |
| `plantable`, `overhead`, `street_corners` | Plantable zones and two of the things that rule ground out |
| `runoff_m2` | Roof and pavement area draining to within 2 m of each cell |
| `trees` | Proposed trees: species, scenario, zone, mature crown and height, runoff |
| `canopy_s1..s3`, `height_s0..s3` | Canopy, and height of crowns and roofs, today (s0) and under each scenario |
| `shade_s0..s3` | Ground in shade at 4 p.m. on 15 July, today and under each scenario |

## Limits to state in the write-up

- Lidar is from 2021 and the imagery from 2023.
- Saguaros and tall shrubs can read as trees in the canopy height model.
- Landsat gives surface temperature at coarse resolution, and the temperature
  change is an estimate from a citywide relationship.
- Species records reflect where observers go.
- Carbon figures are estimates for mature trees.
- The habitat score is illustrative, not a recognised metric for the Sonoran
  Desert.
- The scenario is a planning sketch, not a planting plan: no utility locates,
  ownership checks or irrigation design.

## Site page

Published 14 November 2026: `/tucson-canopy/` ("What Would
Street Trees Do for a Bare Tucson Neighborhood?") and `/tucson-canopy/map/`,
in the site's look, with a home page entry. The viewer is a swipe map: left
of the divider is today, right is the chosen planting. Settings pick the
neighborhood, the planting, and what to show (tree canopy with the proposed
trees by species, shade at 4 p.m. in July, or land cover). The settings ride
in the address (`?site=western_hills_ii&plant=1&show=canopy`) and carry
between the two pages.

The page uses Leaflet like the rest of the site: each side of the divider is its own map pane, clipped to its half.
Overlays are the 0.5 m rasters as transparent images placed by their corner
coordinates. Colours are the site palette's categorical slots; the palette
validator could not be run here (no Node on this machine).

Every figure on the page comes from `data/canopy.json`, so re-running
`15_publish_web.py` after any earlier step updates the page. No draft or
under-construction labels.

## Products besides the page

Made 14 November 2026.

- **Map layouts** (`downloads/*.pdf`, `*.png`): four 16:9 slides exported from
  ArcGIS Pro by `18_layouts.py`. Land cover for both neighborhoods; tree
  canopy today and with street trees for each; shade at 4 p.m. on 15 July in
  Western Hills. The project file is `work/tucson_canopy.aprx`; open it in
  Pro to restyle by hand. The legend and scale bar are drawn by the script,
  because Pro's own legend could not be laid out cleanly from ArcPy.
- **Summary workbook** (`downloads/tucson_canopy_summary.xlsx`): eight sheets.
  Scenarios is the main one. Checked by opening it in Excel and
  recalculating: 105 formulas, no errors, and the carbon figures match
  `12_carbon.py`.
- **GIS files** (`work/deliverable/<site>.zip`, not in the repository): a
  GeoPackage of eight vector layers, ten GeoTIFFs and `LAYERS.txt` for each
  site, 15 to 19 MB zipped. The parcel layer is left out.

Still to make: Blender renders.
