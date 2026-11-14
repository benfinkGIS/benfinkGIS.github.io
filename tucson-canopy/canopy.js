/* Neighborhood Canopy: map, figures and tables.
   Reads data/canopy.json and the overlay images beside it (written by
   tools/canopy/15_publish_web.py). Leaflet 1.9.4 is loaded by the page. */
(function () {
  "use strict";
  /* The full-page map (map/index.html) has only the viewer. An id that is not on the page gets a
     spare element, so the figures and tables written for the project page go nowhere there. */
  var spare = {};
  var $ = function (id) { return document.getElementById(id) || spare[id] || (spare[id] = document.createElement("div")); };
  var FULL = document.body.classList.contains("fullmap");
  var DATA = "/tucson-canopy/data/";
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  var fmt = function (n) { return Math.round(n).toLocaleString("en-US"); };
  var p1 = function (x) { return x.toFixed(1) + "%"; };
  var p0 = function (x) { return Math.round(x) + "%"; };
  function fill(key, text) {
    document.querySelectorAll('[data-fill="' + key + '"]').forEach(function (n) { n.textContent = text; });
  }

  var VIEWS = [["canopy", "Tree canopy", "canopy"], ["shade", "Shade at 4 p.m. in July", "shade"], ["cover", "Land cover", "cover"]];
  var d, site = 1, scen = 0, view = "canopy", frac = 0.5;
  var map, base, labels, imagery, imgLabels, canvas, swipeEl, tagL, tagR;
  var images = {}, treeGroups = {}, outlines = [], shown = { left: [], right: [] };

  function S() { return d.sites[site]; }
  function P() { return S().scenarios[scen]; }
  function setMsg(t) { $("sb-msg").textContent = t; }

  // ---- settings: toolbar-style buttons; the choices ride along in the address ----
  function readQuery() {
    var q = new URLSearchParams(location.search), p = parseInt(q.get("plant"), 10);
    if (p >= 1 && p <= 3) scen = p - 1;
    if (VIEWS.some(function (v) { return v[0] === q.get("show"); })) view = q.get("show");
    readQuery.site = q.get("site");
  }
  function writeQuery() {
    history.replaceState(null, "", location.pathname + "?site=" + S().id + "&plant=" + (scen + 1) + "&show=" + view);
    document.querySelectorAll("a[data-carry]").forEach(function (a) { a.href = a.getAttribute("data-carry") + location.search; });
  }
  function buildSettings() {
    function add(box, text, fn, sw) {
      var b = el("button");
      b.type = "button";
      if (sw) b.appendChild(el("span", "sw " + sw));
      b.appendChild(document.createTextNode(text));
      b.addEventListener("click", fn);
      $(box).appendChild(b);
    }
    d.sites.forEach(function (s, i) { add("site-buttons", s.name, function () { site = i; render(true); }); });
    d.scenarios.forEach(function (n, i) { add("plant-buttons", n, function () { scen = i; render(); }); });
    VIEWS.forEach(function (v) { add("show-buttons", v[1], function () { view = v[0]; render(); }, v[2]); });
  }
  function press(box, on) {
    Array.prototype.forEach.call($(box).children, function (b, i) { b.setAttribute("aria-pressed", i === on ? "true" : "false"); });
  }
  function renderSettings() {
    press("site-buttons", site);
    press("plant-buttons", scen);
    press("show-buttons", VIEWS.map(function (v) { return v[0]; }).indexOf(view));
    writeQuery();
  }

  // ---- figures ----
  function renderStats() {
    var s = S(), p = P(), low = p.name.charAt(0).toLowerCase() + p.name.slice(1);
    $("hero-num").textContent = p1(p.canopy);
    $("hero-lab").textContent = "tree canopy in " + s.name + " with " + low + " at mature size, up from " + p1(s.today.canopy) + " today";
    $("tree-num").textContent = fmt(p.trees);
    $("tree-lab").textContent = "native trees planted, " + p0(p.runoff_fed * 100) + " of them where roof or street runoff collects";
    $("shade-num").textContent = p0(p.edge);
    $("shade-lab").textContent = "of the street edge in shade at 4 p.m. in July, up from " + p0(s.today.edge) + " today";
  }
  function row(cells, head) {
    var tr = el("tr");
    cells.forEach(function (c, i) {
      var td = el(head ? "th" : "td", i ? "num" : null);
      if (head) td.scope = "col";
      if (c instanceof Node) td.appendChild(c); else td.textContent = c;
      tr.appendChild(td);
    });
    return tr;
  }
  function withSmall(main, small) {
    var f = document.createDocumentFragment();
    f.appendChild(document.createTextNode(main));
    f.appendChild(el("small", null, small));
    return f;
  }
  function renderScenTable() {
    var s = S(), t = $("t-scen");
    t.textContent = "";
    var head = el("thead"), body = el("tbody");
    head.appendChild(row(["", "Trees planted", "Tree canopy", "Street edge in shade", "Pavement in shade",
                          "Carbon stored, tonnes", "Surface temperature"], true));
    body.appendChild(row(["Today", "", p1(s.today.canopy), p0(s.today.edge), p0(s.today.pavement), "",
                          s.lst.toFixed(1) + " °C"]));
    s.scenarios.forEach(function (p, i) {
      var tr = row([p.name, fmt(p.trees), p1(p.canopy), p0(p.edge), p0(p.pavement),
                    withSmall(fmt(p.carbon), fmt(p.carbon_low) + " to " + fmt(p.carbon_high)),
                    withSmall(p.lst.toFixed(1).replace("-", "−") + " °C", "weak estimate")]);
      if (i === scen) tr.className = "on";
      body.appendChild(tr);
    });
    t.appendChild(head);
    t.appendChild(body);
  }
  function renderBars() {
    var box = $("bars"), max = 0;
    box.textContent = "";
    d.sites.forEach(function (s) { s.scenarios.forEach(function (p) { max = Math.max(max, p.canopy); }); });
    d.sites.forEach(function (s, si) {
      box.appendChild(el("h3", null, s.name));
      [["Today", s.today.canopy, true]].concat(s.scenarios.map(function (p) { return [p.name, p.canopy, false]; }))
        .forEach(function (r, i) {
          var on = si === site && i === scen + 1;
          var lab = el("div", "lab", r[0]), track = el("div", "track");
          var bar = el("div", "bar" + (r[2] ? " now" : ""));
          bar.style.width = (r[1] / max * 82) + "%";
          bar.title = s.name + ", " + r[0].toLowerCase() + ": " + p1(r[1]) + " tree canopy";
          track.appendChild(bar);
          track.appendChild(el("span", "val", p1(r[1])));
          if (on) { lab.className += " on"; track.className += " on"; }
          var wrapA = el("div", on ? "on" : null), wrapB = el("div", on ? "on" : null);
          wrapA.appendChild(lab);
          wrapB.appendChild(track);
          box.appendChild(wrapA);
          box.appendChild(wrapB);
        });
    });
  }
  function renderSpecies() {
    var p = P(), t = $("t-species");
    t.textContent = "";
    var head = el("thead"), body = el("tbody");
    head.appendChild(row(["Species", "Mature height", "Mature width", "Water need", "In this planting", "Share"], true));
    d.species.forEach(function (sp, i) {
      var name = document.createDocumentFragment(), dot = el("span", "dot");
      dot.style.background = sp.colour;
      var a = el("a", null, sp.name);
      a.href = sp.url;
      name.appendChild(dot);
      name.appendChild(a);
      name.appendChild(document.createTextNode(" "));
      name.appendChild(el("small", null, sp.latin));
      body.appendChild(row([name, sp.height_ft + " ft", sp.width_ft + " ft", sp.water,
                            fmt(p.by_species[i]), p0(p.by_species[i] / p.trees * 100)]));
    });
    t.appendChild(head);
    t.appendChild(body);
  }
  function list(items) {
    if (items.length < 2) return items.join("");
    return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
  }
  function renderHabitat() {
    var s = S(), c = s.context, t = $("t-link");
    // where the neighborhood sits
    var through = c.washes.filter(function (w) { return w.distance_m === 0; }).map(function (w) { return w.name; });
    var near = c.washes.filter(function (w) { return w.distance_m > 0; }).slice(0, 2)
      .map(function (w) { return w.name + " (" + fmt(w.distance_m) + " m)"; });
    var parks = c.parks.slice(0, 3).map(function (p) {
      return p.name + (p.distance_m ? " (" + fmt(p.distance_m) + " m)" : " (adjoining)");
    });
    var txt = through.length
      ? "The county\u2019s wash map shows " + list(through) + " running through or along " + s.name + ". "
      : "No mapped wash runs through " + s.name + ". ";
    if (near.length) txt += "The next nearest are " + list(near) + ". ";
    txt += c.riparian.nearest_m == null
      ? "No mapped riparian habitat lies within a kilometre. "
      : "The nearest mapped riparian habitat is " + fmt(c.riparian.nearest_m) + " m from the boundary, with " +
        fmt(c.riparian.total_ha) + " hectares of it within a kilometre. ";
    if (parks.length) txt += "The nearest parks and open spaces are " + list(parks) + ".";
    $("ctx-text").textContent = txt;

    t.textContent = "";
    var head = el("thead"), body = el("tbody");
    head.appendChild(row(["", "Average distance to the nearest crown", "Ground within 5 m of a crown",
                          "Canopy in the largest linked cluster", "Canopy linked to riparian habitat"], true));
    s.structure.forEach(function (r, i) {
      var tr = row([i ? s.scenarios[i - 1].name : "Today", r.mean_distance_to_canopy_m.toFixed(1) + " m",
                    p0(r.within_5m_pct), p0(r.largest_cluster_share * 100),
                    r.linked_to_riparian_share == null ? "none in reach" : p0(r.linked_to_riparian_share * 100)]);
      if (i === scen + 1) tr.className = "on";
      body.appendChild(tr);
    });
    t.appendChild(head);
    t.appendChild(body);

    var rec = s.records, tr2 = $("t-rec");
    tr2.textContent = "";
    head = el("thead");
    body = el("tbody");
    head.appendChild(row(["Group", "Records inside", "Species inside", "Records within 1 km",
                          "Species within 1 km", "Most recorded within 1 km"], true));
    Object.keys(rec.near.groups).forEach(function (g) {
      var a = rec.inside.groups[g], b = rec.near.groups[g];
      var tr = row([g, fmt(a.records), fmt(a.species), fmt(b.records), fmt(b.species), b.top.join(", ")]);
      tr.lastChild.className = "";
      body.appendChild(tr);
    });
    var total = row(["Everything", fmt(rec.inside.records), fmt(rec.inside.species), fmt(rec.near.records),
                     fmt(rec.near.species), ""]);
    total.className = "on";
    body.appendChild(total);
    tr2.appendChild(head);
    tr2.appendChild(body);

    var top = rec.near.datasets[0], palette = [];
    d.species.forEach(function (sp) {
      var n = rec.near.palette[sp.name];
      if (n) palette.push(sp.name.toLowerCase() + " (" + n + ")");
    });
    $("rec-text").textContent =
      "Inside " + s.name + " there " + (rec.inside.records === 1 ? "is " : "are ") + fmt(rec.inside.records) + " record" + (rec.inside.records === 1 ? "" : "s") +
      "; within a kilometre there are " + fmt(rec.near.records) + ", " + p0(top.records / rec.near.records * 100) +
      " of them from " + (/eBird/.test(top.title) ? "eBird" : top.title) + ". " +
      (palette.length ? "The planting\u2019s own species have been recorded within that kilometre: " + list(palette) + "."
        : "None of the planting\u2019s four species has been recorded within that kilometre.");
    fill("gap", String(s.gap_m));
    fill("rec-since", String(rec.since));
    fill("rec-date", new Date(rec.queried + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }));
  }
  function renderAccuracy() {
    var a = d.accuracy.both, t = $("t-acc");
    t.textContent = "";
    var head = el("thead"), body = el("tbody");
    head.appendChild(row(["The map is asked", "Right, both neighborhoods", "Likely range"], true));
    [["tree canopy or not", "Is this tree canopy or not?"], ["impervious or not", "Is this roof or pavement, or not?"],
     ["open ground merged", "Which of five kinds of cover is this?"]].forEach(function (q) {
      var r = a[q[0]];
      body.appendChild(row([q[1], p1(r.overall * 100), p0(r.low * 100) + " to " + p0(r.high * 100)]));
    });
    t.appendChild(head);
    t.appendChild(body);
  }
  function fillStatic() {
    var a = d.accuracy, ds = d.sites[0], wh = d.sites[1];
    function room(s) { return p1(s.plantable.street + s.plantable.yard + s.plantable["park edge"]); }
    fill("ds-canopy", p1(ds.today.canopy));
    fill("wh-canopy", p1(wh.today.canopy));
    fill("ds-room", room(ds));
    fill("wh-room", room(wh));
    fill("spacing", "8");
    fill("fed-m2", "50");
    fill("acc-n", fmt(a.points));
    fill("cant", a.cant_tell === 1 ? "One point" : a.cant_tell + " points");
    fill("ua-tree", p0(a.both["open ground merged"].users["Tree canopy"] * 100));
    fill("ua-pave", p0(a.both["open ground merged"].users.Pavement * 100));
    fill("first-all", p1(a.first_map["all classes"] * 100));
    fill("first-tree", p1(a.first_map["tree canopy or not"] * 100));
    fill("c-store", String(d.carbon.storage));
    fill("c-low", String(d.carbon.low));
    fill("c-high", String(d.carbon.high));
    fill("blocks", fmt(d.heat.blocks));
    fill("block-m", String(d.heat.block_m));
    fill("r2", p0(d.heat.r2 * 100));
    fill("scatter", d.heat.scatter.toFixed(1));
    document.querySelectorAll('a[data-href="carbon"]').forEach(function (n) { n.href = d.carbon.url; });
  }
  function fillSite() {
    var s = S(), p = P();
    fill("site-name", s.name);
    fill("fed", p0(p.runoff_fed * 100));
    fill("density", String(Math.round(s.lidar_points_per_m2)));
    fill("sun-el", String(Math.round(s.sun.elevation)));
    fill("edge-km", s.street_edge_km.toFixed(1));
    fill("check", p0(s.photo_check.agreement * 100));
  }

  // ---- map ----
  function image(name, pane, opacity) {
    var s = S(), key = s.id + "_" + name + "@" + pane;
    if (!images[key]) {
      images[key] = L.imageOverlay(DATA + s.id + "_" + name + ".png", s.bounds,
        { pane: pane, opacity: opacity, interactive: false, className: "crisp" });
    }
    return images[key];
  }
  function trees(tier) {
    var s = S(), key = s.id + ":" + tier;
    if (!treeGroups[key]) {
      var g = L.featureGroup();
      s.trees.forEach(function (t) {
        if (t[3] !== tier) return;
        var sp = d.species[t[2]];
        L.circle([t[0], t[1]], { radius: sp.radius_m, renderer: canvas, pane: "right", color: "#fff", weight: 1,
                                 fillColor: sp.colour, fillOpacity: 0.92, tree: t }).addTo(g);
      });
      g.on("click", function (e) {
        var t = e.layer.options.tree, sp = d.species[t[2]];
        L.popup().setLatLng(e.latlng).setContent(
          "<strong>" + sp.name + "</strong><br><em>" + sp.latin + "</em><br>" +
          "Mature size: " + sp.height_ft + " ft tall, " + sp.width_ft + " ft wide<br>" +
          "Part of: " + d.scenarios[t[3] - 1] + "<br>" +
          (t[4] ? "Roof or street runoff collects here" : "No runoff collects here")).openOn(map);
      });
      treeGroups[key] = g;
    }
    return treeGroups[key];
  }
  function renderMap(refit) {
    var want = { left: [], right: [] };
    if (view === "canopy") {
      want.left.push(image("canopy", "left", 0.85));
      want.right.push(image("canopy", "right", 0.85));
      for (var t = 1; t <= scen + 1; t++) want.right.push(trees(t));
    } else if (view === "shade") {
      want.left.push(image("shade0", "left", 0.62));
      want.right.push(image("shade" + (scen + 1), "right", 0.62));
    } else {
      want.right.push(image("cover", "right", 0.85));
    }
    ["left", "right"].forEach(function (side) {
      shown[side].forEach(function (l) { if (want[side].indexOf(l) < 0) map.removeLayer(l); });
      want[side].forEach(function (l) { if (!map.hasLayer(l)) l.addTo(map); });
      shown[side] = want[side];
    });
    outlines.forEach(function (o, i) { o.setStyle({ color: i === site ? "#ffff00" : "#ffffff", weight: i === site ? 3 : 2 }); });
    if (refit) { map.closePopup(); map.fitBounds(outlines[site].getBounds().pad(0.04), { animate: false }); }
    tagL.textContent = view === "cover" ? "Aerial photo" : "Today";
    tagR.textContent = view === "cover" ? "Land cover" : P().name;
    renderLegend();
    clip();
    setMsg(S().name + ": " + (view === "cover" ? "land cover from lidar and imagery"
      : P().name.toLowerCase() + ", " + fmt(P().trees) + " trees"));
  }
  function renderLegend() {
    var lg = $("map-legend");
    lg.textContent = "";
    function item(cls, text, colour, shape) {
      var li = el("li"), sw = el("span", shape || "sw " + (cls || ""));
      if (colour) sw.style.background = colour;
      li.appendChild(sw);
      li.appendChild(document.createTextNode(text));
      lg.appendChild(li);
    }
    if (view === "canopy") {
      item("canopy", "Tree canopy today");
      d.species.forEach(function (sp) { item(null, sp.name, sp.colour, "dot"); });
    } else if (view === "shade") {
      item("shade", "Ground in shade at 4 p.m., 15 July (roofs left clear)");
    } else {
      Object.keys(d.colours.cover).forEach(function (k) { item(null, k, d.colours.cover[k]); });
    }
    item(null, "Neighborhood boundary", null, "ring");
  }
  // Each side of the divider is its own map pane, clipped to its half of the view
  function clip() {
    var size = map.getSize(), nw = map.containerPointToLayerPoint([0, 0]);
    var x = nw.x + size.x * frac, y0 = nw.y, y1 = nw.y + size.y, x0 = nw.x, x1 = nw.x + size.x;
    function poly(a, b) { return "polygon(" + a + "px " + y0 + "px," + b + "px " + y0 + "px," + b + "px " + y1 + "px," + a + "px " + y1 + "px)"; }
    map.getPane("left").style.clipPath = poly(x0, x);
    map.getPane("right").style.clipPath = poly(x, x1);
    swipeEl.style.left = (frac * 100) + "%";
    swipeEl.setAttribute("aria-valuenow", String(Math.round(frac * 100)));
    swipeEl.setAttribute("aria-valuetext", Math.round(frac * 100) + "% of the map shows today");
  }
  function buildSwipe(mapEl) {
    swipeEl = el("div", "swipe");
    swipeEl.tabIndex = 0;
    swipeEl.setAttribute("role", "slider");
    swipeEl.setAttribute("aria-label", "Divider between today, on the left, and the planting, on the right");
    swipeEl.setAttribute("aria-valuemin", "0");
    swipeEl.setAttribute("aria-valuemax", "100");
    swipeEl.setAttribute("aria-orientation", "horizontal");
    swipeEl.appendChild(el("div", "grip", "◄►"));
    tagL = el("div", "side-tag l");
    tagR = el("div", "side-tag r");
    mapEl.appendChild(tagL);
    mapEl.appendChild(tagR);
    mapEl.appendChild(swipeEl);
    L.DomEvent.disableClickPropagation(swipeEl);
    L.DomEvent.disableScrollPropagation(swipeEl);
    function at(e) {
      var r = mapEl.getBoundingClientRect();
      frac = Math.max(0.02, Math.min(0.98, (e.clientX - r.left) / r.width));
      clip();
    }
    swipeEl.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      e.stopPropagation();
      swipeEl.setPointerCapture(e.pointerId);
      swipeEl.focus({ preventScroll: true });
      function move(ev) { at(ev); }
      function up() {
        swipeEl.removeEventListener("pointermove", move);
        swipeEl.removeEventListener("pointerup", up);
        swipeEl.removeEventListener("pointercancel", up);
      }
      swipeEl.addEventListener("pointermove", move);
      swipeEl.addEventListener("pointerup", up);
      swipeEl.addEventListener("pointercancel", up);
    });
    swipeEl.addEventListener("keydown", function (e) {
      var step = e.key === "ArrowLeft" ? -0.05 : e.key === "ArrowRight" ? 0.05 : e.key === "Home" ? -1 : e.key === "End" ? 1 : 0;
      if (!step) return;
      e.preventDefault();
      e.stopPropagation();
      frac = Math.max(0.02, Math.min(0.98, frac + step));
      clip();
    });
  }
  function buildMap() {
    var mapEl = $("map");
    var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
    map = L.map(mapEl, { zoomControl: false, minZoom: 12, maxZoom: 20, zoomSnap: 0.25, scrollWheelZoom: FULL });
    map.on("click focus", function () { map.scrollWheelZoom.enable(); });
    mapEl.addEventListener("mouseleave", function () { if (!FULL) map.scrollWheelZoom.disable(); });
    [["left", false], ["right", true], ["outline", false], ["labels", false]].forEach(function (p, i) {
      map.createPane(p[0]).style.zIndex = 405 + 5 * i;
      if (!p[1]) map.getPane(p[0]).style.pointerEvents = "none";
    });
    canvas = L.canvas({ pane: "right", padding: 0.3 });
    base = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20,
      attribution: "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS user community" });
    labels = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, pane: "labels" });
    imagery = L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 19, maxZoom: 20,
      attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS user community" }).addTo(map);
    // street names help find the place, then get in the way: gone once zoomed in to the trees
    imgLabels = L.tileLayer(ESRI + "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16.25, pane: "labels" }).addTo(map);
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution("USGS 3DEP lidar, USDA NAIP, City of Tucson, Pima County GIS");

    d.sites.forEach(function (s, i) {
      var o = L.polygon(s.boundary, { pane: "outline", fill: false, color: "#fff", weight: 2 }).addTo(map);
      outlines.push(o);
    });
    buildSwipe(mapEl);
    map.fitBounds(outlines[site].getBounds().pad(0.04), { animate: false });
    map.on("move zoom zoomend resize viewreset", clip);

    var touched = false;
    mapEl.addEventListener("pointerdown", function () { touched = true; });
    mapEl.addEventListener("wheel", function () { touched = true; }, { passive: true });
    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        map.invalidateSize();
        if (!touched) map.fitBounds(outlines[site].getBounds().pad(0.04), { animate: false });
        clip();
      }).observe(mapEl);
    }
    function onClick(id, fn) { $(id).addEventListener("click", fn); }
    onClick("tb-in", function () { touched = true; map.zoomIn(); });
    onClick("tb-out", function () { touched = true; map.zoomOut(); });
    onClick("tb-full", function () { map.closePopup(); map.fitBounds(outlines[site].getBounds().pad(0.04)); });
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
  }

  function render(refit) {
    renderSettings();
    renderStats();
    renderScenTable();
    renderBars();
    renderSpecies();
    renderHabitat();
    fillSite();
    renderMap(refit);
  }
  function fail(msg) {
    var e = $("map-error");
    e.textContent = msg;
    e.hidden = false;
    setMsg("Could not load the data.");
  }

  readQuery();
  fetch(DATA + "canopy.json")
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (got) {
      d = got;
      d.sites.forEach(function (s, i) { if (s.id === readQuery.site) site = i; });
      buildSettings();
      fillStatic();
      renderAccuracy();
      buildMap();
      render();
    }).catch(function (err) {
      fail("The canopy data did not load. Reload the page to try again.");
      if (window.console) console.error(err);
    });
})();
