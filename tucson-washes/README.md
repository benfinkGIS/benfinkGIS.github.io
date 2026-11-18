# Tucson Wash Corridors

Map how wildlife could move between the Tucson Mountains and the Santa
Catalinas through the washes, parks and canopy of northwest Tucson, at the
finest detail the data allows, and show where the gaps are.

Portfolio project #2 for the Second Nature Ecology + Design GIS Analyst
application. Brought into this repo on 14 November 2026 from an outline
written outside it (`02-tucson-wash-corridors.md`); this file replaces that
outline. Project 1 is `tucson-canopy/`.

## Where it stands (15 November 2026)

All four stages are built. The page at `/tucson-washes/` (with `/map/` and a
home page entry) shows the wash network, its attributes and the road
crossings, reports a hand check of all three, carries a movement model for
the three species with a check against sightings, and ranks the gaps where a
repair would add the most movement. Stages 1 to 3 were published on 14 and
15 November; the stage 4 version of the page is built and checked locally.

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
| Candidate gaps rerun with a repair | 99; fifteen listed, five for each animal |
| Candidate gaps rerun with a repair | 99; fifteen listed, five for each animal |
| Movement model checked against sightings (0.5 is chance) | Flycatcher 0.68 (0.63 to 0.73); bobcat 0.50 (0.45 to 0.55); queen 0.50 (0.45 to 0.54) |

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

### Stage 3: connectivity (15 November 2026)

For each of the three species the study area is a 10 m grid (2,500 by 2,100
cells) with two surfaces: resistance, the cost of crossing a cell (1 is
easiest), and source strength, how much the cell counts as habitat (0 to 1).
Omniscape 0.6.2 (Julia 1.10.13) moves a circular window over the grid; at
each stop current is injected at the source cells inside the window and drawn
out at the centre, and the current through every cell is summed over all
stops. Dividing by the same sum run with resistance 1 everywhere ("flow
potential") gives normalized current, which shows where the ground
concentrates movement or blocks it.

Ground layers behind the surfaces (`14_surfaces.py`, all on the 10 m grid):

| Layer | From |
| --- | --- |
| Percent built on | NLCD 2021 impervious surface, 30 m, resampled |
| Tree canopy share | The 1 m imagery canopy from stage 1 |
| Green ground that is not canopy; turf | 2023 imagery: NDVI of 0.16 and up outside canopy; turf is NDVI of 0.30 and up with a smooth near-infrared texture |
| Roads by class | County centerlines widened by 5 to 12 m a side; the highest class in a cell wins, so a road cannot be slipped through diagonally |
| Washes by size | Reaches kept as washes: small (under 20 ha), medium, large (1,000 ha and up) |
| Riparian class | County riparian layer |
| Standing water | NHDPlus HR ponds and reservoirs (7,506 cells) plus water seen in the imagery on flat ground in patches of 300 m2 or more (280 cells) |
| Crossings | Stage 2 types within 25 m of each crossing point, plus the 43 National Bridge Inventory bridges over water as open spans across the whole road |

The numbers are in `resistance.json`. They are set by judgement. What each
leans on:

**Bobcat** (window radius 2.5 km; one solve per 25 by 25 cells).

- Radius: the Bobcats in Tucson collar study (Mollohan and others, technical
  report to Arizona Game and Fish, November 2024; 38 collared cats on the
  west side of Tucson) gives 95% kernel home ranges of 8.1 km2 for females
  and 19.6 km2 for males. A circle of 19.6 km2 has a radius of 2.5 km.
- Built ground: resistance rises with the square of percent impervious, from
  1 to 50, and is cut by up to half under vegetation cover. The same study
  found cats closer to buildings than random points and calls housing of up
  to about 500 buildings per km2 with native plants and intact washes high
  quality habitat, so light development is kept cheap. The Arizona Missing
  Linkages design for the Tucson, Tortolita and Santa Catalina Mountains
  (Beier and others 2006) scores desert scrub 4, low-intensity development 7
  and denser development 9 on a 1 to 10 cost scale, a much flatter scale
  than this one.
- Roads: the collar study counted road crossings against simulated random
  movement. Minor roads were crossed 8% less than chance (weak evidence),
  major roads 26% less, and Interstate 10 was "apparently a barrier", crossed
  by one cat, under an underpass. So minor streets add nothing, major roads
  15, Oracle Road 40, the interstate 1,000.
- Crossings: the study found the cats "did not select for culverts or under
  or overpasses when crossing roads" (1.3% of crossings were within 7 m of a
  structure), apart from two cats living along the Santa Cruz that went under
  the river bridges. So a typed culvert only cuts a road's cost to a fifth
  (never below 10), which matters on the interstate and little elsewhere; an
  open span costs 2.
