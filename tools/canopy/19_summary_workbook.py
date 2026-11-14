"""Step 10c: the spreadsheet summary of every result.

Runs in the system Python (needs openpyxl):

  py tools/canopy/19_summary_workbook.py

Writes tucson-canopy/downloads/tucson_canopy_summary.xlsx from the JSON files
the earlier steps wrote. Sheets:

  Read me            what the workbook is, sources, how to read it
  Scenarios          one row per neighborhood and planting: every outcome
  Land cover         mapped and error-corrected shares
  Accuracy           overall and per-class accuracy, and the error matrix
  Trees by species   counts and shares per planting
  Species records    GBIF records by group, inside and within 1 km
  Context            washes, riparian habitat and parks near each site
  Assumptions        every factor and rule, with its source

Measured results are written as values. Anything derived from them (gains,
carbon, carbon dioxide, totals, shares) is a formula that points at the
Assumptions sheet, so changing a factor there changes the results.
Percentages are stored as fractions and shown as percentages.

Open the file in Excel once and save it, or run the check in the README, so
the formulas have values before it is read by another program.
"""
import json

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from common import CONFIG, PROJECT, WORK, site_dir, sites

OUT = PROJECT / "downloads"
FONT = "Arial"
HEAD = PatternFill("solid", start_color="D9D9D9")
BAND = PatternFill("solid", start_color="F2F2F2")
THIN = Side(style="thin", color="A6A6A6")
SCEN = ["Today", "Street trees", "Streets and homes", "Full build-out"]
PCT, PCT1, NUM, NUM1, NUM2 = "0%", "0.0%", "#,##0", "#,##0.0", "0.00"


def style_sheet(ws, widths, header_row=1, freeze="A2"):
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                c.font = Font(name=FONT, size=10, bold=c.font.bold, italic=c.font.italic)
    for c in ws[header_row]:
        if c.value is not None:
            c.font = Font(name=FONT, size=10, bold=True)
            c.fill = HEAD
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = Border(bottom=THIN)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    if freeze:
        ws.freeze_panes = freeze


