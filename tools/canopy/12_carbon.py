"""Step 9b: carbon stored and taken up by the canopy each scenario adds.

Runs in the system Python:  py tools/canopy/12_carbon.py [site_id ...]

Carbon is estimated from canopy area, not tree by tree: the new canopy area
inside each boundary (from scenarios.json, at mature size) times a published
amount of carbon per square metre of urban tree cover (carbon_factors.json).

  stored            canopy added x 7.69 kg C per m2, the US urban average.
                    The low and high figures use the lowest and highest city
                    in the source (3.1 and 14.1), because no desert city was
                    sampled and open-crowned desert trees probably sit low
  taken up a year   canopy added x 0.354 kg C per m2 a year, the source's
                    Arizona rate, gross; net of decay and loss is 74% of that

Everything is for the trees once mature, which takes decades, and counts only
the trees themselves: not soil, not the energy saved by shade, not the
emissions of planting and watering. Tonnes are metric. CO2 = carbon x 3.667.

Writes carbon.json beside each site's geodatabase.
"""
import json
import sys

from common import PROJECT, site_dir, sites

F = json.loads((PROJECT / "carbon_factors.json").read_text(encoding="utf-8"))


def main():
    for s in sites(sys.argv[1:]):
        d = site_dir(s)
        scen = json.loads((d / "scenarios.json").read_text())["scenarios"]
        out = dict(site=s["id"], source=F["source"], scenarios={})
        for name, v in scen.items():
            m2 = v["canopy_added_ha"] * 1e4
            stored = m2 * F["storage_kgC_per_m2"] / 1000
            gross = m2 * F["gross_sequestration_arizona_kgC_per_m2_yr"] / 1000
            out["scenarios"][name] = dict(
                trees=v["trees"], canopy_added_ha=v["canopy_added_ha"],
                stored_tC=round(stored),
                stored_tC_low=round(m2 * F["storage_city_range"][0] / 1000),
                stored_tC_high=round(m2 * F["storage_city_range"][1] / 1000),
                stored_tCO2=round(stored * F["co2_per_c"]),
                uptake_gross_tC_yr=round(gross, 1),
                uptake_net_tC_yr=round(gross * F["net_share_of_gross"], 1),
                uptake_net_tCO2_yr=round(gross * F["net_share_of_gross"] * F["co2_per_c"], 1),
                stored_kgC_per_tree=round(stored * 1000 / v["trees"]) if v["trees"] else None)
        (d / "carbon.json").write_text(json.dumps(out, indent=1))
        print(s["id"])
        for name, r in out["scenarios"].items():
            print(f"   {name:18s} +{r['canopy_added_ha']:5.2f} ha  stored {r['stored_tC']:4d} t C "
                  f"({r['stored_tC_low']} to {r['stored_tC_high']})  = {r['stored_tCO2']} t CO2 | "
                  f"net uptake {r['uptake_net_tC_yr']} t C/yr | {r['stored_kgC_per_tree']} kg C per tree")


if __name__ == "__main__":
    main()