- Sources: a cell is habitat in proportion to how little of the ground within
  300 m is built on, reaching zero at 30% impervious.

**Vermilion flycatcher** (radius 1.5 km). No published territory size
or movement distance was found, so the radius is a guess. Tucson Audubon
describes resident pairs in the city's parks; the species account in
California Bird Species of Special Concern (2008) lists golf courses, parks
and open ground with trees near water, and notes the bird avoids dense
riparian growth. Habitat
here is turf with at least some tree canopy within 100 m, halved away from
water. Resistance is low where trees and turf together cover 30% of a cell,
higher over bare desert (10) and higher again over solid development (to 30).

**Queen butterfly** (radius 1 km). No local movement distance was
found either; monarchs, as a stand-in, pick out host plants from up to 125 m
(Fisher and Bradbury 2021). The queen's larval hosts in the Sonoran Desert
include the climbing milkweeds (*Funastrum*), which grow along washes
(Saul-Gershenz and others 2020), so wash and riparian cells cost 1. Other
ground costs 1 to 5 by how green it is, plus up to 25 by percent impervious.
Roads carry no extra cost. Habitat is green cover within 100 m, with a floor
of 0.7 within 50 m of a wash or riparian strip.

Normalized current is classed impeded (under 0.7), diffuse (0.7 to 1.3),
intensified (1.3 to 1.7) and channelled (over 1.7). The breaks are attributed
to Cameron and others 2022 (doi 10.1111/csp2.12698); they were read in a
secondary source, not the paper.

#### Results

| | Bobcat | Vermilion flycatcher | Queen butterfly |
| --- | --- | --- | --- |
| Window radius | 2.5 km | 1.5 km | 1 km |
| Run time, 30 threads | 49.9 min | 3.5 min | 29.3 min |
| Area impeded (normalized current under 0.7) | 36% | 72% | 22% |
| Area diffuse (0.7 to 1.3) | 53% | 23% | 57% |
| Area intensified (1.3 to 1.7) | 9.0% | 2.5% | 9.2% |
| Area channelled (over 1.7) | 2.5% | 2.5% | 11.5% |
| Intensified or channelled ground within 30 m of a wash (28% of the area is) | 45% | 45% | 66% |
| Wash cells that are intensified or channelled | 23% | 10% | 97% |
| Median normalized current on wash cells | 1.07 | 0.35 | 1.99 |

Interstate 10 (bobcat run): 290 of 14,970 interstate cells are under an inventoried river bridge (the Rillito and the Canada del Oro). They carry 22% of the current on interstate cells, at 3.6 times the area's mean; the rest of the interstate carries 0.26 times the mean. Omniscape injects a fixed current, so a barrier redirects movement to the nearest weak point inside the window and cannot stop it; current on the closed cells is the model forcing its way through, not a prediction that cats cross there.

Culverts (bobcat): with every typed culvert closed against every one open (both at a coarser step of 51 cells), normalized current changes by more than 25% on 0.9% of wash cells and 0.3% of all cells. Reach values under the two runs correlate at 0.982 by rank, and 89% or more of the top tenth of reaches in the main run stay in the top tenth under either; part of that difference is the coarser step, not the culverts.

#### Check against sightings (`17_validate.py`)

Sightings follow observers, so each species' records are compared with every
other research-grade iNaturalist record of its group in the box (mammals,
birds, butterflies; 4,294, 43,480 and 6,838 records).
Records placed to 100 m or better, one per 100 m square; each surface
averaged over 50 m. The score is the chance that a record of the species sits
on a higher value than a record of something else in its group (0.5 is a coin
toss). Ranges are 95%, from resampling 1 km squares.

