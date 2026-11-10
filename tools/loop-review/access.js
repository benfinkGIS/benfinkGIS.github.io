/* Closer-vs-farther page. Everything it draws comes from access.json (tools/build_access.py)
   and loop_draft.geojson (tools/build_loop.py). Draft working page, not a site page. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n) { return Math.round(n).toLocaleString("en-US"); };
  var pct = function (a, b) { return b ? (100 * a / b).toFixed(1) + "%" : "0%"; };
  var css = function (name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); };
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;       // names come from data: never innerHTML
    return e;
  }

  var BREAKS = [1, 250, 750, 1500];               // residents far away per map cell -> --seq-1..4
  var BREAK_LABELS = ["1 to 250", "250 to 750", "750 to 1,500", "1,500 or more"];
  var SPEED_MPH = 10;
  var TOP = 8;                                    // candidate segments shown at once
  var data, ti = 2, hexLayers = [], map, tiles = {}, loopLayers = [];
  var segs = null, candGroup = null, picked = null, mode = "per_mile";
  var MODES = [["per_mile", "residents per new mile"], ["residents", "most residents"]];

  // ---- tooltip: one floating box, values lead ----
  var tip = $("tip");
  function showTip(x, y, strong, lines) {
    tip.textContent = "";
    tip.appendChild(el("strong", null, strong));
    lines.forEach(function (l) { tip.appendChild(el("div", null, l)); });
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(x + 14, window.innerWidth - w - 8)) + "px";
    tip.style.top = Math.max(8, (y + 16 + h > window.innerHeight ? y - h - 12 : y + 16)) + "px";
  }
  function hideTip() { tip.hidden = true; }
  function hover(node, content) {                  // same readout on hover and on keyboard focus
    node.addEventListener("pointermove", function (e) { var c = content(); showTip(e.clientX, e.clientY, c[0], c[1]); });
    node.addEventListener("pointerleave", hideTip);
    node.addEventListener("focus", function () { var r = node.getBoundingClientRect(), c = content(); showTip(r.left + r.width / 2, r.bottom - 8, c[0], c[1]); });
    node.addEventListener("blur", hideTip);
  }

  function T() { return data.meta.thresholds[ti]; }
  function farTotal() { return data.far[String(T())]; }

  // ---- filter row ----
  function buildFilters() {
    var host = $("thresholds");
    data.meta.thresholds.forEach(function (t, i) {
      var lab = el("label"), inp = el("input");
      inp.type = "radio"; inp.name = "t"; inp.value = i; inp.checked = i === ti;
      inp.addEventListener("change", function () { ti = i; render(); });
      lab.appendChild(inp);
      lab.appendChild(el("span", null, t + " min"));
      host.appendChild(lab);
    });
    if (!segs || !segs.packages || !segs.packages.per_mile) return;
    var mhost = $("modes");
    $("mlab").hidden = mhost.hidden = false;
    MODES.forEach(function (m) {
      var lab = el("label"), inp = el("input");
      inp.type = "radio"; inp.name = "mode"; inp.value = m[0]; inp.checked = m[0] === mode;
      inp.addEventListener("change", function () { mode = m[0]; render(); });
      lab.appendChild(inp);
      lab.appendChild(el("span", null, m[1]));
      mhost.appendChild(lab);
    });
  }

  // ---- headline figures ----
  function renderLead() {
    var total = data.meta.population, far = farTotal();
    $("hero-num").textContent = fmt(far);
    $("hero-lab").textContent = "residents live more than " + T() + " minutes by bike from the Loop";
    $("share-num").textContent = pct(far, total);
    $("share-lab").textContent = "of the " + fmt(total) + " people living in the study area";
    $("dist-num").textContent = (T() / 60 * SPEED_MPH).toFixed(1) + " mi";
    $("dist-lab").textContent = "or more each way: " + T() + " minutes at " + SPEED_MPH + " mph";
  }

  // ---- tall segmented bar: the whole study area split by ride time ----
  function luminance(hex) {
    var c = hex.replace("#", "");
    var v = [0, 2, 4].map(function (i) { var s = parseInt(c.slice(i, i + 2), 16) / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  // white or near-black, whichever contrasts more with the fill (0.0533 = luminance of #0b0b0b + 0.05)
  function inkOn(hex) { var L = luminance(hex); return (1.05 / (L + 0.05)) >= ((L + 0.05) / 0.0533) ? "#ffffff" : "#0b0b0b"; }

  function buildSplit() {
    var total = data.meta.population, host = $("split"), legend = $("split-legend");
    $("split-cap").textContent = "All " + fmt(total) + " residents of the study area. Darker means a longer ride.";
    host.setAttribute("aria-label", data.bands.map(function (b) { return b.label + ": " + fmt(b.pop) + " residents, " + pct(b.pop, total); }).join("; "));
    data.bands.forEach(function (b, i) {
      var part = el("div", "part");
      part.style.flex = b.pop + " 1 0";
      part.style.background = "var(--band-" + (i + 1) + ")";
      part.tabIndex = 0;
      part.appendChild(el("span", null, pct(b.pop, total)));
      hover(part, function () { return [fmt(b.pop) + " residents", [b.label, pct(b.pop, total) + " of the study area"]]; });
      host.appendChild(part);
      var li = el("li");
      var sw = el("span", "sw"); sw.style.background = "var(--band-" + (i + 1) + ")";
      li.appendChild(sw); li.appendChild(el("span", null, b.label));
      legend.appendChild(li);
    });
  }
  function layoutSplit() {
    var parts = $("split").children, host = $("split");
    for (var i = 0; i < parts.length; i++) {
      var span = parts[i].firstChild;
      span.style.color = inkOn(css("--band-" + (i + 1)));
      span.style.visibility = "visible";
      if (span.offsetWidth > parts[i].clientWidth) span.style.visibility = "hidden";   // no room: the tooltip and table carry it
    }
    var first = data.bands.findIndex(function (b) { return b.lo >= T(); });
    var bracket = $("bracket");
    bracket.querySelector("i").style.width = (host.offsetLeft + host.clientWidth - parts[first].offsetLeft) + "px";
    var b = bracket.querySelector("b");
    b.textContent = "";
    b.appendChild(el("strong", null, fmt(farTotal())));
    b.appendChild(document.createTextNode(" residents (" + pct(farTotal(), data.meta.population) + ") are more than " + T() + " min away"));
  }

  // ---- map: hexagons coloured by residents far from the Loop ----
  function cellClass(far) {
    if (far <= 0) return 0;
    for (var k = BREAKS.length - 1; k >= 0; k--) if (far >= BREAKS[k]) return k + 1;
    return 1;
  }
  function cellStyle(h) {
    var k = cellClass(h.far[ti]);
    return { color: css("--surface"), weight: 1, opacity: 0.9,
             fillColor: k ? css("--seq-" + k) : css("--near"), fillOpacity: k ? 0.86 : 0.5 };
  }
  function dark() { return css("color-scheme") === "dark" || getComputedStyle(document.body).colorScheme === "dark"; }
  function setBasemap() {
    var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
    var name = dark() ? "World_Dark_Gray" : "World_Light_Gray";
    if (tiles.name === name) return;
    if (tiles.base) { map.removeLayer(tiles.base); map.removeLayer(tiles.ref); }
    tiles.name = name;
    tiles.base = L.tileLayer(ESRI + name + "_Base/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 17,
      attribution: "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS user community" }).addTo(map);
    tiles.ref = L.tileLayer(ESRI + name + "_Reference/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 17, pane: "labels" }).addTo(map);
  }
  function buildMap(loop) {
    map = L.map("map", { minZoom: 9, maxZoom: 17, zoomSnap: 0.25, scrollWheelZoom: false });
    map.on("click focus", function () { map.scrollWheelZoom.enable(); });
    $("map").addEventListener("mouseleave", function () { map.scrollWheelZoom.disable(); hideTip(); });
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution('Loop &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors; residents: U.S. Census Bureau');
    L.control.scale({ imperial: true, metric: false }).addTo(map);
    ["loop", "labels"].forEach(function (p, i) {      // the Loop and place names sit above the cells and ignore the pointer
      map.createPane(p).style.zIndex = 450 + 10 * i;
      map.getPane(p).style.pointerEvents = "none";
    });
    map.createPane("cands").style.zIndex = 455;       // candidate segments: above the Loop, and they do take the pointer
    candGroup = L.layerGroup().addTo(map);
    setBasemap();
    var group = L.featureGroup();
    data.hexes.forEach(function (h) {
      var layer = L.polygon(h.ring.map(function (c) { return [c[1], c[0]]; }), Object.assign({ className: "hex" }, cellStyle(h)));
      layer.on("mousemove", function (e) {
        var far = h.far[ti];
        showTip(e.originalEvent.clientX, e.originalEvent.clientY,
          far ? fmt(far) + " residents more than " + T() + " min away" : "Everyone within " + T() + " min",
          [fmt(h.pop) + " residents in this cell", "Average ride to the Loop: " + h.min.toFixed(0) + " min"]);
      });
      layer.on("mouseover", function () { layer.setStyle({ color: css("--ink"), weight: 2, opacity: 1 }); layer.bringToFront(); });
      layer.on("mouseout", function () { layer.setStyle(cellStyle(h)); hideTip(); });
      hexLayers.push([layer, h]);
      group.addLayer(layer);
    });
    group.addTo(map);
    loopLayers = [
      L.geoJSON(loop, { pane: "loop", interactive: false, style: { color: css("--loop-casing"), weight: 5, opacity: 0.95 } }).addTo(map),
      L.geoJSON(loop, { pane: "loop", interactive: false, style: { color: css("--loop"), weight: 2.25, opacity: 1 } }).addTo(map)
    ];
    map.fitBounds(group.getBounds(), { padding: [10, 10] });
  }
  function renderMap() {
    $("map-cap").textContent = "Each cell is coloured by how many of its residents are more than " + T() +
      " minutes from the Loop. Grey cells have residents, all of them within " + T() + " minutes.";
    if (!map) return;
    setBasemap();
    hexLayers.forEach(function (p) { p[0].setStyle(cellStyle(p[1])); });
    loopLayers[0].setStyle({ color: css("--loop-casing") });
    loopLayers[1].setStyle({ color: css("--loop") });
    var legend = $("map-legend");
    legend.textContent = "";
    function item(swatch, text) { var li = el("li"); li.appendChild(swatch); li.appendChild(el("span", null, text)); legend.appendChild(li); }
    var line = el("span", "line"); item(line, "The Loop (draft, " + data.meta.loop_miles + " mi)");
    if (segs) item(el("span", "dash"), "Candidate segment (those ranked below)");
    var near = el("span", "sw"); near.style.background = "var(--near)"; item(near, "Everyone within " + T() + " min");
    BREAK_LABELS.forEach(function (lab, k) {
      var sw = el("span", "sw"); sw.style.background = "var(--seq-" + (k + 1) + ")";
      item(sw, lab + (k === 0 ? " residents farther" : ""));
    });
  }

  // ---- ranked bars: communities by residents far away ----
  function renderRank() {
    var key = String(T()), host = $("rank");
    $("rank-cap").textContent = "Residents more than " + T() + " minutes away, by city, town or census-named community. " +
      "The percentage is the share of that community's own residents.";
    var rows = data.places.filter(function (p) { return p.far[key] > 0; })
      .sort(function (a, b) { return b.far[key] - a.far[key]; }).slice(0, 10);
    var max = rows.length ? rows[0].far[key] : 1;
    host.textContent = "";
    rows.forEach(function (p) {
      host.appendChild(el("div", "name", p.name));
      var track = el("div", "track"), bar = el("div", "bar"), val = el("div", "val");
      bar.style.width = (62 * p.far[key] / max) + "%";
      val.appendChild(document.createTextNode(fmt(p.far[key]) + " "));
      val.appendChild(el("small", null, pct(p.far[key], p.pop)));
      track.tabIndex = 0;
      track.setAttribute("aria-label", p.name + ": " + fmt(p.far[key]) + " residents more than " + T() + " minutes away, " + pct(p.far[key], p.pop) + " of its " + fmt(p.pop) + " residents");
      track.appendChild(bar); track.appendChild(val);
      hover(track, function () { return [fmt(p.far[key]) + " residents", [p.name, pct(p.far[key], p.pop) + " of its " + fmt(p.pop) + " residents", "more than " + T() + " min from the Loop"]]; });
      host.appendChild(track);
    });
  }

  // ---- candidate new segments (tools/test_segments.py) ----
  function kindText(c) {
    return c.kind === "wash" ? "new path along a wash" : c.kind === "existing path" ? "existing path, not part of the Loop" : "custom line";
  }
  function candLatLngs(c) { return c.lines.map(function (ln) { return ln.map(function (p) { return [p[1], p[0]]; }); }); }
  function drawCands(rows) {
    if (!map) return;
    var key = String(T());
    candGroup.clearLayers();
    rows.forEach(function (c) {
      var ll = candLatLngs(c), sel = picked === c;
      L.polyline(ll, { pane: "cands", interactive: false, color: css("--loop-casing"), weight: sel ? 9 : 6, opacity: 0.9 }).addTo(candGroup);
      L.polyline(ll, { pane: "cands", interactive: false, color: css("--cand"), weight: sel ? 5 : 3, dashArray: sel ? null : "7 6" }).addTo(candGroup);
      var hit = L.polyline(ll, { pane: "cands", weight: 20, opacity: 0 }).addTo(candGroup);   // wide invisible target
      hit.on("mousemove", function (e) {
        showTip(e.originalEvent.clientX, e.originalEvent.clientY, fmt(c.gained[key]) + " residents brought within " + T() + " min",
          [c.name, c.miles.toFixed(1) + " mi, " + kindText(c)]);
      });
      hit.on("mouseout", hideTip);
      hit.on("click", function () { picked = sel ? null : c; renderSegments(); });
    });
  }
  function topRows() {
    var key = String(T());
    return segs.candidates.filter(function (c) { return c.gained[key] > 0; })
      .sort(function (a, b) { return b.gained[key] - a.gained[key]; }).slice(0, TOP);
  }
  function packSteps() { return (segs.packages && segs.packages[mode] && segs.packages[mode][String(T())]) || []; }
  function shownCands() {                          // on the map: the top singles plus everything in the build-out
    var rows = topRows();
    packSteps().forEach(function (st) { var c = segs.candidates[st.i]; if (rows.indexOf(c) < 0) rows.push(c); });
    return rows;
  }
  function pickButton(c) {
    var btn = el("button", "pick");
    btn.type = "button";
    btn.setAttribute("aria-pressed", picked === c ? "true" : "false");
    btn.appendChild(document.createTextNode(c.name));
    btn.appendChild(el("small", null, c.miles.toFixed(1) + " mi · " + kindText(c)));
    btn.addEventListener("click", function () {
      picked = picked === c ? null : c;
      renderSegments();
      if (picked && map) {
        map.fitBounds(L.latLngBounds([].concat.apply([], candLatLngs(c))), { padding: [50, 50], maxZoom: 14 });
        $("map").scrollIntoView({ block: "center" });
      }
    });
    return btn;
  }
  function renderSegments() {
    if (!segs) return;
    var shown = shownCands();
    if (picked && shown.indexOf(picked) < 0) picked = null;
    renderCands();
    renderPackage();
    drawCands(shown);
  }
  function renderCands() {
    var key = String(T()), host = $("cands"), m = segs.meta;
    var rows = topRows();
    $("cand-card").hidden = false;
    $("cand-cap").textContent = "The " + TOP + " corridors that would bring the most residents within " + T() +
      " minutes if a path there counted as Loop, out of " + m.candidates_tested + " named washes and existing paved paths screened. " +
      "Candidates overlap, so their numbers do not add up. Pick one to see it on the map.";
    var tg = segs.top_together && segs.top_together[key];
    $("cand-together").textContent = !tg ? "" : "Built together, these " + tg.segments + " would bring " + fmt(tg.total) + " residents within " + T() +
      " minutes, not the " + fmt(tg.sum_of_singles) + " their separate numbers add up to, because many of them serve the same people.";
    host.textContent = "";
    var max = rows.length ? rows[0].gained[key] : 1;
    rows.forEach(function (c) {
      host.appendChild(pickButton(c));
      var track = el("div", "track"), bar = el("div", "bar"), val = el("div", "val");
      bar.style.width = (62 * c.gained[key] / max) + "%";
      val.appendChild(document.createTextNode(fmt(c.gained[key]) + " "));
      val.appendChild(el("small", null, fmt(c.gained_per_mile[key]) + " per mile"));
      track.tabIndex = 0;
      track.setAttribute("aria-label", c.name + ": " + fmt(c.gained[key]) + " residents brought within " + T() + " minutes, " + c.miles.toFixed(1) + " miles");
      track.appendChild(bar); track.appendChild(val);
      hover(track, function () { return [fmt(c.gained[key]) + " residents", [c.name, "brought within " + T() + " min of the Loop", c.miles.toFixed(1) + " mi, " + fmt(c.gained_per_mile[key]) + " residents per mile"]]; });
      host.appendChild(track);
    });
  }

  // ---- built together: candidates added one at a time, overlap counted once ----
  function renderPackage() {
    var steps = packSteps(), card = $("pack-card");
    card.hidden = !steps.length;
    if (!steps.length) return;
    var last = steps[steps.length - 1], far = farTotal(), host = $("pack");
    var existing = steps.filter(function (s) { return s.per_new_mile == null; }).length;
    $("pack-cap").textContent = "Candidates added one at a time, each time taking the one that helps the most residents not already helped" +
      (mode === "per_mile" ? " for each mile of new path" : "") + ", so nobody is counted twice. " +
      (mode === "per_mile" ? "A path that already exists needs no new path, so it goes first. " : "") +
      steps.length + " segments: " + last.new_miles_total + " miles of new path" +
      (existing ? " plus " + existing + " existing path" + (existing > 1 ? "s" : "") : "") + ".";
    $("pack-num").textContent = fmt(last.total);
    $("pack-lab").textContent = "residents would come within " + T() + " minutes of the Loop";
    var meter = $("pack-meter");
    meter.firstChild.style.width = Math.min(100, 100 * last.total / far) + "%";
    meter.setAttribute("aria-label", pct(last.total, far) + " of the residents now farther than " + T() + " minutes");
    $("pack-meter-lab").textContent = pct(last.total, far) + " of the " + fmt(far) + " residents now farther than " + T() +
      " minutes. " + fmt(far - last.total) + " would still be.";
    host.textContent = "";
    var max = Math.max.apply(null, steps.map(function (s) { return s.added; }));
    steps.forEach(function (st, k) {
      var c = segs.candidates[st.i];
      host.appendChild(pickButton(c));
      var track = el("div", "track"), bar = el("div", "bar"), val = el("div", "val");
      bar.style.width = (62 * st.added / max) + "%";
      val.appendChild(document.createTextNode("+" + fmt(st.added) + " "));
      var rate = st.per_new_mile == null ? "no new path needed" : fmt(st.per_new_mile) + " per new mile";
      val.appendChild(el("small", null, rate + " · running total " + fmt(st.total)));
      track.tabIndex = 0;
      track.setAttribute("aria-label", "Step " + (k + 1) + ", " + c.name + ": adds " + fmt(st.added) + " residents, " + rate + ", running total " + fmt(st.total) + ", " + st.new_miles_total + " miles of new path so far");
      track.appendChild(bar); track.appendChild(val);
      hover(track, function () { return ["+" + fmt(st.added) + " residents", ["Step " + (k + 1) + ": " + c.name, rate, "running total " + fmt(st.total), st.new_miles_total + " mi of new path so far"]]; });
      host.appendChild(track);
    });
    var t = $("t-pack");
    t.textContent = "";
    var head = t.appendChild(el("thead")).appendChild(el("tr"));
    ["Step", "Segment", "Adds", "Per new mile", "Running total", "New miles so far"].forEach(function (h, i) { head.appendChild(el("th", i > 1 ? "n" : null, h)).scope = "col"; });
    var body = t.appendChild(el("tbody"));
    steps.forEach(function (st, k) {
      var tr = body.appendChild(el("tr"));
      [String(k + 1), segs.candidates[st.i].name, fmt(st.added), st.per_new_mile == null ? "existing" : fmt(st.per_new_mile), fmt(st.total), String(st.new_miles_total)]
        .forEach(function (v, i) { tr.appendChild(el("td", i > 1 ? "n" : null, v)); });
    });
  }

  // ---- table view: every number on the page, without hovering ----
  function buildTables() {
    var total = data.meta.population;
    function table(host, caption, head, rows) {
      host.appendChild(el("caption", null, caption)).style.cssText = "text-align:left;font-weight:600;padding:8px 0 4px";
      var tr = host.appendChild(el("thead")).appendChild(el("tr"));
      head.forEach(function (h, i) { tr.appendChild(el("th", i ? "n" : null, h)).scope = "col"; });
      var body = host.appendChild(el("tbody"));
      rows.forEach(function (r) {
        var row = body.appendChild(el("tr"));
        r.forEach(function (c, i) { row.appendChild(el(i ? "td" : "th", i ? "n" : null, c)).scope = i ? "" : "row"; });
      });
    }
    table($("t-bands"), "Residents by ride time to the Loop", ["Ride time", "Residents", "Share"],
      data.bands.map(function (b) { return [b.label, fmt(b.pop), pct(b.pop, total)]; }));
    table($("t-places"), "Residents farther than each limit, by community",
      ["Community", "Residents"].concat(data.meta.thresholds.map(function (t) { return "Over " + t + " min"; })),
      data.places.map(function (p) { return [p.name, fmt(p.pop)].concat(data.meta.thresholds.map(function (t) { return fmt(p.far[String(t)]); })); }));
    if (segs) table($("t-cands"), "Residents each candidate would bring within each limit",
      ["Candidate", "Type", "Miles", "Reaches the Loop"].concat(segs.meta.thresholds.map(function (t) { return "Within " + t + " min"; })),
      segs.candidates.map(function (c) {
        return [c.name, kindText(c), c.miles.toFixed(1), c.connects_to_loop ? "yes" : "no"].concat(segs.meta.thresholds.map(function (t) { return fmt(c.gained[String(t)]); }));
      }));
  }

  function buildNotes() {
    var o = data.meta.outside_study_area, b = data.meta.study_bbox_south_west_north_east, host = $("notes");
    [["Ride time", "the shortest legal route from home to the nearest point on the Loop, over streets and paths from OpenStreetMap, at " + SPEED_MPH +
        " mph. Nothing is added for traffic: a mile on a fast arterial counts the same as a mile on a quiet street. Most people would not ride every one of these routes, so the true reach is smaller than shown."],
     ["Residents", "2020 Census counts by block. Each block's people are placed at the block's centre point, which is rough for the large blocks at the desert edge."],
     ["The Loop", "a draft extent of " + data.meta.loop_miles + " miles assembled from OpenStreetMap. It has not been checked section by section."],
     ["Study area", "latitude " + b[0] + " to " + b[2] + ", longitude " + b[1] + " to " + b[3] + ". Another " + fmt(o.population) +
        " Pima County residents live outside it (Green Valley, Sahuarita, Ajo and other places). The closest of them is " + o.nearest_straight_line_miles +
        " miles from the Loop in a straight line, and " + fmt(o.population_within_5_straight_line_miles) + " are within 5 straight-line miles. They are not in any figure above."],
     ["Communities", "2020 Census cities, towns and census-designated places. “Tucson” means inside the city limits."],
     ["Map cells", "hexagons " + data.meta.hex_radius_m + " m from centre to corner, about 0.6 square miles each."]
    ].concat(segs ? [["Candidate segments", "every named wash in OpenStreetMap (leaving out the parts within " + segs.meta.loop_near_m +
        " m of the Loop) and every existing paved bike path of " + segs.meta.min_path_miles + " miles or more that is not part of the Loop was scored as if it were Loop. " +
        "An existing path is entered at its real junctions. A path that does not exist yet is assumed reachable from any public street or path within " + segs.meta.access_m +
        " m, which is generous, and nobody has checked that a path would fit or who owns the land. Use the ranking to decide where to look, not as a list of proposals."]] : []).concat([
     ["Sources", "streets and paths © OpenStreetMap contributors; population and place boundaries from the U.S. Census Bureau; basemap by Esri. Data built " + data.meta.generated + "."]
    ]).forEach(function (n) {
      var li = el("li");
      li.appendChild(el("strong", null, n[0] + ": "));
      li.appendChild(document.createTextNode(n[1]));
      host.appendChild(li);
    });
  }

  function render() { renderLead(); layoutSplit(); renderMap(); renderRank(); renderSegments(); }

  function getJSON(name) {
    return fetch(name).then(function (r) { if (!r.ok) throw new Error(name + ": HTTP " + r.status); return r.json(); });
  }
  Promise.all([getJSON("access.json"), getJSON("loop_draft.geojson"),
               getJSON("segments.json").catch(function () { return null; })]).then(function (res) {
    data = res[0];
    segs = res[2];
    ti = Math.max(0, data.meta.thresholds.indexOf(20));
    buildFilters(); buildSplit(); buildTables(); buildNotes();
    if (typeof L !== "undefined") buildMap(res[1]);
    render();
    window.addEventListener("resize", layoutSplit);
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
  }).catch(function (e) {
    var box = $("err");
    box.textContent = "Could not load the data (" + e.message + "). Run: py tools/build_access.py";
    box.hidden = false;
  });
})();
