/* Tucson Loop Access: charts and map for both project pages.
   /tucson-loop-access/        who lives far from the Loop
   /tucson-loop-access/grow/   where the Loop could grow
   Each part below draws only if its element is on the page. Data comes from data/*.json,
   put there by tools/publish_loop_access.py. Leaflet 1.9.4 is loaded by the page. */
(function () {
  "use strict";
  var DATA = "/tucson-loop-access/data/";
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n) { return Math.round(n).toLocaleString("en-US"); };
  var pct = function (a, b) { return b ? (100 * a / b).toFixed(1) + "%" : "0%"; };
  var css = function (name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); };
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;          // names come from data: never innerHTML
    return e;
  }

  var BREAKS = [1, 250, 750, 1500];                  // residents far away per map cell -> --seq-1..4
  var BREAK_LABELS = ["1 to 250", "250 to 750", "750 to 1,500", "1,500 or more"];
  var SPEED_MPH = 10, TOP = 8;
  var MODES = [["per_mile", "Residents per new mile"], ["residents", "Most residents"]];
  var data, segs = null, loop = null;
  var ti = 2, mode = "per_mile", picked = null;
  var map, labels, hexLayers = [], candGroup = null, fullBounds = null;
  var growPage = !!$("cands");                       // the second page shows candidate segments

  // ---- tooltip: one pale-yellow box; the same readout on hover and on keyboard focus ----
  var tip = $("tip");
  function showTip(x, y, strong, lines) {
    if (!tip) return;
    tip.textContent = "";
    tip.appendChild(el("strong", null, strong));
    lines.forEach(function (l) { tip.appendChild(el("div", null, l)); });
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(6, Math.min(x + 14, window.innerWidth - w - 6)) + "px";
    tip.style.top = Math.max(6, (y + 18 + h > window.innerHeight ? y - h - 10 : y + 18)) + "px";
  }
  function hideTip() { if (tip) tip.hidden = true; }
  function hover(node, content) {
    node.addEventListener("pointermove", function (e) { var c = content(); showTip(e.clientX, e.clientY, c[0], c[1]); });
    node.addEventListener("pointerleave", hideTip);
    node.addEventListener("focus", function () { var r = node.getBoundingClientRect(), c = content(); showTip(r.left + r.width / 2, r.bottom - 8, c[0], c[1]); });
    node.addEventListener("blur", hideTip);
  }
  function setMsg(t) { var m = $("sb-msg"); if (m) m.textContent = t; }

  function T() { return data.meta.thresholds[ti]; }
  function farTotal() { return data.far[String(T())]; }

  // ---- settings: toolbar-style buttons; the choice rides along in the address ----
  function readQuery() {
    var q = new URLSearchParams(location.search), far = +q.get("far"), i = data.meta.thresholds.indexOf(far);
    ti = i >= 0 ? i : Math.max(0, data.meta.thresholds.indexOf(20));
    if (q.get("pick") === "residents") mode = "residents";
  }
  function writeQuery() {
    var q = "?far=" + T() + (mode === "residents" ? "&pick=residents" : "");
    history.replaceState(null, "", location.pathname + q);
    document.querySelectorAll("a[data-carry]").forEach(function (a) { a.href = a.getAttribute("data-carry") + q; });
  }
  function buttons(host, items, isOn, choose) {
    if (!host) return;
    if (host.children.length !== items.length) {     // built once, so a pressed button keeps keyboard focus
      host.textContent = "";
      items.forEach(function (it) {
        var b = el("button", null, it[1]);
        b.type = "button";
        b.addEventListener("click", function () { choose(it[0]); render(); });
        host.appendChild(b);
      });
    }
    items.forEach(function (it, k) { host.children[k].setAttribute("aria-pressed", isOn(it[0]) ? "true" : "false"); });
  }
  function renderSettings() {
    buttons($("far-buttons"), data.meta.thresholds.map(function (t, i) { return [i, t + " min"]; }),
      function (i) { return i === ti; }, function (i) { ti = i; });
    if (segs && segs.packages && segs.packages.per_mile) {
      buttons($("mode-buttons"), MODES, function (m) { return m === mode; }, function (m) { mode = m; });
    }
    writeQuery();
  }

  // ---- headline figures ----
  function renderLead() {
    if (!$("hero-num")) return;
    var total = data.meta.population, far = farTotal();
    $("hero-num").textContent = fmt(far);
    $("hero-lab").textContent = "residents live more than " + T() + " minutes by bike from the Loop";
    $("share-num").textContent = pct(far, total);
    $("share-lab").textContent = "of the " + fmt(total) + " people in the study area";
    $("dist-num").textContent = (T() / 60 * SPEED_MPH).toFixed(1) + " mi";
    $("dist-lab").textContent = "or more each way: " + T() + " minutes at " + SPEED_MPH + " mph";
  }

  // ---- split bar: the whole study area by ride time ----
  function luminance(hex) {
    var c = hex.replace("#", "");
    var v = [0, 2, 4].map(function (i) { var s = parseInt(c.slice(i, i + 2), 16) / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  // white or black, whichever contrasts more with the fill
  function inkOn(hex) { var L = luminance(hex); return (1.05 / (L + 0.05)) >= ((L + 0.05) / 0.05) ? "#ffffff" : "#000000"; }
  function buildSplit() {
    var host = $("split");
    if (!host) return;
    var total = data.meta.population, legend = $("split-legend");
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
      var li = el("li"), sw = el("span", "sw");
      sw.style.background = "var(--band-" + (i + 1) + ")";
      li.appendChild(sw); li.appendChild(el("span", null, b.label));
      legend.appendChild(li);
    });
  }
  function layoutSplit() {
    var host = $("split");
    if (!host) return;
    var parts = host.children;
    for (var i = 0; i < parts.length; i++) {
      var span = parts[i].firstChild;
      span.style.color = inkOn(css("--band-" + (i + 1)));
      span.style.visibility = "visible";
      if (span.offsetWidth > parts[i].clientWidth) span.style.visibility = "hidden";   // no room: the tooltip and table carry it
    }
    var first = data.bands.findIndex(function (b) { return b.lo >= T(); });
    var bracket = $("bracket"), b = bracket.querySelector("b");
    bracket.querySelector("i").style.width = (host.offsetLeft + host.clientWidth - parts[first].offsetLeft) + "px";
    b.textContent = "";
    b.appendChild(el("strong", null, fmt(farTotal())));
    b.appendChild(document.createTextNode(" residents (" + pct(farTotal(), data.meta.population) + ") are more than " + T() + " min away"));
  }

  // ---- map ----
  function cellClass(far) {
    if (far <= 0) return 0;
    for (var k = BREAKS.length - 1; k >= 0; k--) if (far >= BREAKS[k]) return k + 1;
    return 1;
  }
  function cellStyle(h) {
    var k = cellClass(h.far[ti]);
    return { color: "#ffffff", weight: 1, opacity: 0.9, fillColor: k ? css("--seq-" + k) : css("--near"), fillOpacity: k ? 0.88 : 0.55 };
  }
  function buildMap() {
    var mapEl = $("map");
    if (!mapEl || typeof L === "undefined") return;
    var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
    map = L.map(mapEl, { zoomControl: false, minZoom: 9, maxZoom: 17, zoomSnap: 0.25, scrollWheelZoom: false });
    map.on("click focus", function () { map.scrollWheelZoom.enable(); });
    mapEl.addEventListener("mouseleave", function () { map.scrollWheelZoom.disable(); hideTip(); });
    ["loop", "cands", "labels"].forEach(function (p, i) { map.createPane(p).style.zIndex = 450 + 5 * i; });
    map.getPane("loop").style.pointerEvents = map.getPane("labels").style.pointerEvents = "none";
    L.tileLayer(ESRI + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 17,
      attribution: "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS user community" }).addTo(map);
    labels = L.tileLayer(ESRI + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 17, pane: "labels" }).addTo(map);
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution('Paths &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors; residents: U.S. Census Bureau');
    L.control.scale({ imperial: true, metric: false }).addTo(map);

    var group = L.featureGroup();
    data.hexes.forEach(function (h) {
      var layer = L.polygon(h.ring.map(function (c) { return [c[1], c[0]]; }), Object.assign({ className: "hex" }, cellStyle(h)));
      layer.on("mousemove", function (e) {
        var far = h.far[ti];
        showTip(e.originalEvent.clientX, e.originalEvent.clientY,
          far ? fmt(far) + " residents more than " + T() + " min away" : "Everyone within " + T() + " min",
          [fmt(h.pop) + " residents in this cell", "Average ride to the Loop: " + h.min.toFixed(0) + " min"]);
      });
      layer.on("mouseover", function () { layer.setStyle({ color: "#000000", weight: 2, opacity: 1 }); layer.bringToFront(); });
      layer.on("mouseout", function () { layer.setStyle(cellStyle(h)); hideTip(); });
      hexLayers.push([layer, h]);
      group.addLayer(layer);
    });
    group.addTo(map);
    var lines = loop.lines.map(function (ln) { return ln.map(function (c) { return [c[1], c[0]]; }); });
    L.polyline(lines, { pane: "loop", interactive: false, color: "#ffffff", weight: 5, opacity: 0.95 }).addTo(map);
    L.polyline(lines, { pane: "loop", interactive: false, color: css("--loopline"), weight: 2.25 }).addTo(map);
    candGroup = L.layerGroup().addTo(map);
    fullBounds = group.getBounds();
    map.fitBounds(fullBounds, { padding: [10, 10] });

    // the viewer's own toolbar and status bar
    function on(id, fn) { var b = $(id); if (b) b.addEventListener("click", fn); }
    on("tb-in", function () { map.zoomIn(); });
    on("tb-out", function () { map.zoomOut(); });
    on("tb-full", function () { picked = null; renderSegments(); map.fitBounds(fullBounds, { padding: [10, 10] }); });
    var lb = $("tb-labels");
    if (lb) lb.addEventListener("click", function () {
      var show = lb.getAttribute("aria-pressed") !== "true";
      lb.setAttribute("aria-pressed", show ? "true" : "false");
      if (show) labels.addTo(map); else map.removeLayer(labels);
    });
    var pos = $("sb-pos");
    function coord(ll) { return Math.abs(ll.lat).toFixed(4) + "° N, " + Math.abs(ll.lng).toFixed(4) + "° W"; }
    if (pos) {
      map.on("mousemove", function (e) { pos.textContent = coord(e.latlng); });
      map.on("mouseout", function () { pos.textContent = coord(map.getCenter()); });
      pos.textContent = coord(map.getCenter());
    }
  }
  function renderMap() {
    var cap = $("map-cap");
    if (cap) cap.textContent = "Each cell is coloured by how many of its residents are more than " + T() +
      " minutes from the Loop. Grey cells have residents, all of them within " + T() + " minutes.";
    hexLayers.forEach(function (p) { p[0].setStyle(cellStyle(p[1])); });
    var legend = $("map-legend");
    if (!legend) return;
    legend.textContent = "";
    function item(swatch, text) { var li = el("li"); li.appendChild(swatch); li.appendChild(el("span", null, text)); legend.appendChild(li); }
    item(el("span", "line"), "The Loop (draft, " + loop.miles + " mi)");
    if (growPage && segs) item(el("span", "dash"), "Candidate segment (those listed below)");
    var near = el("span", "sw"); near.style.background = "var(--near)"; item(near, "Everyone within " + T() + " min");
    BREAK_LABELS.forEach(function (lab, k) {
      var sw = el("span", "sw"); sw.style.background = "var(--seq-" + (k + 1) + ")";
      item(sw, lab + (k === 0 ? " residents farther" : ""));
    });
  }

  // ---- ranked bars: communities by residents far away ----
  function renderRank() {
    var host = $("rank");
    if (!host) return;
    var key = String(T());
    $("rank-cap").textContent = "Residents more than " + T() + " minutes away, by city, town or census-named community. " +
      "The percentage is the share of that community's own residents.";
    var rows = data.places.filter(function (p) { return p.far[key] > 0; })
      .sort(function (a, b) { return b.far[key] - a.far[key]; }).slice(0, 10);
    var max = rows.length ? rows[0].far[key] : 1;
    host.textContent = "";
    rows.forEach(function (p) {
      host.appendChild(el("div", "name", p.name));
      var track = el("div", "track"), bar = el("div", "bar"), val = el("div", "val");
      bar.style.width = (58 * p.far[key] / max) + "%";
      val.appendChild(document.createTextNode(fmt(p.far[key]) + " "));
      val.appendChild(el("small", null, pct(p.far[key], p.pop)));
      track.tabIndex = 0;
      track.setAttribute("aria-label", p.name + ": " + fmt(p.far[key]) + " residents more than " + T() + " minutes away, " + pct(p.far[key], p.pop) + " of its " + fmt(p.pop) + " residents");
      track.appendChild(bar); track.appendChild(val);
      hover(track, function () { return [fmt(p.far[key]) + " residents", [p.name, pct(p.far[key], p.pop) + " of its " + fmt(p.pop) + " residents", "more than " + T() + " min from the Loop"]]; });
      host.appendChild(track);
    });
  }

  // ---- candidate new segments ----
  function kindText(c) {
    return c.kind === "wash" ? "new path along a wash" : c.kind === "existing path" ? "existing path, not part of the Loop" : "custom line";
  }
  function candLatLngs(c) { return c.lines.map(function (ln) { return ln.map(function (p) { return [p[1], p[0]]; }); }); }
  function topRows() {
    var key = String(T());
    return segs.candidates.filter(function (c) { return c.gained[key] > 0; })
      .sort(function (a, b) { return b.gained[key] - a.gained[key]; }).slice(0, TOP);
  }
  function packSteps() { return (segs.packages && segs.packages[mode] && segs.packages[mode][String(T())]) || []; }
  function shownCands() {                            // on the map: the top singles plus everything in the build-out
    var rows = topRows();
    packSteps().forEach(function (st) { var c = segs.candidates[st.i]; if (rows.indexOf(c) < 0) rows.push(c); });
    return rows;
  }
  function drawCands(rows) {
    if (!map) return;
    var key = String(T());
    candGroup.clearLayers();
    rows.forEach(function (c) {
      var ll = candLatLngs(c), sel = picked === c;
      L.polyline(ll, { pane: "cands", interactive: false, color: "#ffffff", weight: sel ? 9 : 6, opacity: 0.9 }).addTo(candGroup);
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
  function pickButton(c) {
    var btn = el("button", "pick");
    btn.type = "button";
    btn.setAttribute("aria-pressed", picked === c ? "true" : "false");
    btn.appendChild(el("span", "nm", c.name));
    btn.appendChild(el("small", null, c.miles.toFixed(1) + " mi · " + kindText(c)));
    btn.addEventListener("click", function () {
      picked = picked === c ? null : c;
      renderSegments();
      if (picked && map) {
        map.fitBounds(L.latLngBounds([].concat.apply([], candLatLngs(c))), { padding: [50, 50], maxZoom: 14 });
        $("map").scrollIntoView({ block: "center" });
        setMsg(c.name);
      }
    });
    return btn;
  }
  function renderSegments() {
    if (!growPage || !segs) return;
    var shown = shownCands();
    if (picked && shown.indexOf(picked) < 0) picked = null;
    renderCands();
    renderPackage();
    drawCands(shown);
    if (!picked) setMsg("Ready");
  }
  function renderCands() {
    var key = String(T()), host = $("cands"), rows = topRows();
    $("cand-cap").textContent = "The " + TOP + " corridors that would bring the most residents within " + T() +
      " minutes if a path there counted as Loop. Pick one to see it on the map.";
    var tg = segs.top_together && segs.top_together[key];
    $("cand-together").textContent = !tg ? "" : "Built together, these " + tg.segments + " would bring " + fmt(tg.total) + " residents within " + T() +
      " minutes, not the " + fmt(tg.sum_of_singles) + " their separate numbers add up to, because many of them serve the same people.";
    host.textContent = "";
    var max = rows.length ? rows[0].gained[key] : 1;
    rows.forEach(function (c) {
      host.appendChild(pickButton(c));
      var track = el("div", "track"), bar = el("div", "bar"), val = el("div", "val");
      bar.style.width = (58 * c.gained[key] / max) + "%";
      val.appendChild(document.createTextNode(fmt(c.gained[key]) + " "));
      val.appendChild(el("small", null, fmt(c.gained_per_mile[key]) + " per mile"));
      track.tabIndex = 0;
      track.setAttribute("aria-label", c.name + ": " + fmt(c.gained[key]) + " residents brought within " + T() + " minutes, " + c.miles.toFixed(1) + " miles");
      track.appendChild(bar); track.appendChild(val);
      hover(track, function () { return [fmt(c.gained[key]) + " residents", [c.name, "brought within " + T() + " min of the Loop", c.miles.toFixed(1) + " mi, " + fmt(c.gained_per_mile[key]) + " residents per mile"]]; });
      host.appendChild(track);
    });
  }
  function renderPackage() {
    var steps = packSteps(), box = $("pack-box");
    box.hidden = !steps.length;
    if (!steps.length) return;
    var last = steps[steps.length - 1], far = farTotal(), host = $("pack");
    var existing = steps.filter(function (s) { return s.per_new_mile == null; }).length;
    $("pack-cap").textContent = "Segments added one at a time, each time taking the one that helps the most residents not already helped" +
      (mode === "per_mile" ? " for each mile of new path" : "") + ", so nobody is counted twice. " +
      (mode === "per_mile" ? "A path that already exists needs no new path, so it goes first. " : "") +
      steps.length + " segments: " + last.new_miles_total + " miles of new path" +
      (existing ? " plus " + existing + " existing path" + (existing > 1 ? "s" : "") : "") + ".";
    $("pack-num").textContent = fmt(last.total);
    $("pack-lab").textContent = "residents would come within " + T() + " minutes of the Loop";
    var bar = $("pack-progress");
    bar.firstChild.style.width = Math.min(100, 100 * last.total / far) + "%";
    bar.setAttribute("aria-label", pct(last.total, far) + " of the residents now farther than " + T() + " minutes");
    $("pack-progress-lab").textContent = pct(last.total, far) + " of the " + fmt(far) + " residents now farther than " + T() +
      " minutes. " + fmt(far - last.total) + " would still be.";
    host.textContent = "";
    var max = Math.max.apply(null, steps.map(function (s) { return s.added; }));
    steps.forEach(function (st, k) {
      var c = segs.candidates[st.i];
      host.appendChild(pickButton(c));
      var track = el("div", "track"), b = el("div", "bar"), val = el("div", "val");
      var rate = st.per_new_mile == null ? "no new path needed" : fmt(st.per_new_mile) + " per new mile";
      b.style.width = (58 * st.added / max) + "%";
      val.appendChild(document.createTextNode("+" + fmt(st.added) + " "));
      val.appendChild(el("small", null, rate + " · total " + fmt(st.total)));
      track.tabIndex = 0;
      track.setAttribute("aria-label", "Step " + (k + 1) + ", " + c.name + ": adds " + fmt(st.added) + " residents, " + rate + ", running total " + fmt(st.total) + ", " + st.new_miles_total + " miles of new path so far");
      track.appendChild(b); track.appendChild(val);
      hover(track, function () { return ["+" + fmt(st.added) + " residents", ["Step " + (k + 1) + ": " + c.name, rate, "running total " + fmt(st.total), st.new_miles_total + " mi of new path so far"]]; });
      host.appendChild(track);
    });
    fillTable($("t-pack"), "The build-out, step by step", ["Step", "Segment", "Adds", "Per new mile", "Running total", "New miles so far"], 2,
      steps.map(function (st, k) {
        return [String(k + 1), segs.candidates[st.i].name, fmt(st.added), st.per_new_mile == null ? "existing" : fmt(st.per_new_mile), fmt(st.total), String(st.new_miles_total)];
      }));
  }

  // ---- table view: every number, without hovering ----
  function fillTable(host, caption, head, firstNum, rows) {
    if (!host) return;
    host.textContent = "";
    host.appendChild(el("caption", null, caption));
    var tr = host.appendChild(el("thead")).appendChild(el("tr"));
    head.forEach(function (h, i) { tr.appendChild(el("th", i >= firstNum ? "num" : null, h)).scope = "col"; });
    var body = host.appendChild(el("tbody"));
    rows.forEach(function (r) {
      var row = body.appendChild(el("tr"));
      r.forEach(function (c, i) { row.appendChild(el("td", i >= firstNum ? "num" : null, c)); });
    });
  }
  function buildTables() {
    var total = data.meta.population, th = data.meta.thresholds;
    fillTable($("t-bands"), "Residents by ride time to the Loop", ["Ride time", "Residents", "Share"], 1,
      data.bands.map(function (b) { return [b.label, fmt(b.pop), pct(b.pop, total)]; }));
    fillTable($("t-places"), "Residents farther than each limit, by community",
      ["Community", "Residents"].concat(th.map(function (t) { return "Over " + t + " min"; })), 1,
      data.places.map(function (p) { return [p.name, fmt(p.pop)].concat(th.map(function (t) { return fmt(p.far[String(t)]); })); }));
    if (segs) fillTable($("t-cands"), "Residents each candidate would bring within each limit",
      ["Candidate", "Type", "Miles", "Reaches the Loop"].concat(segs.meta.thresholds.map(function (t) { return "Within " + t + " min"; })), 2,
      segs.candidates.map(function (c) {
        return [c.name, kindText(c), c.miles.toFixed(1), c.connects_to_loop ? "yes" : "no"].concat(segs.meta.thresholds.map(function (t) { return fmt(c.gained[String(t)]); }));
      }));
  }

  // ---- numbers quoted in the page text ----
  function fillText() {
    var o = data.meta.outside_study_area, b = data.meta.study_bbox_south_west_north_east;
    var vals = {
      total: fmt(data.meta.population), loop_miles: String(loop.miles), built: data.meta.generated.slice(0, 10),
      outside_pop: fmt(o.population), outside_nearest: String(o.nearest_straight_line_miles), outside_within5: fmt(o.population_within_5_straight_line_miles),
      bbox: "latitude " + b[0] + " to " + b[2] + ", longitude " + b[1] + " to " + b[3], hex_m: String(data.meta.hex_radius_m)
    };
    if (segs) {
      vals.tested = String(segs.meta.candidates_tested); vals.access_m = String(segs.meta.access_m);
      vals.loop_near_m = String(segs.meta.loop_near_m); vals.min_path_miles = String(segs.meta.min_path_miles);
    }
    document.querySelectorAll("[data-fill]").forEach(function (n) { var v = vals[n.getAttribute("data-fill")]; if (v != null) n.textContent = v; });
  }

  function render() { renderSettings(); renderLead(); layoutSplit(); renderMap(); renderRank(); renderSegments(); }

  function getJSON(name) {
    return fetch(DATA + name).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
  }
  Promise.all([getJSON("access.json"), getJSON("loop.json"), growPage ? getJSON("segments.json") : Promise.resolve(null)])
    .then(function (res) {
      data = res[0]; loop = res[1]; segs = res[2];
      readQuery();
      buildSplit(); buildTables(); fillText(); buildMap();
      render();
      setMsg("Ready");
      window.addEventListener("resize", layoutSplit);
    })
    .catch(function () {
      var box = $("map-error"), text = "Could not load the project data. Try reloading the page.";
      if (box) { box.textContent = text; box.hidden = false; }
      setMsg(text);
    });
})();