| | Bobcat | Vermilion flycatcher | Queen butterfly |
| --- | --- | --- | --- |
| Squares with a record of the species | 137 (from 331 records) | 485 (from 1,229 records) | 244 (from 583 records) |
| Squares with a record of the rest of its group | 1,038 | 3,816 | 1,083 |
| Current | 0.50 (0.45 to 0.55) | 0.68 (0.63 to 0.73) | 0.50 (0.45 to 0.54) |
| Normalized current | 0.51 (0.44 to 0.57) | 0.67 (0.61 to 0.71) | 0.48 (0.43 to 0.52) |
| Source strength (model input) | 0.48 (0.42 to 0.53) | 0.63 (0.60 to 0.67) | 0.53 (0.48 to 0.57) |
| 1 / resistance (model input) | 0.48 (0.41 to 0.54) | 0.63 (0.58 to 0.66) | 0.46 (0.41 to 0.51) |
| Current, against random points instead | 0.44 | 0.78 | 0.58 |
| Records per group record in the top fifth of the area by current, against the overall rate | 0.83 times | 1.76 times | 0.93 times |

Bobcat, current with every typed culvert closed: 0.50 (0.45 to 0.55); open: 0.50 (0.44 to 0.55).

What it says:

- **Flycatcher: supported.** Its records sit on higher current than other
  birds' records. The circuit model scores a little above its own inputs
  (0.68 against 0.63), but the ranges overlap, so it is not shown that the
  moving window adds to the habitat surface.
- **Bobcat: not distinguishable from chance.** Bobcat records fall on the
  same kind of ground as other mammal records. Against random points the
  score is below 0.5: sightings are where people live, and current is
  highest in open desert. This is not evidence the map is wrong, but nothing
  here shows it is right. The costs rest on the collar study's findings, not
  on this check.
- **Queen: not distinguishable from chance.** The queen surface gives washes
  the lowest cost by assumption, and 97% of wash cells come out as
  intensified or channelled. Queen records are no more common there than
  other butterflies' are. The source surface alone scores 0.64 against
  random points and 0.53 against other butterflies: butterflies of all kinds
  are recorded on green ground.

The page reports these three scores as they are.

#### Limits

- Every resistance number is a judgement. The check above tests the result
  against sightings; it does not tune the numbers, and a sighting is evidence
  of presence, not of movement.
- The box has no buffer. A window near the edge has less ground to draw on,
  so current falls away within one radius of the edge. Normalized current
  shares the same windows and is less affected.
- Built ground comes from a 30 m layer. A wash 10 m wide between back walls
  is carried by its own cells and by canopy, not by the impervious layer.
- The flycatcher map is the 1.5 km reach drawn around each patch of turf with
  trees. Where patches are further apart than that the map shows separate
  islands, and the edge of each island is the radius, not a finding.
- Culvert size is unknown. The two bobcat runs with every typed culvert
  closed and every one open bracket that; see the table.
- The bobcat collar study's ground lies mostly south and west of the box; its
  findings set the costs but its locations were not used.

### Stage 4: gaps (15 November 2026)

The question is the outline's step 7: where would one repair add the most
movement? It is answered by making the repair in the model and running it
again, 99 times.

#### Candidates (`18_gaps.py --shortlist`)

Each animal is stopped by different things, so each has its own kind of gap.
A repair changes that animal's resistance surface in a few cells and leaves
its habitat (source) surface alone.

| Animal | Gap | Repair in the model | Candidates |
| --- | --- | --- | --- |
| Bobcat | A wash meeting the Interstate 10 corridor: freeway, ramps, frontage roads and railroad crossings within 250 m of each other are one place | A straight strip 30 m wide across the whole corridor, square to the freeway, at the cost of an open span (2) | 16, every one not already under an inventoried river bridge |
| Bobcat | A wash crossing a state route (Oracle Road) that is not an open span | The cells within 25 m of the crossing at the cost of an open span | 13, every one |
| Bobcat | A wash of 20 ha or more crossing a major road, not an open span | The same | 20, the best by first guess, 300 m apart |
| Vermilion flycatcher | A stretch of wash, 200 to 800 m, with little perch cover | Canopy raised to 30% within 20 m of the line, which takes the perch term of the resistance to zero | 25, the best by first guess, 500 m apart |
| Queen butterfly | A run of street flow or unchannelled flow path, 50 to 800 m, with wash at both ends | The cells within 10 m of the line at the cost of a wash (1) | 25, the best by first guess, 400 m apart |

The first guess is the flow potential on the repair's cells (what uniform
ground would carry) times the share of the resistance the repair removes.
It only decides which candidates are run; the ranking comes from the reruns.

