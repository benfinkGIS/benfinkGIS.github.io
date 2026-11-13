/* KXCI Signal Reach: map, figures and tables.
   Reads data/kxci.json and data/field.png (both written by tools/publish_kxci.py).
   field.png is a data image: red = modelled dBu x 2 at 9.1 m, green = the same at 1.5 m,
   blue = 255 inside the FCC contour. It is coloured here and read back on hover.
   Leaflet 1.9.4 is loaded by the page. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  var fmt = function (n) { return Math.round(n).toLocaleString("en-US"); };
  var pct = function (a, b) { return b ? Math.round(a / b * 100) + "%" : ""; };

  var RX = [["roof", "A rooftop antenna (9.1 m)", "at rooftop height", 0],
            ["car", "A car or table radio (1.5 m)", "at car height", 1]];
  var SHOW = [["field", "Modelled signal", "field"], ["shadow", "Shadows inside the contour", "hatch"],
              ["contour", "FCC contour", "cl"], ["old", "1991 contour", "ol"]];
  var BAND_LABELS = ["40 to 50 dBu", "50 to 60", "60 to 70", "70 to 80", "80 or more"];

  var d, rx = "roof", on = { field: true, shadow: true, contour: true, old: false };
  var map, base, labels, imagery, overlay, contourLayer, oldLayer, fullBounds;
  var px = null, W = 0, H = 0, canvas;

  function rxRow() { return RX.filter(function (r) { return r[0] === rx; })[0]; }
  function model() { return rx === "roof" ? d.rooftop : d.car; }
  function setMsg(t) { var m = $("sb-msg"); if (m) m.textContent = t; }
  function hex(c) { return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]; }
  function mercY(lat) { return Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)); }
  function km(a, b) {
    var R = 6371, p = Math.PI / 180, dla = (b[0] - a[0]) * p, dlo = (b[1] - a[1]) * p;
    var s = Math.pow(Math.sin(dla / 2), 2) + Math.cos(a[0] * p) * Math.cos(b[0] * p) * Math.pow(Math.sin(dlo / 2), 2);
    return 2 * R * Math.asin(Math.sqrt(s));
  }

  // ---- settings: toolbar-style buttons; the choices ride along in the address ----
  function readQuery() {
    var q = new URLSearchParams(location.search), show = q.get("show");
    if (q.get("rx") === "car") rx = "car";
    if (show !== null) {
      var want = show.split(",");
      SHOW.forEach(function (s) { on[s[0]] = want.indexOf(s[0]) >= 0; });
    }
  }
  function writeQuery() {
    var show = SHOW.filter(function (s) { return on[s[0]]; }).map(function (s) { return s[0]; }).join(",");
    history.replaceState(null, "", location.pathname + "?rx=" + rx + "&show=" + show);
  }
  function buildSettings() {
    RX.forEach(function (r) {
      var b = el("button", null, r[1]);
      b.type = "button";
      b.addEventListener("click", function () { rx = r[0]; render(); });
      $("rx-buttons").appendChild(b);
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
    RX.forEach(function (r, i) { $("rx-buttons").children[i].setAttribute("aria-pressed", r[0] === rx ? "true" : "false"); });
    SHOW.forEach(function (s, i) { $("show-buttons").children[i].setAttribute("aria-pressed", on[s[0]] ? "true" : "false"); });
    writeQuery();
  }

  // ---- figures ----
  function fill(key, text) {
    document.querySelectorAll('[data-fill="' + key + '"]').forEach(function (n) { n.textContent = text; });
  }
  function fillStatic() {
    var lic = d.licence, ov = d.places.filter(function (p) { return p.place === "Oro Valley"; })[0];
    fill("erp", fmt(lic.erp_kw * 1000));
    fill("agl", d.antenna_agl_m);
    fill("amsl", fmt(lic.rcamsl_m));
    fill("file", lic.file_number);
    fill("facility", lic.facility_id);
    fill("class", lic.station_class);
    fill("study", fmt(d.study.population));
    fill("radius", d.radius_km);
    fill("minpop", fmt(d.place_min_pop));
    fill("kmmin", d.fcc.km_min.toFixed(0));
    fill("kmmax", d.fcc.km_max.toFixed(0));
    fill("area", fmt(d.fcc.area_sqkm));
    fill("warn", Math.round(d.warn_share * 100) + "%");
    fill("roof-shadow", fmt(d.rooftop.inside_fcc_shadowed));
    fill("roof-extra", fmt(d.rooftop.outside_fcc_served));
    fill("car-shadow", fmt(d.car.inside_fcc_shadowed));
    fill("old-erp", fmt(d.lookup.erp_kw * 1000));
    fill("old-km", Math.round(km([lic.lat, lic.lon], [d.lookup.lat, d.lookup.lon])));
    if (ov) {
      fill("ov-pop", fmt(ov.population));
      fill("ov-fcc", fmt(ov.inside_fcc));
      fill("ov-shadow", fmt(ov.shadowed_9m));
    }
    $("hero-num").textContent = fmt(d.fcc.population);
    $("hh-num").textContent = fmt(d.fcc.households);
  }
  function renderLead() {
    var m = model();
    $("shadow-num").textContent = fmt(m.inside_fcc_shadowed);
    $("shadow-lab").textContent = "of those residents (" + pct(m.inside_fcc_shadowed, d.fcc.population) +
      ") are under 60 dBu in the terrain model " + rxRow()[2];
  }

  // ---- three ways to count: bars on one scale ----
  function renderCounts() {
    var host = $("counts"), max = d.fcc.population;
    var rows = [
      ["FCC contour", d.fcc.population, "inside the line", false],
      ["Terrain model, rooftop", d.rooftop.served.population, fmt(d.rooftop.inside_fcc_served) + " inside the line, " + fmt(d.rooftop.outside_fcc_served) + " outside", rx === "roof"],
      ["Terrain model, car height", d.car.served.population, fmt(d.car.inside_fcc_served) + " inside the line, " + fmt(d.car.outside_fcc_served) + " outside", rx === "car"]
    ];
    rows.forEach(function (r) { max = Math.max(max, r[1]); });
    host.textContent = "";
    rows.forEach(function (r) {
      var name = el("div", "name", r[0]);
      if (r[3]) name.style.fontWeight = "bold";
      var track = el("div", "track"), bar = el("div", "bar");
      bar.style.width = "calc((100% - 170px) * " + (r[1] / max).toFixed(4) + ")";
      track.tabIndex = 0;
      track.setAttribute("role", "img");
      track.setAttribute("aria-label", r[0] + ": " + fmt(r[1]) + " residents, " + r[2]);
      track.appendChild(bar);
      var val = el("span", "val", fmt(r[1]) + " ");
      val.appendChild(el("small", null, "(" + r[2] + ")"));
      track.appendChild(val);
      hoverTip(track, function () { return [r[0], fmt(r[1]) + " residents at 60 dBu or more: " + r[2] + "."]; });
      host.appendChild(name);
      host.appendChild(track);
    });
  }

  // ---- town table ----
  function renderPlaces() {
    var t = $("t-places");
    t.textContent = "";
    var head = el("tr");
    [["Town", ""], ["Residents", "num"], ["Inside FCC contour", "num"], ["Model, rooftop", "num"], ["Model, car height", "num"]]
      .forEach(function (h) { var th = el("th", h[1], h[0]); th.scope = "col"; head.appendChild(th); });
    var thead = el("thead"); thead.appendChild(head); t.appendChild(thead);
    var body = el("tbody");
    d.places.forEach(function (p) {
      var tr = el("tr");
      var th = el("td", null, p.place === "Saddlebrooke" ? "SaddleBrooke" : p.place);
      tr.appendChild(th);
      tr.appendChild(el("td", "num", fmt(p.population)));
      tr.appendChild(el("td", "num", fmt(p.inside_fcc)));
      [p.modelled_9m, p.modelled_1p5m].forEach(function (v) {
        // marked when the model serves under three quarters of the residents the contour takes in
        var gap = p.inside_fcc >= 500 && v < 0.75 * p.inside_fcc;
        var td = el("td", "num" + (gap ? " gap" : ""), fmt(v) + (gap ? " ▼" : ""));
        if (gap) td.title = "Under three quarters of the residents inside the FCC contour";
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    t.appendChild(body);
  }
  function renderOld() {
    var t = $("t-old"), lic = d.licence, o = d.lookup;
    var rows = [
      ["", "Licence on file now", "What the call-sign lookup returns"],
      ["Licence file", lic.file_number, o.file_number],
      ["Site", "Southeast of Tucson (" + lic.lat.toFixed(4) + ", " + lic.lon.toFixed(4) + ")", "Mt. Bigelow (" + o.lat.toFixed(4) + ", " + o.lon.toFixed(4) + ")"],
      ["Power", fmt(lic.erp_kw * 1000) + " watts", fmt(o.erp_kw * 1000) + " watts"],
      ["Antenna centre above sea level", fmt(lic.rcamsl_m) + " m", fmt(o.rcamsl_m) + " m"],
      ["Residents inside the 60 dBu contour", fmt(d.fcc.population), fmt(d.fcc_1991.population)],
      ["Households inside", fmt(d.fcc.households), fmt(d.fcc_1991.households)]
    ];
    t.textContent = "";
    rows.forEach(function (r, i) {
      var tr = el("tr");
      r.forEach(function (c, j) {
        var cell = el(i === 0 ? "th" : "td", j > 0 && i > 3 ? "num" : (i === 0 && j > 0 ? "" : ""), c);
        if (i === 0) cell.scope = "col";
        tr.appendChild(cell);
      });
      t.appendChild(tr);
    });
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

  // ---- the signal layer: colour the data image for the chosen height ----
  function paint() {
    if (!px) return;
    var ch = rxRow()[3], out = canvas.getContext("2d").createImageData(W, H), o = out.data;
    var bands = d.bands.map(function (b) { return [b[0], hex(b[1])]; });
    var sh = hex(d.shadow), shDk = [184, 74, 31], th = d.threshold_dbu;
    for (var y = 0, i = 0; y < H; y++) {
      for (var x = 0; x < W; x++, i += 4) {
        var raw = px[i + ch];
        if (!raw) continue;
        var v = raw / 2, inside = px[i + 2] > 127, c = null, a = 170;
        if (on.shadow && inside && v < th) {
          c = (x + y) % 5 < 2 ? shDk : sh;               // striped, so it is never colour alone
          a = 215;
        } else if (on.field) {
          for (var k = bands.length - 1; k >= 0; k--) { if (v >= bands[k][0]) { c = bands[k][1]; break; } }
        }
        if (!c) continue;
        o[i] = c[0]; o[i + 1] = c[1]; o[i + 2] = c[2]; o[i + 3] = a;
      }
    }
    canvas.getContext("2d").putImageData(out, 0, 0);
    var url = canvas.toDataURL("image/png");
    if (overlay) overlay.setUrl(url);
    else overlay = L.imageOverlay(url, d.bounds, { pane: "field", interactive: false }).addTo(map);
  }
  function readAt(ll) {
    if (!px) return null;
    var b = d.bounds, x = Math.floor((ll.lng - b[0][1]) / (b[1][1] - b[0][1]) * W);
    var y = Math.floor((mercY(b[1][0]) - mercY(ll.lat)) / (mercY(b[1][0]) - mercY(b[0][0])) * H);
    if (x < 0 || y < 0 || x >= W || y >= H) return null;
    var i = (y * W + x) * 4, raw = px[i + rxRow()[3]];
    if (!raw) return null;
    return { dbu: raw / 2, inside: px[i + 2] > 127 };
  }
  function describe(r) {
    if (!r) return ["Outside the model", "The model stops " + d.radius_km + " km from the tower."];
    var th = d.threshold_dbu, text;
    if (r.inside && r.dbu < th) text = "Inside the FCC contour, but under " + th + " dBu in the model: a shadow.";
    else if (r.inside) text = "Inside the FCC contour, and the model agrees.";
    else if (r.dbu >= th) text = "Outside the FCC contour, but " + th + " dBu or more in the model.";
    else text = "Outside the FCC contour.";
    return [(r.dbu >= 119 ? "Over 119" : "About " + Math.round(r.dbu)) + " dBu " + rxRow()[2], text];
  }

  // ---- map ----
  function txIcon(kind) {
    var svg = {
      main: '<svg width="22" height="20" viewBox="0 0 22 20"><path d="M11 1 21 19H1Z" fill="#ffff00" stroke="#000" stroke-width="2" stroke-linejoin="round"/></svg>',
      old: '<svg width="18" height="16" viewBox="0 0 18 16"><path d="M9 1 17 15H1Z" fill="#fff" stroke="#5b2a86" stroke-width="2" stroke-dasharray="3 2" stroke-linejoin="round"/></svg>',
      aux: '<svg width="14" height="14" viewBox="0 0 14 14"><rect x="1.5" y="1.5" width="11" height="11" fill="#fff" stroke="#000" stroke-width="2"/></svg>'
    }[kind];
    var size = kind === "main" ? [22, 20] : kind === "old" ? [18, 16] : [14, 14];
    return L.divIcon({ className: "tx-mark", html: svg, iconSize: size, iconAnchor: [size[0] / 2, size[1] / 2] });
  }
  function popup(title, lines) {
    var box = el("div");
    box.appendChild(el("strong", null, title));
    lines.forEach(function (t) { box.appendChild(el("div", null, t)); });
    return box;
  }
  function buildMap() {
    var mapEl = $("map"), lic = d.licence;
    var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
    map = L.map(mapEl, { zoomControl: false, minZoom: 8, maxZoom: 14, zoomSnap: 0.25, scrollWheelZoom: false });
    map.on("click focus", function () { map.scrollWheelZoom.enable(); });
    mapEl.addEventListener("mouseleave", function () { map.scrollWheelZoom.disable(); });
    ["field", "lines", "labels"].forEach(function (p, i) {
      map.createPane(p).style.zIndex = 410 + 5 * i;
      map.getPane(p).style.pointerEvents = "none";
    });
    base = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 18,
      attribution: "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS user community" }).addTo(map);
    labels = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 18, pane: "labels" }).addTo(map);
    imagery = L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 18, maxZoom: 18,
      attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS user community" });
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution("FCC, USGS 3DEP, 2020 Census");
    L.control.scale({ imperial: true, metric: true }).addTo(map);

    var ring = d.contour.map(function (c) { return [c[1], c[0]]; });
    contourLayer = L.layerGroup([
      L.polyline(ring, { pane: "lines", interactive: false, color: "#ffffff", weight: 6, opacity: 0.95 }),
      L.polyline(ring, { pane: "lines", interactive: false, color: "#000000", weight: 2.5 })
    ]);
    var oldRing = d.contour_1991.map(function (c) { return [c[1], c[0]]; });
    oldLayer = L.layerGroup([
      L.polyline(oldRing, { pane: "lines", interactive: false, color: "#ffffff", weight: 5, opacity: 0.9 }),
      L.polyline(oldRing, { pane: "lines", interactive: false, color: "#5b2a86", weight: 2.5, dashArray: "7 5" }),
      L.marker([d.lookup.lat, d.lookup.lon], { icon: txIcon("old"), title: "Mt. Bigelow: the 1991 licence", alt: "Mt. Bigelow, the 1991 licence" })
        .bindPopup(popup("Mt. Bigelow (1991 licence)", [fmt(d.lookup.erp_kw * 1000) + " watts, antenna " + fmt(d.lookup.rcamsl_m) + " m above sea level",
          "Licence file " + d.lookup.file_number, "Still what the FCC's contour lookup returns for KXCI."]), { maxWidth: 250 })
    ]);
    L.marker([lic.lat, lic.lon], { icon: txIcon("main"), title: "KXCI tower", alt: "KXCI tower", zIndexOffset: 1000 })
      .bindPopup(popup("KXCI 91.3 FM", [fmt(lic.erp_kw * 1000) + " watts, non-directional", "Antenna " + d.antenna_agl_m + " m above the ground, " + fmt(lic.rcamsl_m) + " m above sea level",
        "Class " + lic.station_class + ", licence file " + lic.file_number]), { maxWidth: 250 }).addTo(map);
    d.auxiliary.forEach(function (a) {
      L.marker([a.lat, a.lon], { icon: txIcon("aux"), title: "KXCI backup transmitter", alt: "KXCI backup transmitter" })
        .bindPopup(popup("Backup transmitter", [fmt(a.erp_kw * 1000) + " watts, directional", "Licensed as an auxiliary. Not modelled here."]), { maxWidth: 230 }).addTo(map);
    });
    fullBounds = L.latLngBounds(ring).pad(0.12);
    map.fitBounds(fullBounds, { animate: false });
    // if the page was laid out late (a background tab, a slow stylesheet), fit again once it settles
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
    var sat = $("tb-base");
    sat.addEventListener("click", function () {
      var show = sat.getAttribute("aria-pressed") !== "true";
      sat.setAttribute("aria-pressed", show ? "true" : "false");
      if (show) { map.removeLayer(base); map.removeLayer(labels); imagery.addTo(map); }
      else { map.removeLayer(imagery); base.addTo(map); labels.addTo(map); }
    });
    var pos = $("sb-pos");
    function coord(ll) { return Math.abs(ll.lat).toFixed(4) + "° N, " + Math.abs(ll.lng).toFixed(4) + "° W"; }
    map.on("mousemove", function (e) {
      pos.textContent = coord(e.latlng);
      var c = describe(readAt(e.latlng));
      setMsg(c[0] + ". " + c[1]);
      showTip(e.originalEvent.clientX, e.originalEvent.clientY, c[0], c[1]);
    });
    map.on("mouseout", function () { pos.textContent = coord(map.getCenter()); hideTip(); setMsg(statusText()); });
    map.on("click", function (e) { var c = describe(readAt(e.latlng)); setMsg(c[0] + ". " + c[1]); });   // touch screens
    pos.textContent = coord(map.getCenter());
  }
  function statusText() { return "Modelled signal " + rxRow()[2] + ". Point at the map for a reading."; }
  function renderMap() {
    paint();
    [[contourLayer, on.contour], [oldLayer, on.old]].forEach(function (x) {
      if (x[1] && !map.hasLayer(x[0])) x[0].addTo(map);
      if (!x[1] && map.hasLayer(x[0])) map.removeLayer(x[0]);
    });
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
    if (on.field) d.bands.forEach(function (b, i) { item("sw", BAND_LABELS[i], b[1]); });
    if (on.shadow) item("sw hatch", "Inside the contour, under 60 dBu");
    if (on.contour) item("cline", "FCC 60 dBu contour");
    if (on.old) item("oline", "1991 Mt. Bigelow contour");
    item("tri", "KXCI tower");
  }

  function render() {
    renderSettings();
    renderLead();
    renderCounts();
    renderMap();
  }

  function fail(msg) {
    var e = $("map-error");
    if (e) { e.textContent = msg; e.hidden = false; }
    setMsg("Could not load the data.");
  }
  function loadImage(src) {
    return new Promise(function (ok, bad) {
      var im = new Image();
      im.onload = function () { ok(im); };
      im.onerror = function () { bad(new Error("image")); };
      im.src = src;
    });
  }

  readQuery();
  buildSettings();
  Promise.all([
    fetch("/kxci-signal/data/kxci.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }),
    loadImage("/kxci-signal/data/field.png")
  ]).then(function (got) {
    d = got[0];
    var im = got[1];
    W = im.naturalWidth; H = im.naturalHeight;
    var src = document.createElement("canvas");
    src.width = W; src.height = H;
    var ctx = src.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(im, 0, 0);
    px = ctx.getImageData(0, 0, W, H).data;
    canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    fillStatic();
    renderPlaces();
    renderOld();
    buildMap();
    render();
  }).catch(function (err) {
    fail("The signal data did not load. Reload the page to try again.");
    if (window.console) console.error(err);
  });
})();
