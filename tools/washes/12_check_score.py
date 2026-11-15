"""Step 6b: score the rules against the hand labels, and set their cut-offs.

Run:  py tools/washes/12_check_score.py

Reads work/check/key.json (what the rule said and the stratum each item was
drawn from), labels.json (what Ben saw) and sample_attrs.json (each item's
measures when it was drawn). Every figure is weighted back to the population
the sample was drawn from, so an over-sampled stratum does not count for more
than its share.

Three things come out of it:

  1. Is it a wash at all?  A third of the sampled spots were labelled "not a
     wash" or "no crossing here": the lidar traces where water would run, and
     much of that is across yards, lots and streets with no channel. A reach
     is kept as a wash when it is cut at least INCISION cm below the ground
     either side of it, or the county maps a wash or riparian habitat there,
     and under a fifth of it is on street pavement. The incision cut-off is
     chosen from the channel-bed labels.

  2. Crossing type.  The step and hump cut-offs of step 4 are re-chosen from
     the crossing labels.

  3. What the beds are made of.  Concrete turned out too rare (7 of 160) to
     fit a rule to, so this is reported as shares of all reaches, from the
     sample, not mapped reach by reach.

Cut-offs chosen from labels are scored by leave-one-out: each item is typed
by cut-offs chosen without it. Writes tucson-washes/rules.json (read by steps
3 and 4) and work/check/results.json.
"""
import json
import random
import time
from collections import Counter, defaultdict

from common import PROJECT, WORK

CHECK = WORK / "check"
COUNTY_MIN, RIP_MIN, STREET_MAX = 0.5, 0.5, 0.2
INCISION_GRID = [10, 15, 20, 25, 30]
STEP_GRID = [1.2, 1.5, 1.8, 2.0, 2.2, 2.5]
HUMP_GRID = [0.6, 0.8, 1.0, 1.2, 1.5]
SEED = 20261115
BED = {1: "natural", 2: "natural bed, built banks", 3: "concrete", 4: "not a wash"}
CROSS = {1: "open span", 2: "culvert", 3: "at-grade", 4: "no crossing"}


def is_wash(r, incision):
    cut = (r["incision_cm"] or 0) >= incision
    mapped = (r["county_share"] or 0) >= COUNTY_MIN or (r["rip_share"] or 0) >= RIP_MIN
    return (cut or mapped) and (r["street_share"] or 0) < STREET_MAX


def cross_type(c, step_min, hump_min):
    if c["step_m"] >= step_min:
        return "open span"
    if c["hump_m"] >= hump_min:
        return "culvert"
    return "at-grade"


def set_weights(universe):
    """Each labelled item stands for (stratum size / items labelled in it) members."""
    n = Counter(it["stratum"] for it in universe)
    for it in universe:
        it["w"] = it["pop"] / n[it["stratum"]]


def share(universe, good, within=lambda it: True, reps=2000):
    """Weighted share of the items in a subset for which good(item) holds.

    The subset can cut across strata (reaches the rule kept, say), so this is
    a ratio of two weighted totals. The 95% interval comes from resampling
    the labelled items within each stratum.
    """
    def ratio(sample):
        den = sum(it["w"] for it in sample if within(it))
        return sum(it["w"] for it in sample if within(it) and good(it)) / den if den else float("nan")

    by = defaultdict(list)
    for it in universe:
        by[it["stratum"]].append(it)
    rng = random.Random(SEED)
    draws = []
    for _ in range(reps):
        sample = [it for g in by.values() for it in rng.choices(g, k=len(g))]
        r = ratio(sample)
        if r == r:
            draws.append(r)
    draws.sort()
    return dict(pct=round(100 * ratio(universe), 1), low=round(100 * draws[int(0.025 * len(draws))], 1),
                high=round(100 * draws[int(0.975 * len(draws)) - 1], 1),
                n=sum(1 for it in universe if within(it)))


def wmean(items, good):
    den = sum(it["w"] for it in items)
    return sum(it["w"] for it in items if good(it)) / den if den else 0.0


def best(items, grid, score):
    """Grid value with the highest weighted score; the first wins a tie."""
    return max(grid, key=lambda g: wmean(items, lambda it: score(it, g)))