Lined channels, which the outline lists as a kind of gap, are not here: bed
material could not be mapped reach by reach (stage 2).

#### Reruns (`18_gaps.py --run`, `julia/gaps.jl`)

A repair can only change the moving windows that contain a repaired cell,
and each of those windows reaches one radius further. So each candidate is
run on a cut-out reaching two radii beyond it, once as the ground is and
once repaired, and only on the windows centred within one radius of it.
`gaps.jl` adds a method to Omniscape's `get_targets` that drops the other
windows. The difference between the two runs is then the same as the
difference between two runs of the whole grid.

That was tested on one candidate of each kind by also running every window
on the cut-out: the largest difference in any cell was 4 billionths of a
unit of current, against changes of up to 2,409 units. A bobcat candidate
took about 50 seconds for the pair of runs, a flycatcher or queen candidate
about 15, on 30 threads; the full bobcat grid takes 50 minutes once.

Bobcat reruns step the window 51 cells at a time, as its
culvert runs do, instead of 25. 7 bobcat candidates (ranks 1, 2, 3, 5, 7, 9, 13) were rerun at the main run's step of 25 cells. The added movement changed by at most 6% and the order did not change.

#### Measure (`18_gaps.py --score`)

Added movement is the change in current summed over the repair and the
ground within 50 m of it, divided by the repair's length along
the wash, in units of the study area's mean current per cell. Counting the
50 m either side cancels movement that only steps sideways onto
the repaired strip. "Movement now" and "with repair" are normalized current
on the repair's own cells (current over flow potential; flow potential does
not change with the repair).

Spread of added movement by kind:

| Animal | Kind of gap | Tried | Best | Median | Worst |
| --- | --- | --- | --- | --- | --- |
| Bobcat | interstate | 16 | 228.3 | 39.8 | 2.7 |
| Bobcat | major road | 20 | 19.7 | 12.6 | 5.4 |
| Bobcat | state route | 13 | 17.7 | 2.9 | 0.0 |
| Vermilion flycatcher | planting | 25 | 92.6 | 37.0 | 5.7 |
| Queen butterfly | link | 25 | 9.8 | 6.6 | 3.6 |

#### The listed gaps

The best five for each animal with no two closer than
1.5 km. "Added" is relative to that animal's best gap
(100). Place, present state and repair are hand-written in
`gaps_notes.json` from the 2023 photos and the county street and park
layers. Nobody has visited these places.

