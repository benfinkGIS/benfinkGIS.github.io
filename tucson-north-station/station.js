/* A Northern Station: map, figures and tables.
   Reads data/station.json (written by tools/build_north_station.py).
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
  var pct = function (x) { return Math.round(x * 100) + "%"; };
  var cap = function (t) { return t.charAt(0).toUpperCase() + t.slice(1); };

  var SHOW = [["pass", "Sites that pass", "pass"], ["out", "Sites ruled out", "out"],
              ["reach", "Drive area of the chosen site", "reach"], ["depot", "Drive area of the depot", "dl"]];
  var d, limit = 20, pick = null, on = { pass: true, out: true, reach: true, depot: true };
  var map, base, labels, imagery, imgLabels, fullBounds;
  var siteLayers = {}, tagLayers = {}, passGroup, outGroup, reachLayer, depotLayer;

  function passing() { return d.sites.filter(function (s) { return s.pass; }); }
  function byLabel(l) { return d.sites.filter(function (s) { return s.label === l; })[0]; }
  function ranked() {
    return passing().slice().sort(function (a, b) { return b.fresh[limit] - a.fresh[limit]; });
  }
  function setMsg(t) { var m = $("sb-msg"); if (m) m.textContent = t; }
  function siteName(s) { return s.label ? "Site " + s.label : "Ruled out"; }

  // ---- settings: toolbar-style buttons; the choices ride along in the address ----
  function readQuery() {
    var q = new URLSearchParams(location.search), l = parseInt(q.get("limit"), 10), show = q.get("show");
    if ([15, 20, 30].indexOf(l) >= 0) limit = l;
    if (q.get("site")) pick = q.get("site").toUpperCase();
    if (show !== null) {
      var want = show.split(",");
      SHOW.forEach(function (s) { on[s[0]] = want.indexOf(s[0]) >= 0; });
    }
  }
  function writeQuery() {
    var show = SHOW.filter(function (s) { return on[s[0]]; }).map(function (s) { return s[0]; }).join(",");
    history.replaceState(null, "", location.pathname + "?limit=" + limit + "&site=" + pick + "&show=" + show);
    document.querySelectorAll("a[data-carry]").forEach(function (a) { a.href = a.getAttribute("data-carry") + location.search; });
  }
  function buildSettings() {
    d.limits.forEach(function (l) {
      var b = el("button", null, l + " minutes");
      b.type = "button";
      b.addEventListener("click", function () { limit = l; render(); });
      $("limit-buttons").appendChild(b);
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
    d.limits.forEach(function (l, i) { $("limit-buttons").children[i].setAttribute("aria-pressed", l === limit ? "true" : "false"); });
    SHOW.forEach(function (s, i) { $("show-buttons").children[i].setAttribute("aria-pressed", on[s[0]] ? "true" : "false"); });
    writeQuery();
  }

  // ---- figures ----
  function fill(key, text) {
    document.querySelectorAll('[data-fill="' + key + '"]').forEach(function (n) { n.textContent = text; });
  }
  function fillStatic() {
    var a = d.assumptions, sp = a.speeds_mph;
    fill("minmi", a.min_rail_mi);
    fill("linemi", d.county_line_mi);
    fill("parcels", fmt(d.funnel.parcels));
    fill("corridor", fmt(a.corridor_ft));
    fill("gap", a.row_gap_ft);
    fill("frontage", fmt(a.min_frontage_ft));
    fill("acres", a.min_acres);
    fill("depth", a.min_depth_ft);
    fill("built", pct(a.max_built_share));
    fill("open", d.funnel.open_sites);
    fill("failed", d.funnel.open_sites - d.funnel.passing);
    fill("county", fmt(d.county_pop));
    fill("npass", d.funnel.passing);
    fill("wet", passing().filter(function (s) { return s.floodplain >= 0.5; }).length);
    fill("speeds", "driven at " + sp.INTERSTATE + " mph on the interstate, " + sp.FRNT_RD + " on frontage roads, " +
      sp.ST_RT + " on state routes, " + sp.LRD_MJ + " on major streets and " + sp.LRD_MN + " on local streets");
  }
  function renderLead() {
    var s = byLabel(pick);
    $("hero-num").textContent = fmt(s.fresh[limit]);
    $("hero-lab").textContent = "residents within " + limit + " minutes of Site " + s.label + " (rail mile " + s.mile +
      ") who are more than " + limit + " minutes from the downtown depot";
    $("pass-num").textContent = d.funnel.passing + " of " + d.funnel.open_sites;
    $("pass-lab").textContent = "pieces of open land beside the track pass the screen";
    $("depot-num").textContent = fmt(d.depot.within[limit]);
    $("depot-lab").textContent = "county residents (" + pct(d.depot.within[limit] / d.county_pop) + ") are within " +
      limit + " minutes of the downtown depot";
  }

  // ---- ranked bars ----
  function renderRank() {
    var host = $("rank"), rows = ranked(), max = rows[0].fresh[limit] || 1;
    $("rank-cap").textContent = "Residents within " + limit + " minutes of each site and more than " + limit +
      " minutes from the downtown depot. Most first. Pick a site to see it on the map.";
    host.textContent = "";
    rows.forEach(function (s) {
      var b = el("button", "pick");
      b.type = "button";
      b.setAttribute("aria-pressed", s.label === pick ? "true" : "false");
      b.appendChild(el("span", "nm", "Site " + s.label));
      b.appendChild(el("small", null, "mile " + s.mile.toFixed(1) + " · " + s.owner));
      b.addEventListener("click", function () { choose(s.label, true); });
      var name = el("div", "name");
      name.appendChild(b);
      var track = el("div", "track"), bar = el("div", "bar");
      bar.style.width = "calc((100% - 190px) * " + (s.fresh[limit] / max).toFixed(4) + ")";
      track.appendChild(bar);
      var val = el("span", "val", fmt(s.fresh[limit]) + " ");
      val.appendChild(el("small", null, "of " + fmt(s.within[limit]) + " in reach"));
      track.appendChild(val);
      host.appendChild(name);
      host.appendChild(track);
    });
  }

  // ---- tables ----
  function headRow(t, cols) {
    var head = el("tr");
    cols.forEach(function (h) { var th = el("th", h[1], h[0]); th.scope = "col"; head.appendChild(th); });
    var thead = el("thead"); thead.appendChild(head); t.appendChild(thead);
  }
  function renderPass() {
    var t = $("t-pass");
    t.textContent = "";
    headRow(t, [["Site", ""], ["Rail mile", "num"], ["Owner", ""], ["Usable acres", "num"], ["Beside the track", "num"],
      ["In a 1% flood zone", "num"], ["Street in", ""], ["To an I-10 ramp", "num"],
      ["Within " + limit + " min", "num"], ["New within " + limit + " min", "num"], ["Watch for", ""]]);
    var body = el("tbody");
    passing().forEach(function (s) {
      var tr = el("tr", s.label === pick ? "on" : null), first = el("td"), b = el("button", null, "Site " + s.label);
      b.type = "button";
      b.addEventListener("click", function () { choose(s.label, true); });
      first.appendChild(b);
      tr.appendChild(first);
      tr.appendChild(el("td", "num", s.mile.toFixed(1)));
      tr.appendChild(el("td", null, s.owner + " (" + s.use.join(", ") + ")"));
      tr.appendChild(el("td", "num", fmt(s.usable)));
      tr.appendChild(el("td", "num", fmt(s.frontage) + " ft"));
      tr.appendChild(el("td", "num", pct(s.floodplain)));
      tr.appendChild(el("td", null, s.street || ""));
      tr.appendChild(el("td", "num", s.ramp_min.toFixed(0) + " min"));
      tr.appendChild(el("td", "num", fmt(s.within[limit])));
      tr.appendChild(el("td", "num", fmt(s.fresh[limit])));
      tr.appendChild(el("td", "watch", s.cautions.length ? cap(s.cautions.join("; ")) : "Nothing flagged"));
      body.appendChild(tr);
    });
    t.appendChild(body);
  }
  function renderFail() {
    var t = $("t-fail");
    t.textContent = "";
    headRow(t, [["Rail mile", "num"], ["Side of the track", ""], ["Owner", ""], ["Acres", "num"], ["Why it is out", ""]]);
    var body = el("tbody");
    d.sites.filter(function (s) { return !s.pass; }).forEach(function (s) {
      var tr = el("tr");
      tr.appendChild(el("td", "num", s.mile.toFixed(1)));
      tr.appendChild(el("td", null, s.side));
      tr.appendChild(el("td", null, s.owner));
      tr.appendChild(el("td", "num", s.acres.toFixed(1)));
      tr.appendChild(el("td", null, s.fails.join("; ")));
      body.appendChild(tr);
    });
    t.appendChild(body);
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

  // ---- map ----
  function latlngs(geom) {
    return geom.map(function (poly) { return poly.map(function (ring) { return ring.map(function (c) { return [c[1], c[0]]; }); }); });
  }
  function popup(s) {
    var box = el("div");
    box.appendChild(el("strong", null, siteName(s) + ", rail mile " + s.mile));
    var lines = [
      s.owner + ", " + s.use.join(" and ") + (s.juris.length ? " (" + s.juris.join(", ") + ")" : ""),
      s.acres.toFixed(1) + " acres on the " + s.side + " side of the track" + (s.pass ? ", " + fmt(s.usable) + " usable" : ""),
      fmt(s.frontage) + " ft beside the track",
      pct(s.floodplain) + " in a 1% flood zone" + (s.floodway > 0.005 ? ", " + pct(s.floodway) + " in the floodway" : "")
    ];
    if (s.zoning.length) lines.push("Zoning: " + s.zoning.join(", "));
    if (s.pass) {
      lines.push("Street in: " + s.street + "; " + s.ramp_min.toFixed(0) + " min to an I-10 ramp");
      lines.push(fmt(s.within[limit]) + " residents within " + limit + " min, " + fmt(s.fresh[limit]) + " of them beyond " + limit + " min of the depot");
      if (s.cautions.length) lines.push("Watch for: " + s.cautions.join("; "));
    } else {
      lines.push("Out: " + s.fails.join("; "));
    }
    lines.forEach(function (t) { box.appendChild(el("div", null, t)); });
    return box;
  }
  function tagIcon(s, chosen) {
    return L.divIcon({ className: "site-tag" + (chosen ? " on" : ""), html: "<b>" + s.label + "</b>", iconSize: [18, 18], iconAnchor: [9, 9] });
  }
  function siteStyle(s) {
    if (!s.pass) return { pane: "sites", color: "#ffffff", weight: 1.5, dashArray: "4 3", fillColor: "#8a8a8a", fillOpacity: 0.55 };
    var chosen = s.label === pick;
    return { pane: "sites", color: chosen ? "#ffff00" : "#ffffff", weight: chosen ? 3.5 : 1.5, fillColor: "#eb6834", fillOpacity: chosen ? 0.6 : 0.75 };
  }
  function buildMap() {
    var mapEl = $("map");
    var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
    map = L.map(mapEl, { zoomControl: false, minZoom: 9, maxZoom: 18, zoomSnap: 0.25, scrollWheelZoom: FULL });
    map.on("click focus", function () { map.scrollWheelZoom.enable(); });
    mapEl.addEventListener("mouseleave", function () { if (!FULL) map.scrollWheelZoom.disable(); });
    [["reach", false], ["lines", false], ["sites", true], ["labels", false]].forEach(function (p, i) {
      map.createPane(p[0]).style.zIndex = 405 + 5 * i;
      if (!p[1]) map.getPane(p[0]).style.pointerEvents = "none";
    });
    base = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 18,
      attribution: "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS user community" });
    labels = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 18, pane: "labels" });
    imagery = L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 18, maxZoom: 18,
      attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS user community" }).addTo(map);
    imgLabels = L.tileLayer(ESRI + "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 18, maxZoom: 18, pane: "labels" }).addTo(map);
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution("Pima County GIS, FEMA, 2020 Census");
    L.control.scale({ imperial: true, metric: false }).addTo(map);

    var rail = d.rail.map(function (c) { return [c[1], c[0]]; });
    L.polyline(rail, { pane: "lines", interactive: false, color: "#ffffff", weight: 6, opacity: 0.95 }).addTo(map);
    L.polyline(rail, { pane: "lines", interactive: false, color: "#000000", weight: 3, dashArray: "9 6" }).addTo(map);
    d.miles.forEach(function (m) {
      if (m[0] === 0 || m[0] % 2) return;
      L.marker([m[2], m[1]], { interactive: false, keyboard: false, pane: "labels",
        icon: L.divIcon({ className: "mile-tag", html: "<span>" + m[0] + "</span>", iconSize: [22, 12], iconAnchor: [11, -5] }) }).addTo(map);
    });
    L.marker([d.depot.lat, d.depot.lon], { title: "Downtown Tucson depot", alt: "Downtown Tucson depot", zIndexOffset: 500,
      icon: L.divIcon({ className: "depot-mark", iconSize: [20, 20], iconAnchor: [10, 10],
        html: '<svg width="20" height="20" viewBox="0 0 20 20"><path d="M10 1l2.6 5.6 6.1.7-4.5 4.2 1.2 6L10 14.5 4.6 17.5l1.2-6L1.3 7.3l6.1-.7z" fill="#ffff00" stroke="#000" stroke-width="1.6" stroke-linejoin="round"/></svg>' }) })
      .bindPopup("<strong>Downtown Tucson depot</strong><div>400 N Toole Ave. Rail mile 0.</div>", { maxWidth: 220 }).addTo(map);

    passGroup = L.layerGroup();
    outGroup = L.layerGroup();
    d.sites.forEach(function (s) {
      var layer = L.polygon(latlngs(s.geom), siteStyle(s));
      layer.bindPopup(function () { return popup(s); }, { maxWidth: 280 });
      layer.on("click", function () { if (s.pass) choose(s.label, false); });
      layer.on("mousemove", function (e) {
        var text = s.pass ? s.owner + ". " + fmt(s.fresh[limit]) + " residents newly within " + limit + " minutes."
          : s.owner + ". " + s.fails.join("; ") + ".";
        showTip(e.originalEvent.clientX, e.originalEvent.clientY, siteName(s) + ", mile " + s.mile, text);
      });
      layer.on("mouseout", hideTip);
      layer.addTo(s.pass ? passGroup : outGroup);
      siteLayers[s.id] = layer;
      if (s.pass) {
        var tag = L.marker([s.lat, s.lon], { icon: tagIcon(s, false), title: "Site " + s.label, alt: "Site " + s.label, zIndexOffset: 800 });
        tag.on("click", function () { choose(s.label, false); layer.openPopup(); });
        tag.addTo(passGroup);
        tagLayers[s.label] = tag;
      }
    });

    fullBounds = L.latLngBounds(rail).pad(0.08);
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
    onClick("tb-site", function () { touched = true; zoomTo(pick); });
    var sat = $("tb-base");
    sat.addEventListener("click", function () {
      var show = sat.getAttribute("aria-pressed") !== "true";
      sat.setAttribute("aria-pressed", show ? "true" : "false");
      if (show) { map.removeLayer(base); map.removeLayer(labels); imagery.addTo(map); imgLabels.addTo(map); }
      else { map.removeLayer(imagery); map.removeLayer(imgLabels); base.addTo(map); labels.addTo(map); }
    });
    var pos = $("sb-pos");
    function coord(ll) { return Math.abs(ll.lat).toFixed(4) + "° N, " + Math.abs(ll.lng).toFixed(4) + "° W"; }
    map.on("mousemove", function (e) { pos.textContent = coord(e.latlng); });
    map.on("mouseout", function () { pos.textContent = coord(map.getCenter()); });
    pos.textContent = coord(map.getCenter());
    zoomTo.touch = function () { touched = true; };
  }
  function zoomTo(label) {
    var s = byLabel(label);
    if (!s) return;
    if (zoomTo.touch) zoomTo.touch();
    // no animation in a background tab: browsers pause it there and the map would stop half way
    map.fitBounds(siteLayers[s.id].getBounds().pad(0.6), { maxZoom: 17, animate: !document.hidden });
  }
  function area(key, style) {
    var g = d.sheds[key] && d.sheds[key][limit];
    return g && g.length ? L.polygon(latlngs(g), style) : null;
  }
  function renderMap() {
    d.sites.forEach(function (s) { siteLayers[s.id].setStyle(siteStyle(s)); });
    Object.keys(tagLayers).forEach(function (l) { tagLayers[l].setIcon(tagIcon(byLabel(l), l === pick)); });
    [[passGroup, on.pass], [outGroup, on.out]].forEach(function (x) {
      if (x[1] && !map.hasLayer(x[0])) x[0].addTo(map);
      if (!x[1] && map.hasLayer(x[0])) map.removeLayer(x[0]);
    });
    if (reachLayer) { map.removeLayer(reachLayer); reachLayer = null; }
    if (depotLayer) { map.removeLayer(depotLayer); depotLayer = null; }
    if (on.reach) {
      reachLayer = area(pick, { pane: "reach", interactive: false, color: "#2a78d6", weight: 2.5, fillColor: "#2a78d6", fillOpacity: 0.22 });
      if (reachLayer) reachLayer.addTo(map);
    }
    if (on.depot) {
      var halo = area("depot", { pane: "reach", interactive: false, color: "#ffffff", weight: 4.5, fill: false, opacity: 0.9 });
      var line = area("depot", { pane: "reach", interactive: false, color: "#000000", weight: 2, dashArray: "7 5", fill: false });
      if (halo && line) depotLayer = L.layerGroup([halo, line]).addTo(map);
    }
    var s = byLabel(pick);
    setMsg("Site " + s.label + ", rail mile " + s.mile + ": " + fmt(s.within[limit]) + " residents within " + limit +
      " minutes, " + fmt(s.fresh[limit]) + " of them out of the depot's reach.");
    var legend = $("map-legend");
    legend.textContent = "";
    function item(cls, text, glyph) {
      var li = el("li");
      li.appendChild(el("span", cls, glyph));
      li.appendChild(el("span", null, text));
      legend.appendChild(li);
    }
    if (on.pass) item("sw pass", "Passes the screen");
    if (on.out) item("sw out", "Ruled out");
    if (on.reach) item("sw reach", limit + " min drive to Site " + pick);
    if (on.depot) item("dline", limit + " min drive to the depot");
    item("rail", "Union Pacific main line");
    item("star", "Downtown depot", "★");
  }

  function choose(label, zoom) {
    pick = label;
    render();
    if (zoom) {
      zoomTo(label);
      if (!FULL) $("map").scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }
  function render() {
    renderSettings();
    renderLead();
    renderRank();
    renderPass();
    renderMap();
  }
  function fail(msg) {
    var e = $("map-error");
    if (e) { e.textContent = msg; e.hidden = false; }
    setMsg("Could not load the data.");
  }

  readQuery();
  fetch("/tucson-north-station/data/station.json")
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (got) {
      d = got;
      if (!byLabel(pick) || !byLabel(pick).pass) pick = ranked()[0].label;
      buildSettings();
      fillStatic();
      renderFail();
      buildMap();
      render();
    }).catch(function (err) {
      fail("The station data did not load. Reload the page to try again.");
      if (window.console) console.error(err);
    });
})();
