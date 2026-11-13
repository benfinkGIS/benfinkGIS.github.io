/* Kit fox release page: the wizard, the map and the charts.
   Everything it shows comes from /kit-fox-release/data/, written by tools/publish_kitfox.py.
   The eight criterion scores arrive as three PNGs (one criterion per colour channel), so the
   weighted average can be recomputed here whenever a weight changes. */
(function () {
  "use strict";

  var DATA = "/kit-fox-release/data/";
  var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
  /* one hue, light to dark: the site's sequential blue ramp */
  var RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
              "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"];
  var CAND = "#eb6834";
  /* designation kinds: plural name, colour, how a sentence refers to one */
  var KINDS = {
    wilderness: ["Wilderness", "#006300", "wilderness"],
    wsa: ["Wilderness study areas", "#00574f", "a wilderness study area"],
    monument: ["National monuments and conservation areas", "#6250d6", "a national monument or conservation area"],
    acec: ["Areas of critical environmental concern", "#8a1c1c", "an area of critical environmental concern"]
  };
  var LO = 3, HI = 9;      // scores at or beyond these take the ends of the ramp

  /* What each criterion measures and how it was scored. The breaks are the ones used in the model. */
  var CRIT = {
    vegtype: {
      title: "Vegetation type",
      text: "What grows there, from LANDFIRE 2024. Open desert scrub scores highest. Woodland, forest, farms and built-up land score lowest.",
      head: "Vegetation",
      rows: [["Paloverde-cactus, creosote-bursage and mid-elevation desert scrub", "10"],
             ["Semi-desert shrub-steppe, salt desert scrub", "7 to 8"],
             ["Desert grassland, sagebrush, wash and riparian shrubland", "5 to 6"],
             ["Bare rock, desert pavement, playa", "4"],
             ["Pinyon-juniper and ponderosa woodland", "3"],
             ["Chaparral, oak and conifer forest", "2"],
             ["Built-up land, crops, planted or weedy ground", "1"]]
    },
    vegcover: {
      title: "Vegetation cover",
      text: "How much of the ground the plants cover, from LANDFIRE 2024. Open ground with scattered shrubs scores highest.",
      head: "Cover",
      rows: [["Shrub cover 10 to 17%", "10"], ["Shrub cover 18 to 25%", "9"], ["Shrub cover 26 to 30%", "8"],
             ["Shrub cover 31 to 35%", "7"], ["Denser shrub or grass, or very sparse plants", "4 to 6"],
             ["Tree cover", "2 to 3"], ["Built-up land, crops, open water", "1"]]
    },
    soil: {
      title: "Soils",
      text: "Kit foxes live in dens they dig, so the ground matters. Each soil map unit in the USDA SSURGO survey was given a score from 1 to 10.",
      head: null, rows: []
    },
    lights: {
      title: "Night lights",
      text: "How bright the ground is at night, seen from orbit (VIIRS, 2024). Light marks towns, mines and busy roads. Dark scores highest.",
      head: "Brightness (nW/cm²/sr)",
      rows: [["Under 1", "10"], ["1 to 5", "9"], ["5 to 15", "7"], ["15 to 40", "5"], ["40 to 80", "3"], ["80 to 150", "2"], ["Over 150", "1"]]
    },
    elevation: {
      title: "Elevation",
      text: "Height above sea level, from the USGS 30 m elevation model. The low desert valleys score highest.",
      head: "Elevation",
      rows: [["300 to 900 m", "10"], ["900 to 1,200 m", "8"], ["1,200 to 1,500 m", "6"], ["150 to 300 m", "5"],
             ["1,500 to 1,800 m", "4"], ["Under 150 m", "2"], ["Over 1,800 m", "1"]]
    },
    developed: {
      title: "Distance from towns and farms",
      text: "Straight-line distance from built-up and farmed land, taken from LANDFIRE 2024. Farther is better.",
      head: "Distance",
      rows: [["Over 4 km", "10"], ["2 to 4 km", "7"], ["1 to 2 km", "5"], ["500 m to 1 km", "4"], ["Under 500 m", "2"]]
    },
    slope: {
      title: "Slope",
      text: "How steep the ground is, from the same elevation model. Flat ground scores highest.",
      head: "Slope",
      rows: [["0 to 3°", "10"], ["3 to 8°", "8"], ["8 to 15°", "6"], ["15 to 25°", "4"], ["25 to 35°", "2"], ["Over 35°", "1"]]
    },
    water: {
      title: "Distance to water",
      text: "Straight-line distance to the nearest stream, wash or water body in the National Hydrography Dataset. Close, but not right on it, scores highest.",
      head: "Distance",
      rows: [["500 m to 1.5 km", "10"], ["Under 500 m", "8"], ["1.5 to 3 km", "8"], ["3 to 5 km", "6"], ["5 to 8 km", "4"], ["Over 8 km", "2"]]
    }
  };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(n) { return Math.round(n).toLocaleString("en-US"); }
  function pct(x) { return Math.round(x * 100) + "%"; }
  function fail(text) {
    var e = $("map-error");
    if (e) { e.textContent = text; e.hidden = false; }
    $("sb-msg").textContent = "Error";
  }
  if (typeof L === "undefined") { fail("The map library did not load. Check your connection and reload the page."); return; }

  var D = null;            // model.json
  var layers = [];         // one Uint8Array per criterion: score x scale, 0 = outside the search area
  var rowArea = null;      // true ground area of a cell, by row (relative)
  var weights = [], base = [];
  var baseShare = 0;
  var step = 0, steps = [];
  var view = { kind: "none" };   // what the map is showing: none | crit (index) | combo (weights)
  var canvas = document.createElement("canvas"), ctx = null, img = null, lut = null;
  var map, overlay, labels, shortLayer = L.layerGroup(), desigLayer = L.layerGroup(), marks = {};
  var desigShown = false, desigAuto = false;
  var mercTop, mercBottom;

  /* ---------- map ---------- */
  /* An image overlay whose image is a canvas we redraw, so a weight change shows at once. */
  var CanvasOverlay = L.ImageOverlay.extend({
    _initImage: function () {
      var el = this._image = this._url;
      L.DomUtil.addClass(el, "leaflet-image-layer");
      if (this._zoomAnimated) L.DomUtil.addClass(el, "leaflet-zoom-animated");
      el.onselectstart = L.Util.falseFn;
      el.onmousemove = L.Util.falseFn;
    }
  });

  function buildLut() {
    var stops = RAMP.map(function (h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; });
    lut = new Uint8Array(256 * 3);
    for (var i = 0; i < 256; i++) {
      var x = i / 255 * (stops.length - 1), a = Math.min(Math.floor(x), stops.length - 2), f = x - a;
      for (var c = 0; c < 3; c++) lut[i * 3 + c] = Math.round(stops[a][c] * (1 - f) + stops[a + 1][c] * f);
    }
  }

  /* Score (1 to 10) of cell i under the current view, or 0 outside the search area. */
  function scoreAt(i) {
    if (!layers[0][i] || view.kind === "none") return 0;
    var s = D.grid.scale;
    if (view.kind === "crit") return layers[view.index][i] / s;
    var t = 0, wsum = 0;
    for (var k = 0; k < layers.length; k++) { t += view.weights[k] * layers[k][i]; wsum += view.weights[k]; }
    return wsum ? t / (wsum * s) : 0;
  }

  /* Redraw the overlay. Returns the share of the search area scoring the cutoff or more. */
  function draw() {
    var w = D.grid.w, h = D.grid.h, px = img.data, s = D.grid.scale, cut = D.high_cutoff;
    var n = layers.length, ws = view.weights || [], wsum = 0, k;
    for (k = 0; k < ws.length; k++) wsum += ws[k];
    var single = view.kind === "crit" ? layers[view.index] : null;
    var off = view.kind === "none" || (view.kind === "combo" && !wsum);
    var area = 0, high = 0;
    for (var r = 0, i = 0; r < h; r++) {
      var ra = rowArea[r];
      for (var c = 0; c < w; c++, i++) {
        var o = i * 4;
        if (off || !layers[0][i]) { px[o + 3] = 0; continue; }
        var v;
        if (single) v = single[i] / s;
        else {
          var t = 0;
          for (k = 0; k < n; k++) t += ws[k] * layers[k][i];
          v = t / (wsum * s);
        }
        area += ra;
        if (v >= cut) high += ra;
        var j = Math.max(0, Math.min(255, Math.round((v - LO) / (HI - LO) * 255))) * 3;
        px[o] = lut[j]; px[o + 1] = lut[j + 1]; px[o + 2] = lut[j + 2]; px[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return area ? high / area : 0;
  }

  var pending = false;
  function redrawSoon(after) {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; var share = draw(); if (after) after(share); });
  }

  function cellAt(latlng) {
    var b = D.grid.bounds;
    var fx = (latlng.lng - b[0][1]) / (b[1][1] - b[0][1]);
    var y = L.Projection.SphericalMercator.project(latlng).y;
    var fy = (mercTop - y) / (mercTop - mercBottom);
    if (fx < 0 || fx >= 1 || fy < 0 || fy >= 1) return -1;
    return Math.floor(fy * D.grid.h) * D.grid.w + Math.floor(fx * D.grid.w);
  }

  function initMap() {
    var b = D.grid.bounds;
    map = L.map("map", { minZoom: 6, maxZoom: 10, zoomControl: false, zoomSnap: 0.25, scrollWheelZoom: false });
    L.tileLayer(ESRI + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 10, attribution: "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
    }).addTo(map);
    map.createPane("scores").style.zIndex = 250;
    map.createPane("desig").style.zIndex = 300;
    map.createPane("labels").style.zIndex = 450;
    map.getPane("labels").style.pointerEvents = "none";
    labels = L.tileLayer(ESRI + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxZoom: 10, pane: "labels" }).addTo(map);
    map.attributionControl.setPrefix(false);
    L.control.scale({ imperial: true, metric: true }).addTo(map);

    overlay = new CanvasOverlay(canvas, b, { opacity: 0.88, pane: "scores", interactive: false }).addTo(map);
    var ring = L.polygon(D.study_area, { color: "#000", weight: 2, dashArray: "6 5", fill: false, interactive: false }).addTo(map);
    L.circleMarker(D.center, { radius: 6, color: "#000", weight: 2, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip("The wildlife center", { className: "kit-tip", direction: "top" }).addTo(map);
    var full = ring.getBounds();
    map.fitBounds(full, { padding: [8, 8] });

    D.shortlist.forEach(function (p) {
      var where = "about " + p.center_km + " km " + p.dir + " of the center";
      var tip = "<strong>Area " + p.rank + "</strong><br>" + esc(p.manager) + " land, " + where + "<br>Average score " + p.score.toFixed(2) +
        "<br>" + esc(desigText(p)) + "<br>Shown to within about 10 km";
      var c = L.circle([p.lat, p.lon], { radius: 8000, color: CAND, weight: 3, fill: true, fillOpacity: 0, fillColor: CAND });
      var m = L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", html: '<div class="cand-num">' + p.rank + "</div>", iconSize: [22, 22], iconAnchor: [11, 11] }), keyboard: false });
      c.bindTooltip(tip, { className: "kit-tip", sticky: true });
      m.bindTooltip(tip, { className: "kit-tip", direction: "top", offset: [0, -10] });
      shortLayer.addLayer(c).addLayer(m);
      marks[p.rank] = m;
    });

    (D.designations || []).forEach(function (d) {
      var k = KINDS[d.kind] || [d.label, "#333", ""];
      var polys = d.polys.map(function (ring) { return [ring]; });
      L.polygon(polys, { pane: "desig", color: "#fff", weight: 4, fill: false, interactive: false }).addTo(desigLayer);
      L.polygon(polys, { pane: "desig", color: k[1], weight: 2, fillColor: k[1], fillOpacity: 0.08 })
        .bindTooltip("<strong>" + esc(d.name) + "</strong><br>" + esc(d.label), { className: "kit-tip", sticky: true }).addTo(desigLayer);
    });
    var kinds = Object.keys(KINDS).filter(function (k) { return (D.designations || []).some(function (d) { return d.kind === k; }); });
    $("key-desig").innerHTML = kinds.map(function (k) { return '<b><i style="border-color:' + KINDS[k][1] + '"></i>' + esc(KINDS[k][0]) + "</b>"; }).join("");
    $("tb-desig").addEventListener("click", function () { showDesig(!desigShown); });

    $("tb-in").addEventListener("click", function () { map.zoomIn(); });
    $("tb-out").addEventListener("click", function () { map.zoomOut(); });
    $("tb-full").addEventListener("click", function () { map.fitBounds(full, { padding: [8, 8] }); });
    $("tb-labels").addEventListener("click", function () {
      var on = this.getAttribute("aria-pressed") !== "true";
      this.setAttribute("aria-pressed", String(on));
      if (on) labels.addTo(map); else map.removeLayer(labels);
    });
    map.on("mousemove", function (e) {
      var i = cellAt(e.latlng), v = i < 0 ? 0 : scoreAt(i);
      $("sb-pos").textContent = view.kind === "none" ? " " : v ? "Score here: " + v.toFixed(1) : "Outside the search area";
    });
    map.on("mouseout", function () { $("sb-pos").textContent = " "; });
  }

  function showDesig(on) {
    desigShown = on;
    $("tb-desig").setAttribute("aria-pressed", String(on));
    $("key-desig").hidden = !on;
    if (on) desigLayer.addTo(map); else map.removeLayer(desigLayer);
  }
  /* What the page says about the designations a shortlisted area touches. */
  function desigText(p) {
    if (!p.designations || !p.designations.length) return "No designation found";
    return p.designations.map(function (d) {
      if (d.level === "in") return "In " + d.name;
      if (d.level === "mostly") return "Mostly in " + d.name;
      return "Partly in " + (KINDS[d.kind] ? KINDS[d.kind][2] : d.label.toLowerCase());
    }).join("; ");
  }

  /* ---------- wizard ---------- */
  function scoringTable(c) {
    if (!c.rows.length) return "";
    return "<table><thead><tr><th>" + esc(c.head) + "</th><th>Score</th></tr></thead><tbody>" +
      c.rows.map(function (r) { return "<tr><td>" + esc(r[0]) + "</td><td>" + esc(r[1]) + "</td></tr>"; }).join("") + "</tbody></table>";
  }

  function buildSteps() {
    steps.push({
      name: "The search area",
      msg: "The search area",
      show: function () { return { kind: "none" }; },
      html: function () {
        return "<h3>Welcome to the Kit Fox Release Wizard</h3>" +
          "<p>The dashed circle is the search area: everywhere within 100 miles of the center, " + num(D.study_km2) + " km² of central Arizona.</p>" +
          "<p>The next " + D.criteria.length + " screens add one thing at a time. Each scores the land from 1 (poor for a kit fox) to 10 (good).</p>" +
          "<p>After that you can weigh them against each other, and see the areas that made the shortlist.</p>" +
          "<p>Click Next to continue.</p>";
      }
    });
    D.criteria.forEach(function (c, i) {
      var info = CRIT[c.key];
      steps.push({
        name: info.title,
        msg: info.title + ": score from 1 to 10",
        show: function () { return { kind: "crit", index: i }; },
        html: function () {
          return "<h3>" + esc(info.title) + "</h3>" +
            '<p class="weight"><span>Weight ' + c.weight + ' of 100</span><i><b style="width:' + c.weight + '%"></b></i></p>' +
            "<p>" + esc(info.text) + "</p>" + scoringTable(info);
        }
      });
    });
    steps.push({
      name: "Set the weights",
      msg: "All " + D.criteria.length + " combined, with your weights",
      show: function () { return { kind: "combo", weights: weights }; },
      html: function () {
        var rows = D.criteria.map(function (c, i) {
          return '<label for="w' + i + '">' + esc(CRIT[c.key].title) + "</label>" +
            '<input type="range" id="w' + i + '" data-i="' + i + '" min="0" max="40" step="1" value="' + weights[i] + '">' +
            '<output id="o' + i + '" for="w' + i + '"></output>';
        }).join("");
        return "<h3>Set the weights</h3>" +
          "<p>The final score is a weighted average of the eight. These are the weights I used. Drag them to see how much the map depends on them.</p>" +
          '<p class="readout"><strong id="share">&hellip;</strong> of the search area scores ' + D.high_cutoff + ' or more<br><span id="share-base"></span></p>' +
          '<div class="sliders" id="sliders">' + rows + "</div>" +
          '<p><button type="button" class="btn" id="reset">Reset to my weights</button></p>';
      },
      after: function () {
        $("sliders").addEventListener("input", function (e) {
          var i = +e.target.getAttribute("data-i");
          if (isNaN(i)) return;
          weights[i] = +e.target.value;
          showWeights();
          redrawSoon(showShare);
        });
        $("reset").addEventListener("click", function () {
          weights = base.slice();
          D.criteria.forEach(function (c, i) { $("w" + i).value = weights[i]; });
          view.weights = weights;
          showWeights();
          redrawSoon(showShare);
        });
        showWeights();
      }
    });
    steps.push({
      name: "The shortlist",
      msg: "All " + D.criteria.length + " combined, with the original weights",
      shortlist: true,
      show: function () { return { kind: "combo", weights: base }; },
      html: function () {
        var s = D.settings;
        return "<h3>The shortlist</h3>" +
          "<p>A high score is not enough. A release area also has to be somewhere a release could happen.</p>" +
          "<p>Every possible " + s.radius_km + " km circle was scored, then kept only if it is nearly all open public land, close to flat, and away from highways.</p>" +
          "<p>The orange rings are the " + D.shortlist.length + " best that are left. Each ring is drawn large and off-centre on purpose: it shows the general area, not the spot.</p>" +
          "<p>The outlines are wilderness and other designated areas. Use the Designations button to hide them.</p>" +
          '<p><a href="#shortlist">See the table below</a>.</p>' +
          (changed() ? "<p><em>This screen uses the original weights, not the ones you set.</em></p>" : "");
      }
    });
  }

  function changed() { return weights.some(function (w, i) { return w !== base[i]; }); }
  function showWeights() {
    var sum = weights.reduce(function (a, b) { return a + b; }, 0);
    weights.forEach(function (w, i) { $("o" + i).textContent = sum ? pct(w / sum) : "0%"; });
  }
  function showShare(share) {
    var el = $("share");
    if (!el) return;
    el.textContent = pct(share);
    $("share-base").textContent = changed() ? "With my weights: " + pct(baseShare) : "These are my weights.";
  }

  function go(n) {
    step = Math.max(0, Math.min(steps.length - 1, n));
    var s = steps[step];
    $("wiz-text").innerHTML = s.html();
    $("wiz-text").scrollTop = 0;
    if (s.after) s.after();
    $("wiz-count").textContent = "Step " + (step + 1) + " of " + steps.length;
    $("wiz-bar").style.width = (step + 1) / steps.length * 100 + "%";
    $("wiz-back").disabled = step === 0;
    $("wiz-next").disabled = step === steps.length - 1;
    $("wiz-jump").value = String(step);
    view = s.show();
    if (s.shortlist) shortLayer.addTo(map); else map.removeLayer(shortLayer);
    $("key-short").hidden = !s.shortlist;
    if (s.shortlist && !desigAuto) { desigAuto = true; showDesig(true); }   // on the first visit; the button still turns it off
    $("sb-msg").textContent = s.msg;
    redrawSoon(showShare);
  }

  /* ---------- the rest of the page ---------- */
  function fillPage() {
    var all = D.shortlist.every(function (p) { return p.manager === D.shortlist[0].manager; });
    $("hero-num").textContent = num(D.high_km2);
    $("hero-lab").textContent = "square kilometres score " + D.high_cutoff + " or more out of 10, of " + num(D.study_km2) + " in the search area";
    $("crit-num").textContent = D.criteria.length;
    $("crit-lab").textContent = "things weighed into one score from 1 to 10";
    $("short-num").textContent = D.shortlist.length;
    $("short-lab").textContent = "areas on the shortlist" + (all ? ", all on " + D.shortlist[0].manager + " land" : "");

    var s = D.settings;
    var fills = { study_km2: num(D.study_km2), high_km2: num(D.high_km2), high_cutoff: D.high_cutoff, radius_km: s.radius_km,
                  min_public: pct(s.min_public), max_slope_deg: s.max_slope_deg, road_gap_km: s.road_gap_km, top: s.top, spacing_km: s.spacing_km };
    Array.prototype.forEach.call(document.querySelectorAll("[data-fill]"), function (el) {
      var v = fills[el.getAttribute("data-fill")];
      if (v != null) el.textContent = v;
    });

    $("short-how").textContent = "The model only ranks land. To get from a map of scores to places someone could visit, every possible " +
      s.radius_km + " km circle was given its average score and put through three checks: nearly all open public land, close to flat, and no highway nearby. " +
      "These are the " + D.shortlist.length + " best that are left, each at least " + s.spacing_km + " km from the next.";

    $("t-short").innerHTML = "<caption>Shortlisted areas, best average score first</caption><thead><tr><th>#</th><th>Where</th><th>Land manager</th>" +
      '<th class="num">Average score</th><th class="num">Scores ' + D.high_cutoff + '+</th><th class="num">Average slope</th><th class="num">Nearest highway</th><th>Designations</th></tr></thead><tbody>' +
      D.shortlist.map(function (p) {
        return '<tr tabindex="0" data-rank="' + p.rank + '"><td>' + p.rank + "</td><td>About " + p.center_km + " km " + p.dir + "</td><td>" + esc(p.manager) + " " + pct(p.manager_share) +
          '</td><td class="num">' + p.score.toFixed(2) + '</td><td class="num">' + pct(p.high_share) + '</td><td class="num">' +
          (p.slope == null ? "" : p.slope.toFixed(1) + "°") + '</td><td class="num">' + p.road_km.toFixed(1) + " km</td><td>" + esc(desigText(p)) + "</td></tr>";
      }).join("") + "</tbody>";
    function pick(e) {
      var tr = e.target.closest("tr[data-rank]");
      if (!tr || (e.type === "keydown" && e.key !== "Enter" && e.key !== " ")) return;
      e.preventDefault();
      var p = D.shortlist[+tr.getAttribute("data-rank") - 1];
      go(steps.length - 1);
      $("wizard").scrollIntoView({ block: "nearest" });
      map.setView([p.lat, p.lon], 8.5);
      marks[p.rank].openTooltip();
    }
    $("t-short").addEventListener("click", pick);
    $("t-short").addEventListener("keydown", pick);

    var touched = D.shortlist.filter(function (p) { return p.designations && p.designations.length; }).length;
    var bits = [];
    Object.keys(KINDS).forEach(function (k) {
      var n = 0, inside = 0;
      D.shortlist.forEach(function (p) {
        var hit = (p.designations || []).filter(function (d) { return d.kind === k; });
        if (hit.length) { n++; if (hit.some(function (d) { return d.level !== "partly"; })) inside++; }
      });
      if (n) bits.push(n + (n === 1 ? " touches " : " touch ") + KINDS[k][2] + (inside ? " (" + (inside === n ? (n === 1 ? "" : "all ") : inside + " of them ") + "mostly or wholly inside)" : ""));
    });
    var land = (D.designated || []).filter(function (d) { return d.high_km2 > 0; }).map(function (d) {
      return num(d.high_km2) + " km\u00b2 is in " + (KINDS[d.kind] ? KINDS[d.kind][0].toLowerCase() : d.label.toLowerCase());
    });
    $("desig-note").textContent = touched + " of the " + D.shortlist.length + " areas touch a designated area" +
      (bits.length ? ": " + bits.join(", ") + "." : ".") +
      " A designation does not rule a place out, but it changes who has to agree and what is allowed there." +
      (land.length ? " Across the whole search area, of the land scoring " + D.high_cutoff + " or more, " + land.join(", ") + ". These overlap in places." : "");

    var a = D.score_alone, open = {}, parts = [];
    D.by_manager.forEach(function (m) { open[m.name] = m.open; });
    Object.keys(a.managers).forEach(function (name) {
      if (open[name] === false) parts.push(a.managers[name] + " on " + name.toLowerCase().replace(/ land$/, "") + " land");
    });
    var slopeW = 0;
    D.criteria.forEach(function (c) { if (c.key === "slope") slopeW = c.weight; });
    $("alone-note").textContent = "Without those checks the picture is different. Ranked by score alone, the model’s top " + a.top + " areas include " +
      (parts.length ? parts.join(" and ") + ", and " : "") + a.steep + " on slopes averaging more than " + s.max_slope_deg +
      "°. Slope carries only " + slopeW + " of the model’s 100 points, so steep ground can still score well.";

    var top = D.by_manager[0].high_km2;
    $("mgr-cap").textContent = "Land scoring " + D.high_cutoff + " or more, by who manages it: " + num(D.high_km2) + " km² in all.";
    $("mgr").innerHTML = D.by_manager.filter(function (m) { return m.high_km2 / D.high_km2 >= 0.005; }).map(function (m) {
      var t = esc(m.name) + ": " + num(m.high_km2) + " km², " + pct(m.high_km2 / D.high_km2) + " of the high-scoring land";
      return '<div class="name">' + esc(m.name) + "<small>" + (m.open ? "counted as open public land" : "not counted as open") + "</small></div>" +
        '<div class="track" tabindex="0" title="' + t + '"><div class="bar" style="width:' + (m.high_km2 / top * 78).toFixed(1) + '%"></div>' +
        '<div class="val">' + num(m.high_km2) + " km² <small>" + pct(m.high_km2 / D.high_km2) + "</small></div></div>";
    }).join("");
    $("t-mgr").innerHTML = "<caption>Land in the search area by manager</caption><thead><tr><th>Manager</th><th>Counted as open public land</th>" +
      '<th class="num">All land, km²</th><th class="num">Scoring ' + D.high_cutoff + '+, km²</th><th class="num">Share of high-scoring land</th></tr></thead><tbody>' +
      D.by_manager.map(function (m) {
        return "<tr><td>" + esc(m.name) + "</td><td>" + (m.open ? "Yes" : "No") + '</td><td class="num">' + num(m.km2) + '</td><td class="num">' +
          num(m.high_km2) + '</td><td class="num">' + (m.high_km2 / D.high_km2 * 100).toFixed(1) + "%</td></tr>";
      }).join("") + "</tbody>";
  }

  /* ---------- load ---------- */
  function loadImage(name) {
    return new Promise(function (resolve, reject) {
      var im = new Image();
      im.onload = function () { resolve(im); };
      im.onerror = function () { reject(new Error("Could not load " + name)); };
      im.src = DATA + name;
    });
  }
  function unpack(images) {
    var w = D.grid.w, h = D.grid.h, n = D.criteria.length;
    var c = document.createElement("canvas");
    c.width = w; c.height = h;
    var g = c.getContext("2d", { willReadFrequently: true });
    for (var k = 0; k < n; k++) layers.push(new Uint8Array(w * h));
    images.forEach(function (im, f) {
      g.clearRect(0, 0, w, h);
      g.drawImage(im, 0, 0);
      var px = g.getImageData(0, 0, w, h).data;
      for (var ch = 0; ch < 3; ch++) {
        var k = f * 3 + ch;
        if (k >= n) break;
        var out = layers[k];
        for (var i = 0, o = ch; i < out.length; i++, o += 4) out[i] = px[o];
      }
    });
    /* a cell counts only where every criterion has a score */
    for (var i = 0; i < w * h; i++) {
      var ok = true;
      for (k = 0; k < n; k++) if (!layers[k][i]) { ok = false; break; }
      if (!ok) layers[0][i] = 0;
    }
  }

  fetch(DATA + "model.json")
    .then(function (r) { if (!r.ok) throw new Error("Could not load the model data (HTTP " + r.status + ")"); return r.json(); })
    .then(function (d) {
      D = d;
      return Promise.all([loadImage("crit1.png"), loadImage("crit2.png"), loadImage("crit3.png")]);
    })
    .then(function (images) {
      var w = D.grid.w, h = D.grid.h, b = D.grid.bounds;
      unpack(images);
      canvas.width = w; canvas.height = h;
      ctx = canvas.getContext("2d");
      img = ctx.createImageData(w, h);
      buildLut();
      $("scale-ramp").style.background = "linear-gradient(to right," + RAMP.join(",") + ")";
      mercTop = L.Projection.SphericalMercator.project(L.latLng(b[1][0], 0)).y;
      mercBottom = L.Projection.SphericalMercator.project(L.latLng(b[0][0], 0)).y;
      rowArea = new Float64Array(h);
      for (var r = 0; r < h; r++) {
        var y = mercTop + (r + 0.5) / h * (mercBottom - mercTop);
        var lat = 2 * Math.atan(Math.exp(y / 6378137)) - Math.PI / 2;
        rowArea[r] = Math.cos(lat) * Math.cos(lat);
      }
      base = D.criteria.map(function (c) { return c.weight; });
      weights = base.slice();
      view = { kind: "combo", weights: base };
      baseShare = draw();

      initMap();
      buildSteps();
      $("wiz-jump").innerHTML = steps.map(function (s, i) { return '<option value="' + i + '">' + (i + 1) + ". " + esc(s.name) + "</option>"; }).join("");
      $("wiz-jump").addEventListener("change", function () { go(+this.value); });
      $("wiz-back").addEventListener("click", function () { go(step - 1); });
      $("wiz-next").addEventListener("click", function () { go(step + 1); });
      fillPage();
      go(0);
    })
    .catch(function (e) { fail(e.message); });
})();