| Gap | Where | There now | Repair | Movement now | With repair | Added | Rank of those tried |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | Interstate 10 between Twin Peaks Road and Avra Valley Road (near the map edge) | Drainage culverts under the freeway and the railroad, in open desert beside the Santa Cruz River | A wildlife underpass under the freeway, frontage road and railroad together, with fencing to lead animals to it | 0.8 | 20.5 | 100 | 1 of 49 |
| B2 | Hardy Wash at Interstate 10, 800 m south-east of Twin Peaks Road | Culverts under the freeway and the railroad, between a shopping centre and a gravel pit | Enlarge the Hardy Wash culverts to a span an animal can walk through, and fence the approaches | 1.0 | 21.1 | 52 | 5 of 49 |
| B3 | Interstate 10, 900 m north-west of Ina Road | A culvert under the freeway and the railroad, with industrial yards on the west side | Enlarge the culvert to a walk-through span; the yards on the west side limit what it would reach | 0.9 | 12.8 | 22 | 7 of 49 |
| B4 | Interstate 10, 350 m south-east of Cortaro Road | A culvert under the freeway, with a shopping centre on the west side | Enlarge the culvert to a walk-through span; least promising of the freeway sites on the ground | 1.0 | 14.6 | 17 | 9 of 49 |
| B5 | Thornydale Road, 450 m south of Tangerine Road (near the map edge) | A two-lane road crossing the wash at grade, open desert on both sides | A box culvert large enough to walk through when the road is next widened; until then the crossing is at road level | 0.9 | 2.2 | 9 | 12 of 49 |
| F1 | Cañada del Oro Wash between golf fairways, west of La Cholla Boulevard | Wide sandy bed with 13% tree canopy along it, fairways on both sides | Plant native bank trees (mesquite, desert willow) along 870 m so the trees on the two sides become one strip | 1.3 | 1.9 | 100 | 1 of 25 |
| F2 | Unnamed wash through the golf course by Arthur Pack Regional Park | Desert wash between fairways and two ponds, 11% canopy | Plant trees along 710 m of the wash, pond to pond | 1.2 | 1.9 | 84 | 2 of 25 |
| F3 | Side channel on the Santa Cruz floodplain, between Twin Peaks and Cortaro roads | Bare floodplain between the river and a golf course, under 1% canopy | Plant a line of trees along 960 m of the side channel, from the golf course to the river | 0.9 | 2.2 | 72 | 8 of 25 |
| F4 | Santa Cruz River between Sweetwater Wetlands and Silverbell Golf Course | Banked river channel with 8% canopy along it | Plant the bank tops along 1.3 km to join the wetland's trees to the golf course's | 1.3 | 2.1 | 56 | 11 of 25 |
| F5 | Unnamed wash east of La Cholla Boulevard, south of Naranja Drive | Short desert wash between houses and a fairway, 15% canopy | Fill in trees along 290 m of wash | 1.2 | 2.1 | 41 | 12 of 25 |
| Q1 | Christmas Wash north of Fort Lowell Road, west of Country Club Road | The wash runs down residential streets for 580 m | Curb-cut rain gardens along the streets, planted with native milkweeds and nectar plants | 1.0 | 4.0 | 100 | 1 of 25 |
| Q2 | Unnamed wash through apartments off La Reserve Drive, east of Oracle Road | 240 m through parking courts | A planted swale through the parking courts | 0.9 | 3.0 | 85 | 2 of 25 |
| Q3 | Unnamed wash south of Orange Grove Road, between La Cañada Drive and Oracle Road | No channel for 650 m, along the road and through a neighbourhood | A roadside swale and yard-edge planting to carry the strip through | 0.9 | 3.2 | 84 | 3 of 25 |
| Q4 | Unnamed wash by the shops at La Cañada Drive and Lambert Lane | 340 m across Lambert Lane and an apartment car park | A planted strip along the car park edge, down to the wash | 0.7 | 2.5 | 82 | 4 of 25 |
| Q5 | Unnamed wash across a residential street west of Interstate 10, north of Cortaro Road | 150 m of street and house lots between two green strips | Street-side planting to join the two strips | 0.8 | 2.6 | 80 | 5 of 25 |

What it says:

- **Bobcat.** 5 of the six best candidates are
  within 3 km of B1 on Interstate 10, from Avra Valley Road to just past
  Twin Peaks Road; the spacing rule lists them as B1 and B2. Opening a culvert there takes it from about
  the movement of open ground to about twenty times that, because the
  freeway is otherwise closed between the river bridges. The best Oracle
  Road crossing adds 8% as much as B1 and the best
  major-road crossing 9%: by the collar study's
  findings those roads slow bobcats and do not stop them, and the costs
  follow that.
