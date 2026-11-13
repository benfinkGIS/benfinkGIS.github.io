/* Empty Homes: map, figures and tables.
   Reads data/empty.json, written by tools/build_empty_homes.py.
   Leaflet 1.9.4 is loaded by the page. */
(function () {
  "use strict";
  /* The full-page map (map/index.html) has only the viewer. An id that is not on the page gets a
     spare element, so the figures and tables written for the project page go nowhere there. */
  var spare = {};
  var $ = function (id) { return document.getElementById(id) || spare[id] || (spare[id] = document.createElement("div")); };
  var FULL = document.body.classList.contains("fullmap");
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  var fmt = function (n) { return Math.round(n).toLocaleString("en-US"); };
  var money = function (n) { return n == null ? "" : "$" + (Math.round(n / 1000) * 1000).toLocaleString("en-US"); };
  var pct1 = function (a, b) { return b ? (a / b * 100).toFixed(1) + "%" : ""; };

  var RAMP = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"];
  var HEX_BREAKS = [5, 10, 25, 50, 100];              // winter homes per hexagon
  var HEX_LABELS = ["5 to 9 winter homes", "10 to 24", "25 to 49", "50 to 99", "100 or more"];
  var TRACT_BREAKS = [0, 1, 2.5, 5, 10];              // "other vacant" homes as a percent of all homes
  var TRACT_LABELS = ["Under 1% of homes", "1 to 2.5%", "2.5 to 5%", "5 to 10%", "10% or more"];
  var SHADE = [["winter", "Winter homes"], ["census", "Other vacant homes (Census)"]];
  var SHOW = [["unfinished", "Unfinished housing", "sq"], ["cases", "Vacant-building cases", "tr"]];
  var KIND = { house: "Houses", condo: "Condos and townhomes", manufactured: "Manufactured homes", all: "All three" };
  var STATES = { CA: "California", WA: "Washington", MN: "Minnesota", CO: "Colorado", IL: "Illinois", WI: "Wisconsin",
    MI: "Michigan", OR: "Oregon", TX: "Texas", NY: "New York", KS: "Kansas", AK: "Alaska", MT: "Montana", OH: "Ohio",
    IA: "Iowa", ID: "Idaho", FL: "Florida", IN: "Indiana", PA: "Pennsylvania", NM: "New Mexico", NV: "Nevada", UT: "Utah" };

  var d, shade = "winter", on = { unfinished: true, cases: true };
  var map, base, labels, imagery, hexLayer, tractLayer, unfLayer, caseLayer, fullBounds, aerieMarker;

  function setMsg(t) { var m = $("sb-msg"); if (m) m.textContent = t; }
  function band(v, breaks) { for (var k = breaks.length - 1; k >= 0; k--) { if (v >= breaks[k]) return k; } return 0; }
  function fill(key, text) {
    document.querySelectorAll('[data-fill="' + key + '"]').forEach(function (n) { n.textContent = text; });
  }
  function longDate(iso) {
    return new Date(iso + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  }

  // ---- settings: toolbar-style buttons; the choices ride along in the address ----
  function readQuery() {
    var q = new URLSearchParams(location.search), show = q.get("show");
    if (q.get("shade") === "census") shade = "census";
    if (show !== null) {
      var want = show.split(",");
      SHOW.forEach(function (s) { on[s[0]] = want.indexOf(s[0]) >= 0; });
    }
  }
  function writeQuery() {
    var show = SHOW.filter(function (s) { return on[s[0]]; }).map(function (s) { return s[0]; }).join(",");
    history.replaceState(null, "", location.pathname + "?shade=" + shade + "&show=" + show);
    document.querySelectorAll("a[data-carry]").forEach(function (a) { a.href = a.getAttribute("data-carry") + location.search; });
  }
  function buildSettings() {
    SHADE.forEach(function (s) {
      var b = el("button", null, s[1]);
      b.type = "button";
      b.addEventListener("click", function () { shade = s[0]; render(); });
      $("shade-buttons").appendChild(b);
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
    SHADE.forEach(function (s, i) { $("shade-buttons").children[i].setAttribute("aria-pressed", s[0] === shade ? "true" : "false"); });
    SHOW.forEach(function (s, i) { $("show-buttons").children[i].setAttribute("aria-pressed", on[s[0]] ? "true" : "false"); });
    writeQuery();
  }

  // ---- figures ----
  function fillStatic() {
    var w = d.winter, c = d.census.county, h = d.homeless, u = d.unfinished.count;
    var housing = (u.house || 0) + (u.apartments || 0) + (u.condo || 0);
    $("hero-num").textContent = fmt(w.total);
    $("other-num").textContent = fmt(c.other);
    $("homeless-num").textContent = fmt(h.count);
    $("homeless-lab").textContent = "people counted without a home on " + longDate(h.date);
    fill("homeless", fmt(h.count));
    fill("winter", fmt(w.total));
    fill("both", fmt(w.both_years));
    fill("taxyears", w.tax_years.join(" and "));
    fill("ratio", (w.total / h.count).toFixed(1));
    fill("acs-years", d.census.year.replace("-", " to "));
    fill("placemin", fmt(w.place_min_homes));
    fill("over1m", fmt(w.over_1m));
    fill("under250", fmt(w.under_250k) + " (" + Math.round(w.under_250k / w.total * 100) + "%)");
    fill("cases-all", fmt(d.cases.all));
    fill("cases-since", d.cases.since.slice(0, 4));
    fill("cases-open", fmt(d.cases.open.length));
    fill("cases-old", fmt(d.cases.over_2y));
    fill("unf-housing", fmt(housing));
    fill("unf-apts", fmt(u.apartments || 0));
    fill("unf-comm", fmt(u.commercial || 0));
    fill("other", fmt(c.other));
    fill("pit-year", h.date.slice(0, 4));
    fill("pit-date", longDate(h.date));
    fill("pit-prior", fmt(h.prior));
    fill("homes", fmt(w.homes));
    fill("c41-az", fmt(w.funnel.class41_arizona));
    fill("hexm", fmt(w.hex_m));
    fill("hexmin", w.hex_min);
    fill("notdrawn", fmt(w.not_drawn));
    fill("generated", longDate(d.generated));
  }

  // ---- ranked bars ----
  function bars(host, rows, max) {
    host.textContent = "";
    rows.forEach(function (r) {
      var name = el("div", "name", r.name);
      if (r.sub) name.appendChild(el("small", null, r.sub));
      var track = el("div", "track"), bar = el("div", "bar" + (r.cls ? " " + r.cls : ""));
      bar.style.width = "calc((100% - 150px) * " + (r.v / max).toFixed(4) + ")";
      track.tabIndex = 0;
      track.setAttribute("role", "img");
      track.setAttribute("aria-label", r.name + ": " + fmt(r.v) + (r.note ? ", " + r.note : ""));
      track.appendChild(bar);
      var val = el("span", "val", fmt(r.v) + " ");
      if (r.note) val.appendChild(el("small", null, "(" + r.note + ")"));
      track.appendChild(val);
      hoverTip(track, function () { return [r.name, r.tip || fmt(r.v)]; });
      host.appendChild(name);
      host.appendChild(track);
    });
  }
  function renderCompare() {
    var c = d.census.county, w = d.winter, h = d.homeless;
    var market = c.for_rent + c.for_sale;
    var rows = [
      { name: "People counted without a home", sub: "one night, " + h.date.slice(0, 4), v: h.count, cls: "people", note: "people",
        tip: fmt(h.count) + " people in shelters and on the street on " + longDate(h.date) + "." },
      { name: "Winter homes", sub: "Assessor's tax roll", v: w.total, note: "homes",
        tip: fmt(w.total) + " homes that are not a main residence or a rental, owned by people with a mailing address outside Arizona." },
      { name: "Vacant, other reasons", sub: "Census estimate", v: c.other, note: "give or take " + fmt(c.other_moe),
        tip: "About " + fmt(c.other) + " homes vacant and not for rent, for sale or seasonal. Margin of error " + fmt(c.other_moe) + "." },
      { name: "Vacant, for rent or for sale", sub: "Census estimate", v: market, note: "homes between occupants",
        tip: "About " + fmt(c.for_rent) + " for rent and " + fmt(c.for_sale) + " for sale." },
      { name: "Seasonal, as the Census counts it", sub: "Census estimate", v: c.seasonal, note: "give or take " + fmt(c.seasonal_moe),
        tip: "About " + fmt(c.seasonal) + " homes for seasonal, recreational or occasional use that were empty when surveyed. Margin of error " + fmt(c.seasonal_moe) + "." }
    ];
    bars($("compare"), rows, Math.max.apply(null, rows.map(function (r) { return r.v; })));
  }
  function renderOrigin() {
    var w = d.winter, rows = w.origin.map(function (o) {
      return { name: STATES[o.from] || o.from, v: o.n, note: pct1(o.n, w.total),
        tip: fmt(o.n) + " winter homes, " + pct1(o.n, w.total) + " of the total." };
    });
    rows.push({ name: "Everywhere else", v: w.origin_rest, note: pct1(w.origin_rest, w.total),
      tip: fmt(w.origin_rest) + " winter homes, " + pct1(w.origin_rest, w.total) + " of the total." });
    bars($("origin"), rows, Math.max.apply(null, rows.map(function (r) { return r.v; })));
  }

  // ---- tables ----
  function table(id, head, rows, rowClass) {
    var t = $(id);
    t.textContent = "";
    var tr = el("tr");
    head.forEach(function (h) { var th = el("th", h[1], h[0]); th.scope = "col"; tr.appendChild(th); });
    var thead = el("thead"); thead.appendChild(tr); t.appendChild(thead);
    var body = el("tbody");
    rows.forEach(function (r, i) {
      var row = el("tr", rowClass ? rowClass(i) : null);
      r.forEach(function (c, j) { row.appendChild(el("td", head[j][1], c)); });
      body.appendChild(row);
    });
    t.appendChild(body);
  }
  function renderTables() {
    var w = d.winter, f = w.funnel;
    table("t-funnel", [["Step", ""], ["Homes left", "num"]], [
      ["Houses, condos, townhomes and manufactured homes in the county", fmt(w.homes)],
      ["Not a main home and not a rental (legal class 4.1)", fmt(f.class41)],
      ["Tax bill mailed outside Arizona", fmt(f.away)],
      ["Owned by a person or family trust (" + fmt(f.companies) + " company-owned homes dropped)", fmt(f.people)],
      ["Not on Mt Lemmon (" + fmt(f.lemmon) + " dropped): winter homes", fmt(f.winter)]
    ], function (i) { return i === 4 ? "result" : null; });
    table("t-places", [["Community", ""], ["Homes", "num"], ["Winter homes", "num"], ["Share", "num"]],
      w.places.map(function (p) { return [p.place, fmt(p.homes), fmt(p.winter), pct1(p.winter, p.homes)]; }));
    table("t-values", [["", ""], ["Winter homes", "num"], ["Middle winter home", "num"], ["Middle main home", "num"]],
      w.values.map(function (v) { return [KIND[v.kind], fmt(v.winter_n), money(v.winter_median), money(v.primary_median)]; }));
  }

  // ---- tooltip ----
  function showTip(x, y, title, text) {
    var tip = $("tip");
    tip.textContent = "";
    tip.appendChild(el("strong", null, title));
    if (text) tip.appendChild(document.createTextNode(text));
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(4, Math.min(window.innerWidth - w - 4, x + 14)) + "px";
    tip.style.top = (y + 18 + h > window.innerHeight ? y - h - 10 : y + 18) + "px";
  }
  function hideTip() { $("tip").hidden = true; }
  function hoverTip(node, get) {
    node.addEventListener("mousemove", function (e) { var c = get(); showTip(e.clientX, e.clientY, c[0], c[1]); });
    node.addEventListener("mouseleave", hideTip);
    node.addEventListener("focus", function () { var r = node.getBoundingClientRect(), c = get(); showTip(r.left, r.bottom - 14, c[0], c[1]); });
    node.addEventListener("blur", hideTip);
  }
  function areaTip(layer, get) {
    layer.on("mousemove", function (e) {
      var c = get();
      showTip(e.originalEvent.clientX, e.originalEvent.clientY, c[0], c[1]);
      setMsg(c[0] + ". " + c[1]);
      layer.setStyle({ weight: 2, color: "#000" });
    });
    layer.on("mouseout", function () { hideTip(); setMsg(statusText()); layer.setStyle({ weight: 0.6, color: "#fff" }); });
    layer.on("click", function () { var c = get(); setMsg(c[0] + ". " + c[1]); });       // touch screens
  }

  // ---- map ----
  function icon(kind) {
    var svg = {
      apartments: '<svg width="16" height="16" viewBox="0 0 16 16"><rect x="1.5" y="1.5" width="13" height="13" fill="#eb6834" stroke="#000" stroke-width="2"/></svg>',
      home: '<svg width="10" height="10" viewBox="0 0 10 10"><rect x="1" y="1" width="8" height="8" fill="#eb6834" stroke="#000" stroke-width="1.5"/></svg>',
      "case": '<svg width="13" height="12" viewBox="0 0 16 15"><path d="M8 1 15 14H1Z" fill="#ffff00" stroke="#000" stroke-width="2" stroke-linejoin="round"/></svg>',
      old: '<svg width="16" height="15" viewBox="0 0 18 17"><path d="M9 1 17 16H1Z" fill="#000" stroke="#ffff00" stroke-width="1.5" stroke-linejoin="round"/></svg>'
    }[kind];
    var size = { apartments: [16, 16], home: [10, 10], "case": [13, 12], old: [16, 15] }[kind];
    return L.divIcon({ className: "site-mark", html: svg, iconSize: size, iconAnchor: [size[0] / 2, size[1] / 2] });
  }
  function popup(title, lines, link) {
    var box = el("div");
    box.appendChild(el("strong", null, title));
    lines.forEach(function (t) { if (t) box.appendChild(el("div", null, t)); });
    if (link) {
      var a = el("a", null, link[0]);
      a.href = link[1]; a.rel = "noopener";
      box.appendChild(a);
    }
    return box;
  }
  function buildMap() {
    var mapEl = $("map");
    var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
    map = L.map(mapEl, { zoomControl: false, minZoom: 8, maxZoom: 17, zoomSnap: 0.25, scrollWheelZoom: FULL });
    map.on("click focus", function () { map.scrollWheelZoom.enable(); });
    mapEl.addEventListener("mouseleave", function () { if (!FULL) map.scrollWheelZoom.disable(); });
    map.createPane("labels").style.zIndex = 450;
    map.getPane("labels").style.pointerEvents = "none";
    base = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 18,
      attribution: "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS user community" }).addTo(map);
    labels = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 18, pane: "labels" }).addTo(map);
    imagery = L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 18, maxZoom: 18,
      attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS user community" });
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution("Pima County Assessor, City of Tucson, Census");
    L.control.scale({ imperial: true, metric: true, position: "topleft" }).addTo(map);

    hexLayer = L.layerGroup();
    d.winter.hexes.forEach(function (h) {
      var p = L.polygon(h.c, { className: "hex", color: "#fff", weight: 0.6, fillColor: RAMP[band(h.n, HEX_BREAKS)], fillOpacity: 0.82 });
      areaTip(p, function () { return [fmt(h.n) + " winter homes", pct1(h.n, h.homes) + " of the " + fmt(h.homes) + " homes in this hexagon."]; });
      hexLayer.addLayer(p);
    });
    tractLayer = L.layerGroup();
    d.tracts.forEach(function (t) {
      var rate = t.other / t.units * 100;
      var p = L.polygon(t.g, { className: "hex", color: "#fff", weight: 0.6, fillColor: RAMP[band(rate, TRACT_BREAKS)], fillOpacity: 0.78 });
      areaTip(p, function () {
        return ["About " + fmt(t.other) + " other vacant homes", rate.toFixed(1) + "% of " + fmt(t.units) + " homes in this tract, give or take " + fmt(t.other_moe) + " homes."];
      });
      tractLayer.addLayer(p);
    });
    unfLayer = L.layerGroup();
    d.unfinished.sites.forEach(function (s) {
      if (s.kind === "commercial") return;
      var m = L.marker([s.lat, s.lon], { icon: icon(s.kind === "apartments" ? "apartments" : "home"), title: "Unfinished: " + s.use, alt: "Unfinished: " + s.use,
        zIndexOffset: s.kind === "apartments" ? 500 : 0 })
        .bindPopup(popup(s.addr || "No street address on record", [s.use + ".", s.acres + " acres, " + s.juris + ".",
          s.changed ? "Parcel record last changed in " + s.changed + "." : null, "Listed as partially complete; work may be under way."]), { maxWidth: 250 });
      if (s.parcel === "101051300") aerieMarker = m;
      unfLayer.addLayer(m);
    });
    caseLayer = L.layerGroup();
    d.cases.open.forEach(function (c) {
      var old = c.years >= 2;
      caseLayer.addLayer(L.marker([c.lat, c.lon], { icon: icon(old ? "old" : "case"), title: "Vacant-building case: " + c.addr, alt: "Vacant-building case: " + c.addr,
        zIndexOffset: old ? 800 : 300 })
        .bindPopup(popup(c.addr, ["Vacant-building case, open since " + longDate(c.opened) + (old ? " (" + c.years.toFixed(1) + " years)." : "."),
          "Status: " + c.status + "."], ["City of Tucson record", c.url]), { maxWidth: 250 }));
    });

    // open on the Tucson basin and Green Valley; Ajo and the far west are a pan away
    fullBounds = L.latLngBounds([[31.80, -111.30], [32.50, -110.70]]);
    map.fitBounds(fullBounds, { animate: false });
    var touched = false;
    mapEl.addEventListener("pointerdown", function () { touched = true; });
    mapEl.addEventListener("wheel", function () { touched = true; }, { passive: true });
    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        map.invalidateSize();
        if (!touched) map.fitBounds(fullBounds, { animate: false });
      }).observe(mapEl);
    }

    function onClick(id, fn) { var b = $(id); if (b) b.addEventListener("click", fn); }
    onClick("tb-in", function () { touched = true; map.zoomIn(); });
    onClick("tb-out", function () { touched = true; map.zoomOut(); });
    onClick("tb-full", function () { map.closePopup(); map.fitBounds(fullBounds); });
    onClick("aerie", function () {
      if (!aerieMarker) return;
      touched = true;
      on.unfinished = true;
      render();
      map.setView(aerieMarker.getLatLng(), 15);
      aerieMarker.openPopup();
      $("map").scrollIntoView({ block: "center" });
    });
    var sat = $("tb-base");
    sat.addEventListener("click", function () {
      var show = sat.getAttribute("aria-pressed") !== "true";
      sat.setAttribute("aria-pressed", show ? "true" : "false");
      if (show) { map.removeLayer(base); map.removeLayer(labels); imagery.addTo(map); }
      else { map.removeLayer(imagery); base.addTo(map); labels.addTo(map); }
    });
    var pos = $("sb-pos");
    function coord(ll) { return Math.abs(ll.lat).toFixed(4) + "° N, " + Math.abs(ll.lng).toFixed(4) + "° W"; }
    map.on("mousemove", function (e) { pos.textContent = coord(e.latlng); });
    map.on("mouseout", function () { pos.textContent = coord(map.getCenter()); });
    pos.textContent = coord(map.getCenter());
  }
  function statusText() {
    return shade === "winter" ? "Winter homes per hexagon. Point at one for its count."
      : "Homes vacant for other reasons, by Census tract. Point at one for its estimate.";
  }
  function renderMap() {
    [[hexLayer, shade === "winter"], [tractLayer, shade === "census"], [unfLayer, on.unfinished], [caseLayer, on.cases]].forEach(function (x) {
      if (x[1] && !map.hasLayer(x[0])) x[0].addTo(map);
      if (!x[1] && map.hasLayer(x[0])) map.removeLayer(x[0]);
    });
    $("viewer-title").textContent = "Empty Homes Viewer: " + (shade === "winter" ? "Winter Homes" : "Other Vacant Homes (Census)");
    setMsg(statusText());
    var legend = $("map-legend");
    legend.textContent = "";
    function item(cls, text, colour) {
      var li = el("li"), s = el("span", cls);
      if (colour) s.style.background = colour;
      li.appendChild(s);
      li.appendChild(el("span", null, text));
      legend.appendChild(li);
    }
    (shade === "winter" ? HEX_LABELS : TRACT_LABELS).forEach(function (t, i) { item("sw", t, RAMP[i]); });
    if (on.unfinished) { item("sq", "Unfinished apartments"); item("sq small", "Unfinished house or condo"); }
    if (on.cases) { item("tri", "Vacant-building case, open"); item("tri old", "Open two years or more"); }
  }

  function render() {
    renderSettings();
    renderMap();
  }
  function fail(msg) {
    var e = $("map-error");
    if (e) { e.textContent = msg; e.hidden = false; }
    setMsg("Could not load the data.");
  }

  readQuery();
  buildSettings();
  fetch("/empty-homes/data/empty.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (got) {
    d = got;
    fillStatic();
    renderCompare();
    renderOrigin();
    renderTables();
    buildMap();
    render();
  }).catch(function (err) {
    fail("The data did not load. Reload the page to try again.");
    if (window.console) console.error(err);
  });
})();