def main():
    key = json.loads((CHECK / "key.json").read_text())
    labels = json.loads((CHECK / "labels.json").read_text())
    attrs = json.loads((CHECK / "sample_attrs.json").read_text())
    pop = key["population"]
    items = []
    for pid, k in key["items"].items():
        group = pop["crossings" if k["task"] == "x" else "beds"]
        items.append(dict(id=pid, task=k["task"], stratum=k["stratum"], pop=group[k["stratum"]],
                          label=labels[pid]["label"], **attrs[pid]))
    beds = [it for it in items if it["task"] == "b"]
    crossings = [it for it in items if it["task"] == "x"]
    out = dict(scored=time.strftime("%Y-%m-%d"), items=len(items),
               cant_tell=dict(beds=sum(it["label"] == 0 for it in beds),
                              crossings=sum(it["label"] == 0 for it in crossings)))

    # ---- 1. is it a wash ----
    told = [it for it in beds if it["label"] != 0]
    set_weights(told)
    truth = lambda it: it["label"] in (1, 2, 3)
    hit = lambda it, g: is_wash(it["reach"], g) == truth(it)
    incision = best(told, INCISION_GRID, hit)
    loo = {}
    for it in told:
        loo[it["id"]] = is_wash(it["reach"], best([o for o in told if o is not it], INCISION_GRID, hit))
    kept = lambda it: loo[it["id"]]
    out["wash_rule"] = dict(
        incision_min_cm=incision, county_min=COUNTY_MIN, riparian_min=RIP_MIN, street_max=STREET_MAX,
        labelled_a_wash=share(told, truth),
        reaches_kept=share(told, kept),
        agreement_cross_validated=share(told, lambda it: kept(it) == truth(it)),
        kept_that_are_washes=share(told, truth, kept),
        dropped_that_are_not=share(told, lambda it: not truth(it), lambda it: not kept(it)),
        washes_kept=share(told, kept, truth))

    # ---- 3. what the beds are made of ----
    out["bed_material"] = dict(
        of_all_reaches={name: share(told, lambda it, v=v: it["label"] == v) for v, name in BED.items()},
        of_reaches_labelled_a_wash={name: share(told, lambda it, v=v: it["label"] == v, truth)
                                    for v, name in BED.items() if v != 4},
        colour_rule=dict(called_concrete=sum(it["stratum"] == "most" for it in told),
                         of_which_concrete=sum(it["stratum"] == "most" and it["label"] == 3 for it in told),
                         concrete_labels_in_sample=sum(it["label"] == 3 for it in told)))

    # ---- 2. crossings ----
    seen = [it for it in crossings if it["label"] != 0]
    set_weights(seen)
    on_wash = lambda it: is_wash(it["reach"], incision)
    is_real = lambda it: it["label"] != 4
    real_on = lambda it: on_wash(it) and is_real(it)
    reals = [it for it in seen if real_on(it)]
    lab = lambda it: CROSS[it["label"]]

    def choose(sample):
        pairs = [(s, h) for s in STEP_GRID for h in HUMP_GRID]
        return max(pairs, key=lambda p: wmean(sample, lambda it: cross_type(it["crossing"], *p) == lab(it)))

    step_min, hump_min = choose(reals)
    typed = lambda it: cross_type(it["crossing"], step_min, hump_min)
    loo_type = {}
    for it in reals:
        loo_type[it["id"]] = cross_type(it["crossing"], *choose([o for o in reals if o is not it]))
    matrix = defaultdict(Counter)
    for it in reals:
        matrix[loo_type[it["id"]]][lab(it)] += 1
    kinds = ("open span", "culvert", "at-grade")
    out["crossings"] = dict(
        step_min_m=step_min, hump_min_m=hump_min,
        on_reaches_kept_as_wash=sum(on_wash(it) for it in seen),
        on_reaches_dropped=sum(not on_wash(it) for it in seen),
        real_crossing_on_kept_reaches=share(seen, is_real, on_wash),
        real_crossing_on_dropped_reaches=share(seen, is_real, lambda it: not on_wash(it)),
        real_crossing_by_type={k: share(seen, is_real, lambda it, k=k: on_wash(it) and typed(it) == k)
                               for k in kinds},
        type_agreement_first_cutoffs=share(seen, lambda it: cross_type(it["crossing"], 1.2, 0.6) == lab(it), real_on),
        type_agreement_cross_validated=share(seen, lambda it: loo_type[it["id"]] == lab(it), real_on),
        right_when_rule_says={k: share(seen, lambda it: loo_type[it["id"]] == lab(it),
                                       lambda it, k=k: real_on(it) and loo_type[it["id"]] == k)
                              for k in kinds},
        counts_rule_by_label={k: dict(c) for k, c in matrix.items()})

    labelled = [labels[k]["at"] for k in labels if labels[k].get("at") and labels[k]["at"] != "test"]
    out["labelled_between"] = [min(labelled)[:10], max(labelled)[:10]]
    (CHECK / "results.json").write_text(json.dumps(out, indent=2))
    (PROJECT / "rules.json").write_text(json.dumps(dict(
        _about="Cut-offs set from the hand check of 340 crossings and channel beds "
               "(tools/washes/12_check_score.py). Steps 3 and 4 read this file.",
        set_on=out["scored"],
        wash=dict(incision_min_cm=incision, county_min=COUNTY_MIN, riparian_min=RIP_MIN,
                  street_max=STREET_MAX),
        crossing=dict(step_min_m=step_min, hump_min_m=hump_min)), indent=2) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