- **Independent support for B1.** Arizona Sonoran News (17 April 2025,
  https://arizonasonorannews.com/?p=40156, first published by Arizona
  Luminaria) reports an Arizona Game and Fish biologist describing the
  stretch between Twin Peaks Road and West Avra Valley Road as one of the
  few places along I-10 where wildlife can cross, an existing underpass
  there, and Pima County's Santa Cruz River Wildlife Ramp beside El Rio
  Preserve, then expected to be finished by June 2025. Tucson Spotlight
  (21 April 2025, https://www.tucsonspotlight.org/rta-budget-cut/) mentions
  the same abandoned underpass. Neither is in the model: it has open spans
  only at inventoried bridges over water. A site visit should start at that
  underpass. Whether the ramp was finished was not confirmed.
- **Flycatcher.** The gaps are washes that pass between golf courses, parks
  and ponds with few trees of their own. This is the only list resting on a
  model the sightings support.
- **Queen.** Every listed gap is a wash that was built over and now runs
  down a street or through a car park. The gains are close together, so the
  order means little.

#### The static map (`19_hero_map.py`)

`downloads/wash_corridors_gaps.png` (3840 x 2160) and a 1600-pixel JPEG for
the page: the 2023 imagery in grey, ground that is intensified or channelled
for one, two or all three animals (`data/funnel_all.png` on the web map,
"All three"), the freeway and Oracle Road, and the fifteen gaps with the
list beside them. Tag positions that collide are moved by hand in `NUDGE`.

#### Limits

- The sighting check carries over: only the flycatcher model beat chance, so
  the bobcat and queen lists show what the chosen costs imply.
- Omniscape injects a fixed current, so a repair shows up as movement drawn
  to the gap from somewhere harder. A gap that is already the only way
  through gains little by this measure even where opening it would help.
- Only resistance changes. Planting that would itself become habitat (a
  source) is undercounted, most of all for the queen.
- One repair at a time. Two repairs on the same wash may be worth more or
  less together than their sum; combinations were not run.
- Candidates within one window radius of the edge of the box are understated
  (marked in the table).
- The queen's washes cost 1 whatever grows in them, so a bare wash is not a
  gap for it. Only missing stretches can register.
- No costs, ownership, flood engineering or feasibility. The list is a
  shortlist for a site visit.

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
| Land cover and canopy from Project 1 | Project 1 covers two neighborhoods of about half a square kilometer each, and neither is in this area | It cannot be extended. See change 1 below |
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

1. **Canopy and land cover.** Rebuilding Project 1's half-meter land cover
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
   with each candidate gap repaired. A repair can only change the moving
   windows that contain it, so each rerun covers a cut-out around the gap and
   takes seconds to a minute, not the whole grid; 99 candidates were run.
   Lined reaches are not among them: bed material could not be mapped
   (stage 2), so there is no list of lined reaches to repair.
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
| 8a | `13_get_landcover.py` | py | NLCD 2021 impervious surface, NHD ponds, and every research-grade iNaturalist mammal, bird and butterfly record in the box (position and accuracy only) as the measure of observer effort |
| 8b | `14_surfaces.py` | propy | Ground layers on a 10 m grid, then a resistance and a source surface per species from `resistance.json`; `--layers` rebuilds the ground layers, `--look` writes check pictures |
| 8c | `15_omniscape.py` | py + Julia | Runs Omniscape for each species, and for the bobcat with every typed culvert closed and every one open |
| 8d | `16_connectivity.py` | propy | Reads the runs back, writes `data/funnel_<species>.png` for the map, the mean normalized current along each wash reach (`flow_<species>` on `reaches`) and `work/connectivity/summary.json` |
| 8e | `17_validate.py` | py | Scores each current map against sightings, corrected for observer effort; writes `work/connectivity/validation.json` |
| 9 | `08_reaches.py --export` | propy | Writes `data/channels.geojson`, `data/crossings.geojson` and `data/washes.json` for the page |
| 10 | `18_gaps.py` + `julia/gaps.jl` | propy + Julia | `--shortlist` picks candidate gaps, `--run` reruns Omniscape around each with and without its repair, `--score` ranks them and writes `data/gaps.json`. Place names and actions for the listed gaps are hand-written in `gaps_notes.json` |
| 11 | `19_hero_map.py` | py | The static 16:9 map with the gap list, `downloads/wash_corridors_gaps.jpg` and a 1600-pixel copy |

`propy` is ArcGIS Pro's Python:

    "%LOCALAPPDATA%\Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"

Run order after a change to `rules.json`: 08, 09, 10, then 14 with
`--layers`, 15, 16, 17 and 08 with `--export` (08 rebuilds `reaches`, which
drops the `flow_` fields until 16 is run again). After a change to
`resistance.json` only: 14, 15, 16, 17, 08 with `--export`, then 18 (all three
flags) and 19. Steps 11 and 12 are the one-off hand check; do not redraw the
sample. If the listed gaps change, their ids change with them: add notes for
the new ids to `gaps_notes.json` and run 18 with `--score` again.

Julia is a portable install (1.10.13, unzipped under
`%LOCALAPPDATA%\Programs\Julia`); `15_omniscape.py` finds it there, or set
`JULIA`. The package environment is `tools/washes/julia/`. Run times on 30
threads: bobcat 50 minutes, queen 29, flycatcher 3.5, each culvert variant 13.
Omniscape must run in double precision here; single fails the solver's
accuracy check.

All four stages are built.

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

The connectivity grids are in `work/connectivity/`: `layers_10m.npz` (ground
layers), `<species>_resistance.tif` and `<species>_source.tif`,
`run_<name>/` (Omniscape output), `arrays/` and the two JSON summaries.

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

Nothing outstanding. Julia and Omniscape were installed on 15 November with
his go-ahead, and the hand check is done.

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