def main():
    OUT.mkdir(exist_ok=True)
    species = json.loads((PROJECT / "species.json").read_text(encoding="utf-8"))
    carbon = json.loads((PROJECT / "carbon_factors.json").read_text(encoding="utf-8"))
    acc = json.loads((WORK / "accuracy" / "accuracy.json").read_text())
    heat = json.loads((WORK / "heat.json").read_text())
    city = json.loads((WORK / "heat_citywide.json").read_text())
    eco = json.loads((WORK / "heat_ecostress.json").read_text())
    data = {}
    for s in sites():
        d = site_dir(s)
        load = lambda name: json.loads((d / name).read_text())
        data[s["id"]] = dict(
            site=s, land=load("land_cover.json"), plant=load("plantable.json"),
            scen=load("scenarios.json"), shade=load("shade.json"), ctx=load("context.json"),
            rec=load("species_records.json"), summ=load("summary.json"))

    wb = Workbook()

    # ---- Assumptions (written first: other sheets point at it) -------------
    wa = wb.active
    wa.title = "Assumptions"
    wa.append(["Item", "Value", "Unit", "Source or note"])
    ref = {}
    sh0 = next(iter(data.values()))["shade"]
    rules = next(iter(data.values()))["plant"]["rules"]
    srules = next(iter(data.values()))["scen"]["rules"]
    rows = [
        ("storage", "Carbon stored per m2 of tree cover", carbon["storage_kgC_per_m2"], "kg C / m2",
         "US urban average, Nowak et al. 2013, Environmental Pollution 178:229-236. Standard error 1.36"),
        ("storage_low", "Lowest city in that study", carbon["storage_city_range"][0], "kg C / m2",
         "Same source. No Sonoran Desert city was sampled; desert trees probably sit low"),
        ("storage_high", "Highest city in that study", carbon["storage_city_range"][1], "kg C / m2", "Same source"),
        ("uptake", "Gross carbon uptake per m2 of tree cover a year, Arizona",
         carbon["gross_sequestration_arizona_kgC_per_m2_yr"], "kg C / m2 / yr",
         "Same source, Table 3: the sample average adjusted for Arizona's growing season"),
        ("net", "Net uptake as a share of gross", carbon["net_share_of_gross"], "share", "Same source"),
        ("co2", "Carbon dioxide per unit of carbon", "=44/12", "t CO2 / t C", "Ratio of molecular weights"),
        ("rain", "Tucson normal annual rainfall", 10.61, "inches",
         "National Weather Service Tucson, 1991-2020 normals"),
        ("fed", "Roof and pavement draining to a tree for it to count as runoff-fed",
         srules["runoff_fed_m2"], "m2", "Planning assumption"),
        ("fed_gal", "Runoff from that area in a normal year, before losses", None, "gallons",
         "Formula: area x rainfall. For scale: Dunbar Spring's foresters report 4,500 gallons a year per basin"),
        ("spacing", "Least distance between new trunks", srules["spacing_m"], "m", "Planning assumption"),
        ("per_lot", "Trees per home lot in 'Streets and homes'", srules["per_lot"], "trees", "Planning assumption"),
        ("building", "Trunk to nearest roof", rules["building_m"], "m", "Planning assumption"),
        ("pavement", "Trunk to mapped pavement", rules["pavement_m"], "m", "Planning assumption"),
        ("canopy", "Trunk to an existing crown", rules["canopy_m"], "m", "Planning assumption"),
        ("overhead", "Trunk to overhead lines found in the lidar", rules["overhead_m"], "m", "Planning assumption"),
        ("corner", "Trunk to a street intersection", rules["corner_m"], "m", "Planning assumption"),
        ("strip", "Street trees stay this close to street pavement", rules["street_strip_m"], "m", "Planning assumption"),
        ("park", "Parks and schools take trees on this outer rim", rules["park_edge_m"], "m", "Planning assumption"),
        ("gap", "Crowns this close count as one linked cluster",
         next(iter(data.values()))["ctx"]["rules"]["gap_m"], "m",
         "Illustrative round number, not a crossing distance for any animal"),
        ("sun_el", "Sun elevation for the shade model", sh0["sun_elevation"], "degrees",
         "4 p.m. Mountain Standard Time, 15 July; NOAA solar equations"),
        ("sun_az", "Sun azimuth for the shade model", sh0["sun_azimuth"], "degrees", "Same"),
        ("tree_min", "Least height counted as tree canopy", 2.5, "m", "Lidar height above ground"),
        ("heat_local", "Late-morning surface cooling per ten points of canopy, blocks compared within 1.8 km",
         round(-city["local"]["canopy_lidar_units"] / 10, 2), "C",
         f"Landsat summer median against canopy, pavement and elevation over {city['blocks']:,} built-up "
         "90 m blocks in Tucson; step 23. Used in the Scenarios sheet"),
        ("heat_plain", "The same, blocks compared across the whole city",
         round(-city["plain"]["canopy_lidar_units"] / 10, 2), "C",
         "Upper figure: includes whatever else differs between leafy and bare parts of town"),
        ("heat_local_pm", "Afternoon surface cooling per ten points of canopy, blocks compared within 1.8 km",
         round(-eco["local"]["canopy_lidar_units"] / 10, 2), "C",
         f"ECOSTRESS, {eco['scenes_used']} clear scenes from June to August of {min(eco['years'])} to "
         f"{max(eco['years'])}, typically about 2:30 p.m., on the same blocks; step 25. Used in the Scenarios sheet"),
        ("heat_plain_pm", "The same, blocks compared across the whole city",
         round(-eco["plain"]["canopy_lidar_units"] / 10, 2), "C",
         "Upper figure for the afternoon"),
        ("heat_two", "Late-morning cooling from the two study neighborhoods alone",
         round(-heat["coefficients_vs_open_ground"]["tree"]["degC"] / 10, 2), "C",
         f"Step 14, {heat['blocks']} blocks; canopy varies too little there to pin it down"),
    ]
    for key, label, value, unit, note in rows:
        wa.append([label, value, unit, note])
        ref[key] = f"Assumptions!$B${wa.max_row}"
    r = int(ref["fed_gal"].split("$")[-1])
    wa.cell(r, 2, f"={ref['fed']}*{ref['rain']}*0.0254*264.172")
    wa.cell(r, 2).number_format = NUM
    wa.cell(int(ref["co2"].split("$")[-1]), 2).number_format = "0.000"
    wa.cell(int(ref["net"].split("$")[-1]), 2).number_format = PCT
    for sp in species["species"]:
        wa.append([f"Mature size, {sp['common']} ({sp['latin']})",
                   f"{sp['height_ft']} ft tall, {sp['width_ft']} ft wide", "",
                   f"Arizona Municipal Water Users Association, {sp['url']}"])
    style_sheet(wa, [56, 22, 16, 100])
    for row in wa.iter_rows(min_row=2):
        row[3].alignment = Alignment(wrap_text=True, vertical="top")

    # ---- Scenarios ---------------------------------------------------------
    ws = wb.create_sheet("Scenarios", 0)
    head = ["Neighborhood", "Planting", "Trees planted", "Tree canopy", "Canopy gain, points",
            "Canopy added, ha", "Street edge in shade, 4 p.m. 15 July", "Street edge gain, points",
            "Pavement in shade", "All open ground in shade", "Carbon stored once mature, t C",
            "Low, t C", "High, t C", "As carbon dioxide, t CO2", "Net uptake once mature, t C / yr",
            "Summer surface temperature change at about 11 a.m., C, citywide fit within 1.8 km",
            "The same at about 2:30 p.m., C",
            "Mean distance to nearest crown, m", "Canopy in largest linked cluster",
            "Canopy linked to riparian habitat", "Trees where runoff collects"]
    ws.append(head)
    for sid, dd in data.items():
        first = ws.max_row + 1
        for i, name in enumerate(SCEN):
            sc = dd["scen"]["scenarios"].get(name)
            sh = dd["shade"]["scenarios"][name]
            st = dd["ctx"]["structure"][name]
            r = ws.max_row + 1
            ht = city["sites"][sid].get(name)
            pm = eco["sites"][sid].get(name)
            ws.append([
                dd["site"]["name"], name, sc["trees"] if sc else 0,
                (sc["canopy_pct"] if sc else dd["scen"]["existing"]["canopy_pct"]) / 100,
                f"=(D{r}-D{first})*100", sc["canopy_added_ha"] if sc else 0,
                sh["street edge"] / 100, f"=(G{r}-G{first})*100", sh["pavement"] / 100,
                sh["open ground"] / 100,
                f"=F{r}*10000*{ref['storage']}/1000", f"=F{r}*10000*{ref['storage_low']}/1000",
                f"=F{r}*10000*{ref['storage_high']}/1000", f"=K{r}*{ref['co2']}",
                f"=F{r}*10000*{ref['uptake']}*{ref['net']}/1000",
                ht["local"]["change_degC"] if ht else 0,
                pm["local"]["change_degC"] if pm else 0,
                st["mean_distance_to_canopy_m"], st["largest_cluster_share"],
                st["linked_to_riparian_share"] if st["linked_to_riparian_share"] is not None else "n/a",
                sc["runoff_fed_share"] if sc else "n/a"])
            for col, fmt in ((3, NUM), (4, PCT1), (5, NUM1), (6, NUM2), (7, PCT), (8, NUM1), (9, PCT),
                             (10, PCT), (11, NUM), (12, NUM), (13, NUM), (14, NUM), (15, NUM1),
                             (16, NUM2), (17, NUM2), (18, NUM1), (19, PCT), (20, PCT), (21, PCT)):
                ws.cell(r, col).number_format = fmt
            if i == 0:
                for c in ws[r]:
                    c.fill = BAND
    style_sheet(ws, [18, 20] + [14] * 19, freeze="C2")
    ws.row_dimensions[1].height = 66
    note = ws.max_row + 2
    ws.cell(note, 1, "Canopy, shade and carbon are for trees at their published mature size. Each planting "
                     "includes the one above it. Carbon and gains are formulas; factors are on the "
                     "Assumptions sheet. Canopy figures are on the mapped base, not the error-corrected one.")
    ws.cell(note, 1).font = Font(name=FONT, size=10, italic=True)

    # ---- Land cover --------------------------------------------------------
    wl = wb.create_sheet("Land cover")
    wl.append(["Neighborhood", "Class", "Mapped share", "Error-corrected share", "Note"])
    for sid, dd in data.items():
        share = dd["land"]["share_pct"]
        corr = acc["sites"][sid]["open ground merged"]["corrected_share"]
        start = wl.max_row + 1
        for cls, mapped in (("Tree canopy", share["Tree canopy"]), ("Roof", share["Roof"]),
                            ("Pavement", share["Pavement"]),
                            ("Open ground", share["Low vegetation"] + share["Bare ground"])):
            wl.append([dd["site"]["name"], cls, mapped / 100, corr[cls],
                       "Bare ground and low plants together" if cls == "Open ground" else ""])
        r = wl.max_row + 1
        wl.append([dd["site"]["name"], "Impervious (roof + pavement)", f"=C{start + 1}+C{start + 2}",
                   f"=D{start + 1}+D{start + 2}", "Formula"])
        for rr in range(start, r + 1):
            wl.cell(rr, 3).number_format = PCT1
            wl.cell(rr, 4).number_format = PCT1
        for c in wl[r]:
            c.font = Font(name=FONT, size=10, bold=True)
    style_sheet(wl, [18, 30, 14, 20, 44])

    # ---- Accuracy ----------------------------------------------------------
    wc = wb.create_sheet("Accuracy")
    wc.append(["Area", "Question asked of the map", "Points", "Overall accuracy", "95% low", "95% high", "Kappa"])
    labels = {"tree canopy or not": "Tree canopy or not", "impervious or not": "Roof or pavement, or not",
              "open ground merged": "Five classes (open ground merged)", "all classes": "All six classes"}
    for area, block in acc["sites"].items():
        name = "Both neighborhoods" if area == "both sites" else CONFIG_NAME[area]
        for q, lab in labels.items():
            b = block[q]
            wc.append([name, lab, b["points"], b["overall_accuracy"], b["overall_95"][0],
                       b["overall_95"][1], b["kappa"]])
            for col in (4, 5, 6):
                wc.cell(wc.max_row, col).number_format = PCT1
    wc.append([])
    start = wc.max_row + 1
    wc.append(["Both neighborhoods", "Class", "", "User's accuracy", "Producer's accuracy"])
    for c in wc[start]:
        c.font = Font(bold=True)
        c.fill = HEAD
    both = acc["sites"]["both sites"]
    for cls in both["open ground merged"]["classes"]:
        wc.append(["", cls, "", both["open ground merged"]["users"][cls],
                   both["open ground merged"]["producers"][cls]])
    for cls in ("Low vegetation", "Bare ground"):
        wc.append(["", cls + " (alone)", "", both["all classes"]["users"][cls],
                   both["all classes"]["producers"][cls]])
    for rr in range(start + 1, wc.max_row + 1):
        wc.cell(rr, 4).number_format = PCT
        wc.cell(rr, 5).number_format = PCT
    wc.append([])
    m0 = wc.max_row + 1
    classes = both["all classes"]["classes"]
    wc.append(["Error matrix, both neighborhoods", "Mapped \\ labelled"] + classes + ["Row total"])
    for c in wc[m0]:
        c.font = Font(bold=True)
        c.fill = HEAD
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for cls, row in zip(classes, both["all classes"]["matrix"]):
        r = wc.max_row + 1
        last = get_column_letter(2 + len(classes))
        wc.append(["", cls] + row + [f"=SUM(C{r}:{last}{r})"])
    r = wc.max_row + 1
    wc.append(["", "Column total"] + [f"=SUM({get_column_letter(3 + i)}{m0 + 1}:{get_column_letter(3 + i)}{r - 1})"
                                      for i in range(len(classes) + 1)])
    for c in wc[r]:
        c.font = Font(bold=True)
    wc.append([])
    wc.append([f"{acc['skipped']['cant_tell']} points the labeller could not call are left out. Overall "
               "accuracy weights each mapped class by its share of the map; the matrix is raw counts. "
               "The map was revised once after the first scoring and re-scored against the same labels."])
    wc.cell(wc.max_row, 1).font = Font(italic=True)
    style_sheet(wc, [30, 34, 12, 16, 16, 12, 12, 12, 12])

    # ---- Trees by species --------------------------------------------------
    wt = wb.create_sheet("Trees by species")
    names = [sp["common"] for sp in species["species"]]
    wt.append(["Neighborhood", "Planting"] + names + ["Total"] + [f"{n}, share" for n in names])
    for sid, dd in data.items():
        for name in SCEN[1:]:
            by = dd["scen"]["scenarios"][name]["by_species"]
            r = wt.max_row + 1
            total = get_column_letter(3 + len(names))
            wt.append([dd["site"]["name"], name] + [by.get(n, 0) for n in names] +
                      [f"=SUM(C{r}:{get_column_letter(2 + len(names))}{r})"] +
                      [f"={get_column_letter(3 + i)}{r}/${total}{r}" for i in range(len(names))])
            for i in range(len(names) + 1):
                wt.cell(r, 3 + i).number_format = NUM
            for i in range(len(names)):
                wt.cell(r, 4 + len(names) + i).number_format = PCT
    style_sheet(wt, [18, 20] + [14] * (2 * len(names) + 1))
    wt.row_dimensions[1].height = 30

    # ---- Species records ---------------------------------------------------
    wr = wb.create_sheet("Species records")
    wr.append(["Neighborhood", "Group", "Records inside", "Species inside", "Records within 1 km",
               "Species within 1 km", "Most recorded within 1 km"])
    for sid, dd in data.items():
        a, b = dd["rec"]["areas"]["inside"], dd["rec"]["areas"]["within_1km"]
        for g in b["groups"]:
            wr.append([dd["site"]["name"], g, a["groups"][g]["records"], a["groups"][g]["species"],
                       b["groups"][g]["records"], b["groups"][g]["species"],
                       ", ".join(x["common"] or x["latin"] for x in b["groups"][g]["top"][:4])])
        wr.append([dd["site"]["name"], "Everything", a["all"]["records"], a["all"]["species"],
                   b["all"]["records"], b["all"]["species"], ""])
        for c in wr[wr.max_row]:
            c.font = Font(bold=True)
    for row in wr.iter_rows(min_row=2, min_col=3, max_col=6):
        for c in row:
            c.number_format = NUM
    wr.append([])
    rec0 = next(iter(data.values()))["rec"]
    wr.append([f"Global Biodiversity Information Facility occurrence search, records since {rec0['since']}, "
               f"queried {rec0['queried']}. These are records, not wildlife counts: they show where people "
               "have looked. 'Bees' and 'Butterflies and moths' are also counted within 'Insects'."])
    wr.cell(wr.max_row, 1).font = Font(italic=True)
    style_sheet(wr, [18, 24, 14, 14, 16, 16, 70])

    # ---- Context -----------------------------------------------------------
    wx = wb.create_sheet("Context")
    wx.append(["Neighborhood", "Kind", "Name", "Distance from boundary, m", "Detail"])
    for sid, dd in data.items():
        c = dd["ctx"]["context"]
        for w in c["washes"]:
            wx.append([dd["site"]["name"], "Wash", w["name"], w["distance_m"], f"County flow class: {w['flow']}"])
        wx.append([dd["site"]["name"], "Riparian habitat", "Nearest mapped riparian habitat",
                   c["riparian"]["nearest_m"],
                   f"{c['riparian']['total_ha']} ha within 1 km; county class {c['riparian']['nearest_class']}"])
        for p in c["parks"]:
            wx.append([dd["site"]["name"], "Park or open space", p["name"], p["distance_m"],
                       f"{p['ha']} ha, {p['kind'].lower()}"])
    for row in wx.iter_rows(min_row=2, min_col=4, max_col=4):
        row[0].number_format = NUM
    style_sheet(wx, [18, 20, 44, 16, 54])

    # ---- Read me -----------------------------------------------------------
    wm = wb.create_sheet("Read me", 0)
    lines = [
        ("Tucson Neighborhood Canopy Scenario: summary of results", True),
        ("", False),
        ("Two Tucson neighborhoods mapped from lidar and aerial imagery, and a native tree planting "
         "scenario for each. Dunbar Spring is the reference: its residents planted its street trees. "
         "Western Hills is the candidate.", False),
        ("Page and method: https://finkgeo.com/tucson-canopy/   Scripts: tools/canopy/ in the site's repository.", False),
        ("", False),
        ("How to read this workbook", True),
        ("Scenarios is the main sheet: one row per neighborhood and planting. The other sheets hold the "
         "detail behind it.", False),
        ("Measured results are values. Gains, carbon, carbon dioxide, totals and shares are formulas "
         "that point at the Assumptions sheet, so a factor changed there carries through.", False),
        ("Percentages are stored as fractions (0.209 shows as 20.9%).", False),
        ("", False),
        ("What to keep in mind", True),
        ("This is a planning sketch, not a planting plan. Nothing checks buried utilities, ownership or irrigation.", False),
        ("New trees are at their published mature size, which takes decades.", False),
        ("Tree canopy is mapped well (about 95% right on tree or not). Pavement is over-mapped inside "
         "lots, which hides plantable ground and does not invent it.", False),
        ("The surface temperature changes are from how leafy and bare blocks differ across Tucson at "
         "about 11 a.m. (Landsat) and about 2:30 p.m. (ECOSTRESS). They are surface, not air, "
         "temperatures, and leafy blocks are often watered.", False),
        ("Carbon uses a US urban average. No desert city was in that study; the low figure is the safer one.", False),
        ("Species records show where people have looked, not what lives where.", False),
        ("", False),
        ("Sources", True),
        ("Lidar: USGS 3D Elevation Program, Pima County, flown 27 September to 17 November 2021.", False),
        ("Imagery: USDA National Agriculture Imagery Program, 18 October 2023.", False),
        ("Surface temperature: Landsat 8 and 9, June to August 2021 to 2023, through Google Earth Engine; "
         "NASA ECOSTRESS (ECO_L2T_LSTE version 2), June to August 2021 to 2025.", False),
        ("Boundaries: City of Tucson neighborhood associations (Western Hills is registered as Western Hills II).", False),
        ("Parcels, streets, washes, riparian habitat, parks: Pima County GIS.", False),
        ("Species records: Global Biodiversity Information Facility.", False),
        ("Carbon factors, tree sizes, rainfall: see the Assumptions sheet.", False),
    ]
    for words, bold in lines:
        wm.append([words])
        c = wm.cell(wm.max_row, 1)
        c.font = Font(name=FONT, size=14 if wm.max_row == 1 else 10, bold=bold)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    wm.column_dimensions["A"].width = 120

    path = OUT / "tucson_canopy_summary.xlsx"
    wb.save(path)
    print("wrote", path)


CONFIG_NAME = {s["id"]: s["name"] for s in CONFIG["sites"]}

if __name__ == "__main__":
    main()
