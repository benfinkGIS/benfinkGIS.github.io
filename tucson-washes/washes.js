/* Tucson Wash Field Guide: map, figures and table.
   Reads data/washes.json and data/channels.geojson (written by tools/washes/08_reaches.py).
   MapLibre GL JS 4.7.1 is loaded by the page. */
(function () {
  "use strict";
  /* The full-page map (map/index.html) has only the viewer. An id that is not on the page gets a
     spare element, so the figures and table written for the project page go nowhere there. */
  var spare = {};
  var $ = function (id) { return document.getElementById(id) || spare[id] || (spare[id] = document.createElement("div")); };
  var FULL = document.body.classList.contains("fullmap");
  var BASE = "/tucson-washes/";
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  var fmt = function (n) { return Math.round(n).toLocaleString("en-US"); };
  var one = function (n) { return (Math.round(n * 10) / 10).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }); };
  function css(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }

  var RIP = [["H", "Class H: hydroriparian and mesoriparian", "--rip-h"],
             ["A", "Class A xeroriparian (densest)", "--rip-a"],
             ["B", "Class B xeroriparian", "--rip-b"],
             ["C", "Class C xeroriparian", "--rip-c"],
             ["D", "Class D xeroriparian (sparsest)", "--rip-d"]];
  var MODES = [["rip", "County riparian class"], ["canopy", "Tree canopy"], ["source", "Who has mapped it"]];
  var SHOW = [["small", "Small channels (under 20 ha)", "small"], ["street", "Storm water in streets", "street"]];
  var SPECIES = [["bobcat", "bobcat", "b"], ["flycatcher", "vermilion flycatcher", "f"], ["queen", "queen butterfly", "q"]];
  var SMALL_HA = 20;

  var d, map, popup, mode = "rip", on = { small: true, street: false }, pick = null, sat = true;
  var sortKey = "km", sortDir = -1, byName = {};

  function setMsg(t) { $("sb-msg").textContent = t; }
  function ready() { return fmt(d.wash_km) + " km of wash in " + fmt(d.reaches) + " reaches. Click one for its notes."; }

  // ---- settings: toolbar-style buttons; the choices ride along in the address ----
  function readQuery() {
    var q = new URLSearchParams(location.search), m = q.get("color"), show = q.get("show");
    if (MODES.some(function (x) { return x[0] === m; })) mode = m;
    if (show !== null) { var want = show.split(","); SHOW.forEach(function (s) { on[s[0]] = want.indexOf(s[0]) >= 0; }); }
    if (q.get("wash")) pick = q.get("wash");
  }
  function writeQuery() {
    var show = SHOW.filter(function (s) { return on[s[0]]; }).map(function (s) { return s[0]; }).join(",");
    var q = "?color=" + mode + "&show=" + show + (pick ? "&wash=" + encodeURIComponent(pick) : "");
    history.replaceState(null, "", location.pathname + q);
    document.querySelectorAll("a[data-carry]").forEach(function (a) { a.href = a.getAttribute("data-carry") + q; });
  }
  function buildSettings() {
    MODES.forEach(function (m) {
      var b = el("button", null, m[1]);
      b.type = "button";
      b.addEventListener("click", function () { mode = m[0]; render(); });
      $("mode-buttons").appendChild(b);
    });
    SHOW.forEach(function (s) {
      var b = el("button");
      b.type = "button";
      b.appendChild(el("span", "sw " + s[2]));
      b.appendChild(document.createTextNode(s[1]));
      b.addEventListener("click", function () { on[s[0]] = !on[s[0]]; render(); });
      $("show-buttons").appendChild(b);
    });
  }
  function renderSettings() {
    MODES.forEach(function (m, i) { $("mode-buttons").children[i].setAttribute("aria-pressed", m[0] === mode ? "true" : "false"); });
    SHOW.forEach(function (s, i) { $("show-buttons").children[i].setAttribute("aria-pressed", on[s[0]] ? "true" : "false"); });
    writeQuery();
  }

  // ---- figures ----
  function fill(key, text) {
    document.querySelectorAll('[data-fill="' + key + '"]').forEach(function (n) { n.textContent = text; });
  }
  function fillStatic() {
    var c = d.canopy_rule, s = d.sightings, f = d.county_found;
    fill("area", fmt(d.area_km2));
    fill("washkm", fmt(d.wash_km));
    fill("newkm", fmt(d.new_km));
    fill("newpct", Math.round(100 * d.new_km / d.wash_km) + "%");
    fill("streetkm", fmt(d.street_km));
    fill("countykm", fmt(f.all.km));
    fill("found", Math.round(f.all.found_pct) + "%");
    fill("named", d.washes.length);
    fill("namedkm", fmt(d.named_km));
    fill("canwash", one(d.canopy_along_washes_pct) + "%");
    fill("canall", one(d.canopy_study_area_pct) + "%");
    fill("ripshare", d.riparian_share_of_wash_length_pct + "%");
    fill("minha", d.settings.min_area_ha);
    fill("near", d.settings.near_m);
    fill("sight", d.settings.sight_m);
    fill("imagery", (d.imagery_dates || []).join(", "));
    fill("cut", "NDVI of at least " + c.cut.ndvi + ", near-infrared brightness of at least " + Math.round(c.cut.nir) +
      " out of 255, and a spread of at least " + c.cut.spread + " in the 5 m around it");
    var sites = Object.keys(c.sites).map(function (k) { return c.sites[k]; });
    fill("agree", sites.map(function (x) { return Math.round(x.agreement * 100) + "%"; }).join(" and "));
    fill("canfound", sites.map(function (x) { return Math.round(x.share_of_lidar_canopy_found * 100) + "%"; }).join(" and "));
    fill("canright", sites.map(function (x) { return Math.round(x.share_of_mapped_canopy_that_is_lidar_canopy * 100) + "%"; }).join(" and "));
    fill("records", SPECIES.map(function (sp) {
      return fmt(s[sp[0]].placed_to_100m) + " " + sp[1] + " records (" + fmt(s[sp[0]].within_50m_of_a_wash) + " within " + d.settings.sight_m + " m of a wash)";
    }).join(", "));
    var rows = Object.keys(f).filter(function (k) { return k !== "all"; });
    fill("foundby", rows.map(function (k) { return k.toLowerCase() + ", " + Math.round(f[k].found_pct) + "%"; }).join("; "));
  }
  function renderLead() {
    $("hero-num").textContent = fmt(d.wash_km);
    $("hero-lab").textContent = "km of wash channel traced from lidar in " + fmt(d.area_km2) + " km² of northwest Tucson, down to washes that drain " + d.settings.min_area_ha + " hectares";
    $("new-num").textContent = fmt(d.new_km) + " km";
    $("new-lab").textContent = "of it (" + Math.round(100 * d.new_km / d.wash_km) + "%) is on no county wash map";
    $("can-num").textContent = one(d.canopy_along_washes_pct) + "%";
    $("can-lab").textContent = "tree canopy within 10 m of a wash, against " + one(d.canopy_study_area_pct) + "% across the whole area";
  }

  // ---- map ----
  function esri(path) { return "https://server.arcgisonline.com/ArcGIS/rest/services/" + path + "/MapServer/tile/{z}/{y}/{x}"; }
  function colour() {
    if (mode === "canopy") {
      return ["interpolate", ["linear"], ["get", "c"], 0, css("--can-0"), 10, css("--can-1"), 25, css("--can-2"), 45, css("--can-3")];
    }
    if (mode === "source") return ["case", ["==", ["get", "cty"], 1], css("--src-county"), css("--src-new")];
    var m = ["match", ["coalesce", ["get", "r"], ""]];
    RIP.forEach(function (r) { m.push(r[0], css(r[2])); });
    m.push(css("--rip-none"));
    return m;
  }
  function width(extra) {
    var w = ["interpolate", ["linear"], ["sqrt", ["get", "ha"]], 1.4, 0.9, 10, 1.7, 45, 2.8, 140, 4.2, 450, 6];
    return ["interpolate", ["linear"], ["zoom"], 10, ["+", ["*", 0.55, w], extra], 14, ["+", w, extra], 17, ["+", ["*", 1.9, w], extra]];
  }
  function minHa() {
    var z = map.getZoom(), byZoom = z < 11.3 ? 60 : z < 12.6 ? 12 : 0;
    return Math.max(byZoom, on.small ? 0 : SMALL_HA);
  }
  function washFilter() { return ["all", ["==", ["get", "k"], 0], [">=", ["get", "ha"], minHa()]]; }
  function streetFilter() { return ["all", ["==", ["get", "k"], 1], [">=", ["get", "ha"], minHa()]]; }
  function applyFilters() {
    ["ch-case", "ch", "ch-hit"].forEach(function (id) { map.setFilter(id, washFilter()); });
    ["st-case", "st"].forEach(function (id) {
      map.setFilter(id, streetFilter());
      map.setLayoutProperty(id, "visibility", on.street ? "visible" : "none");
    });
    map.setFilter("ch-pick", ["all", ["==", ["get", "k"], 0], ["==", ["coalesce", ["get", "n"], ""], pick || "\u0000"]]);
  }
  function buildMap() {
    var b = d.box;
    map = new maplibregl.Map({
      container: "map",
      style: {
        version: 8,
        sources: {
          sat: { type: "raster", tiles: [esri("World_Imagery")], tileSize: 256, maxzoom: 19,
                 attribution: "Imagery: Esri, Maxar, Earthstar Geographics" },
          gray: { type: "raster", tiles: [esri("Canvas/World_Light_Gray_Base")], tileSize: 256, maxzoom: 16,
                  attribution: "Basemap: Esri" },
          places: { type: "raster", tiles: [esri("Reference/World_Boundaries_and_Places")], tileSize: 256, maxzoom: 19 },
          roads: { type: "raster", tiles: [esri("Canvas/World_Light_Gray_Reference")], tileSize: 256, maxzoom: 16 }
        },
        layers: [
          { id: "sat", type: "raster", source: "sat" },
          { id: "gray", type: "raster", source: "gray", layout: { visibility: "none" } }
        ]
      },
      bounds: [[b[0], b[1]], [b[2], b[3]]],
      fitBoundsOptions: { padding: 10 },
      maxBounds: [[b[0] - 0.25, b[1] - 0.2], [b[2] + 0.25, b[3] + 0.2]],
      minZoom: 9, maxZoom: 18,
      dragRotate: false, pitchWithRotate: false, scrollZoom: FULL,
      attributionControl: { compact: true }
    });
    map.touchZoomRotate.disableRotation();
    if (!FULL) map.once("click", function () { map.scrollZoom.enable(); });
    map.on("error", function (e) {
      if (e && e.sourceId === "ch") fail("The channel data did not load. Try reloading the page.");
    });
    map.on("load", function () {
      map.addSource("ch", { type: "geojson", data: BASE + "data/channels.geojson", tolerance: 0.2 });
      map.addLayer({ id: "st-case", type: "line", source: "ch", layout: { "line-cap": "butt", visibility: "none" },
        paint: { "line-color": "#000", "line-width": width(2), "line-opacity": 0.6 } });
      map.addLayer({ id: "st", type: "line", source: "ch", layout: { "line-cap": "butt", visibility: "none" },
        paint: { "line-color": css("--street"), "line-width": width(0), "line-dasharray": [2, 1.5] } });
      map.addLayer({ id: "ch-case", type: "line", source: "ch", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#000", "line-width": width(2), "line-opacity": 0.6 } });
      map.addLayer({ id: "ch-pick", type: "line", source: "ch", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": css("--pick"), "line-width": width(6), "line-opacity": 0.95 } });
      map.addLayer({ id: "ch", type: "line", source: "ch", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": colour(), "line-width": width(0) } });
      map.addLayer({ id: "ch-hit", type: "line", source: "ch",
        paint: { "line-color": "#000", "line-width": 14, "line-opacity": 0 } });
      map.addLayer({ id: "places", type: "raster", source: "places" });
      map.addLayer({ id: "roads", type: "raster", source: "roads", layout: { visibility: "none" } });
      applyFilters();
      setMsg("Loading channels…");
      map.on("sourcedata", function loaded(e) {
        if (e.sourceId === "ch" && map.isSourceLoaded("ch")) { map.off("sourcedata", loaded); setMsg(ready()); if (pick) choose(pick, true); }
      });
    });
    var tier = null;
    map.on("zoom", function () {
      var t = minHa();
      if (t !== tier && map.getLayer("ch")) { tier = t; applyFilters(); }
    });
    map.on("mousemove", "ch-hit", function (e) {
      map.getCanvas().style.cursor = "pointer";
      var p = e.features[0].properties;
      setMsg((p.n || "Unnamed channel") + ": this reach drains " + haText(p.ha));
    });
    map.on("mouseleave", "ch-hit", function () { map.getCanvas().style.cursor = ""; if (d) setMsg(ready()); });
    map.on("mousemove", function (e) {
      $("sb-pos").textContent = e.lngLat.lat.toFixed(4) + "°N " + Math.abs(e.lngLat.lng).toFixed(4) + "°W";
    });
    map.on("click", "ch-hit", function (e) {
      var p = e.features[0].properties;
      if (p.n) { pick = p.n; render(); }
      showPopup(e.lngLat, p);
    });
    $("tb-in").addEventListener("click", function () { map.zoomIn(); });
    $("tb-out").addEventListener("click", function () { map.zoomOut(); });
    $("tb-full").addEventListener("click", function () { map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 10 }); });
    $("tb-base").addEventListener("click", function () {
      sat = !sat;
      $("tb-base").setAttribute("aria-pressed", sat ? "true" : "false");
      map.setLayoutProperty("sat", "visibility", sat ? "visible" : "none");
      map.setLayoutProperty("places", "visibility", sat ? "visible" : "none");
      map.setLayoutProperty("gray", "visibility", sat ? "none" : "visible");
      map.setLayoutProperty("roads", "visibility", sat ? "none" : "visible");
    });
  }
  function fail(text) { var m = $("map-error"); m.textContent = text; m.hidden = false; setMsg("Not loaded"); }

  // ---- pop-ups ----
  function haText(ha) { return ha >= 100 ? one(ha / 100) + " km²" : fmt(ha) + " ha"; }
  function ripText(code) {
    var r = RIP.filter(function (x) { return x[0] === code; })[0];
    return r ? r[1].replace(/^Class /, "class ") : "not mapped as riparian habitat";
  }
  function line(parent, text) { parent.appendChild(el("li", null, text)); }
  function showPopup(lngLat, p) {
    var box = el("div"), w = p.n ? byName[p.n] : null;
    box.appendChild(el("strong", null, p.n || "Unnamed channel"));
    if (w) {
      box.appendChild(el("p", null, w.blurb));
      var ul = el("ul");
      line(ul, "Drains " + one(w.drains_km2) + " km² inside the study area");
      if (classMix(w)) line(ul, "Riparian classes by length: " + classMix(w));
      line(ul, "Records within " + d.settings.sight_m + " m: " + SPECIES.map(function (s) { return w.sightings[s[0]] + " " + s[1]; }).join(", "));
      box.appendChild(ul);
    } else if (p.n) {
      box.appendChild(el("p", null, "A county-named wash with under " + d.settings.min_named_km + " km of open channel here."));
    } else {
      box.appendChild(el("p", null, p.cty ? "On the county's wash layer, without a name." : "Not on the county's wash layer. Traced from the lidar."));
    }
    var r = el("div", "reach");
    r.textContent = "This reach: " + one(p.km) + " km, drains " + haText(p.ha) + ", " + p.c + "% canopy within 10 m, " + ripText(p.r) + ".";
    box.appendChild(r);
    if (popup) popup.remove();
    popup = new maplibregl.Popup({ maxWidth: "300px" }).setLngLat(lngLat).setDOMContent(box).addTo(map);
  }
  function classMix(w) {
    var keys = Object.keys(w.classes).filter(function (k) { return w.classes[k] >= 5; });
    if (!keys.length) return "";
    keys.sort(function (a, b) { return w.classes[b] - w.classes[a]; });
    return keys.map(function (k) { return k + " " + w.classes[k] + "%"; }).join(", ");
  }

  // ---- legend ----
  function key(cls, varName, text) {
    var li = el("li"), k = el("span", cls);
    if (varName) k.style.setProperty("--k", "var(" + varName + ")");
    li.appendChild(k);
    li.appendChild(document.createTextNode(text));
    return li;
  }
  function renderLegend() {
    var host = $("map-legend");
    host.textContent = "";
    if (mode === "rip") {
      RIP.forEach(function (r) { host.appendChild(key("ln", r[2], r[1])); });
      host.appendChild(key("ln", "--rip-none", "Not mapped as riparian"));
    } else if (mode === "canopy") {
      host.appendChild(key("ramp", null, "Tree canopy within 10 m: none to 45% and over"));
    } else {
      host.appendChild(key("ln", "--src-county", "On the county's wash layer"));
      host.appendChild(key("ln", "--src-new", "Traced from lidar only"));
    }
    if (on.street) host.appendChild(key("ln dashed", "--street", "Storm water running down a street"));
    host.appendChild(el("li", "wide", "Wider line = more ground draining to it"));
  }

  // ---- table ----
  var COLS = [["name", "Wash", ""], ["km", "Length, km", "num"], ["drains_km2", "Drains, km²", "num"],
              ["canopy_pct", "Canopy within 10 m", "num"], ["riparian_pct", "Mapped riparian", "num"],
              ["top", "Main class", "cls"], ["bobcat", "Bobcat", "num"], ["flycatcher", "Flycatcher", "num"], ["queen", "Queen", "num"]];
  function val(w, k) {
    if (k === "bobcat" || k === "flycatcher" || k === "queen") return w.sightings[k];
    if (k === "top") return w.top;
    return w[k];
  }
  function renderTable() {
    var t = $("t-wash");
    t.textContent = "";
    var head = el("tr");
    COLS.forEach(function (c) {
      var th = el("th", c[2] === "num" ? "num" : null), b = el("button", null, c[1]);
      th.scope = "col";
      b.type = "button";
      if (c[0] === sortKey) th.setAttribute("aria-sort", sortDir > 0 ? "ascending" : "descending");
      b.addEventListener("click", function () {
        if (sortKey === c[0]) sortDir = -sortDir; else { sortKey = c[0]; sortDir = c[2] === "num" ? -1 : 1; }
        renderTable();
      });
      th.appendChild(b);
      head.appendChild(th);
    });
    var thead = el("thead"); thead.appendChild(head); t.appendChild(thead);
    var rows = d.washes.slice().sort(function (a, b) {
      var x = val(a, sortKey), y = val(b, sortKey);
      return (x < y ? -1 : x > y ? 1 : 0) * sortDir || (a.name < b.name ? -1 : 1);
    });
    var body = el("tbody");
    rows.forEach(function (w) {
      var tr = el("tr", w.name === pick ? "on" : null), first = el("td"), b = el("button", null, w.name);
      b.type = "button";
      b.addEventListener("click", function () { choose(w.name, true); });
      first.appendChild(b);
      tr.appendChild(first);
      tr.appendChild(el("td", "num", one(w.km)));
      tr.appendChild(el("td", "num", one(w.drains_km2)));
      tr.appendChild(el("td", "num", Math.round(w.canopy_pct) + "%"));
      tr.appendChild(el("td", "num", w.riparian_pct + "%"));
      tr.appendChild(el("td", "cls", w.top || "–"));
      SPECIES.forEach(function (s) { tr.appendChild(el("td", "num", w.sightings[s[0]] || "–")); });
      body.appendChild(tr);
    });
    t.appendChild(body);
  }
  function choose(name, zoom) {
    var w = byName[name];
    if (!w) { pick = null; render(); return; }
    pick = name;
    render();
    if (zoom && map) {
      map.fitBounds([[w.box[0], w.box[1]], [w.box[2], w.box[3]]], { padding: 50, maxZoom: 15 });
      setMsg(w.name + ": " + one(w.km) + " km");
      if (!FULL) $("map").scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function render() {
    renderSettings();
    renderLegend();
    renderTable();
    if (map && map.getLayer("ch")) {
      map.setPaintProperty("ch", "line-color", colour());
      applyFilters();
    }
  }

  function start(data) {
    d = data;
    d.washes.forEach(function (w) {
      byName[w.name] = w;
      var keys = Object.keys(w.classes);
      keys.sort(function (a, b) { return w.classes[b] - w.classes[a]; });
      w.top = keys.length && w.classes[keys[0]] >= 5 ? keys[0] : "";
    });
    readQuery();
    if (pick && !byName[pick]) pick = null;
    buildSettings();
    fillStatic();
    renderLead();
    if (window.maplibregl) buildMap(); else fail("The map library did not load.");
    render();
  }

  fetch(BASE + "data/washes.json")
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(start)
    .catch(function () { fail("The wash data did not load. Try reloading the page."); });
})();
