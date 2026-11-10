/* Loop draft review map. Layers come from the GeoJSON files next to this page,
   written by tools/build_loop.py from OpenStreetMap. A working tool, not a site page. */
(function () {
  "use strict";
  if (typeof L === "undefined") return;

  var TIERS = [
    ["route_loop", "OSM route “The Loop”", "#3ddc57"],
    ["route_cdo", "OSM route “Cañada del Oro”", "#4da3ff"],
    ["named", "Named Loop section, in no route", "#ff9d2e"],
    ["santa_cruz_south", "Unnamed, Santa Cruz south (guess)", "#ff4b4b"],
    ["gap_fill", "Unnamed gap-filler (guess)", "#ff4df0"]
  ];
  var POINTS = [
    ["road", "Connects to a street", "#ffe600", 6, true],
    ["service", "Connects to a service road or lot", "#ffb45e", 5, true],
    ["path", "Connects to another path or sidewalk", "#6fe8ff", 4, false],
    ["on_street", "Side street along an on-street section", "#bdbdbd", 4, false],
    ["other", "Connects to something else", "#ffffff", 4, false],
    ["separated", "Under/overpass: crosses, no connection", "#ff3b3b", 6, true],
    ["untagged", "Crosses a road with no bridge tag: check", "#ff00ff", 8, true]
  ];
  var TIER_COLOR = {}, POINT_STYLE = {};
  TIERS.forEach(function (t) { TIER_COLOR[t[0]] = t[2]; });
  POINTS.forEach(function (p) { POINT_STYLE[p[0]] = p; });

  var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  var start = parseHash() || { z: 11, lat: 32.26, lng: -110.99 };
  var map = L.map("map", { center: [start.lat, start.lng], zoom: start.z, minZoom: 9, maxZoom: 20, preferCanvas: true, zoomControl: false });
  L.control.zoom({ position: "bottomright" }).addTo(map);      // the legend takes the top edge on narrow screens
  L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxNativeZoom: 19, maxZoom: 20,
    attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community"
  }).addTo(map);
  var labels = L.layerGroup([
    L.tileLayer(ESRI + "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 19, maxZoom: 20 }),
    L.tileLayer(ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 19, maxZoom: 20 })
  ]).addTo(map);
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('Paths &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors');
  L.control.scale({ imperial: true, metric: false }).addTo(map);

  var groups = { labels: labels, others: L.layerGroup() };   // name -> layer, toggled by the checkboxes
  var dots = [];                                             // every point marker, resized with zoom
  function dotScale() { var z = map.getZoom(); return z < 12 ? 0.45 : z < 14 ? 0.7 : 1; }
  map.on("zoomend", function () {
    var s = dotScale();
    dots.forEach(function (m) { m.setRadius(m.baseRadius * s); });
  });
  var msg = document.getElementById("msg"), pos = document.getElementById("pos");

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function osm(type, id) {
    return '<a href="https://www.openstreetmap.org/' + type + "/" + encodeURIComponent(id) + '" target="_blank" rel="noopener">OpenStreetMap ' + type + " " + esc(id) + "</a>";
  }
  function parseHash() {
    var m = /^#(\d+(?:\.\d+)?)\/(-?\d+\.\d+)\/(-?\d+\.\d+)$/.exec(location.hash);
    return m ? { z: +m[1], lat: +m[2], lng: +m[3] } : null;
  }
  function fail(text) {
    var e = document.getElementById("err");
    e.textContent = text; e.hidden = false; msg.textContent = "Error";
  }
  function getJSON(name) {
    return fetch(name).then(function (r) { if (!r.ok) throw new Error(name + ": HTTP " + r.status); return r.json(); });
  }
  function row(host, key, swatch, text, count, checked) {
    var lab = document.createElement("label");
    lab.className = "row";
    lab.innerHTML = '<input type="checkbox" data-layer="' + esc(key) + '"' + (checked ? " checked" : "") + ">" + swatch +
      esc(text) + '<span class="n">' + esc(count) + "</span>";
    host.appendChild(lab);
  }

  // Census blocks coloured by baseline ride time (tools/build_network.py). Drawn first so the Loop stays on top.
  var BANDS = [
    [5, "5 min or less", "#ffffb2"], [10, "5 to 10 min", "#fecc5c"], [20, "10 to 20 min", "#fd8d3c"],
    [30, "20 to 30 min", "#f03b20"], [Infinity, "Over 30 min", "#bd0026"]
  ];
  function addBlocks(blocks) {
    var host = document.getElementById("blocks"), meta = blocks.metadata || {};
    host.innerHTML = "";
    function popup(p) {
      var bits = ["<strong>Census block " + esc(p.geoid) + "</strong>",
        p.pop.toLocaleString("en-US") + " residents &bull; " + p.hu.toLocaleString("en-US") + " housing units",
        "Baseline: " + p.min.toFixed(1) + " min to the Loop",
        "Attached to a street " + p.snap_m.toLocaleString("en-US") + " m from the block's centre point"];
      if (p.private) bits.push("<em>Attached to a private street: the trip starts there and joins the public streets at a gate.</em>");
      if (p.island) bits.push("<em>The nearest street cannot reach the Loop in the network, so a farther one was used.</em>");
      return bits.join("<br>");
    }
    function dot(color, ring) {
      return function (f, ll) {
        var m = L.circleMarker(ll, ring ? { radius: 6 * dotScale(), color: ring, weight: 2, fill: false }
                                        : { radius: 3 * dotScale(), stroke: false, fillColor: color, fillOpacity: 0.9 });
        m.baseRadius = ring ? 6 : 3;
        dots.push(m);
        return m;
      };
    }
    var lower = -Infinity;
    BANDS.forEach(function (b, i) {
      var lo = lower; lower = b[0];
      var feats = blocks.features.filter(function (f) { return f.properties.min > lo && f.properties.min <= b[0]; });
      var people = feats.reduce(function (s, f) { return s + f.properties.pop; }, 0);
      groups["band" + i] = L.geoJSON(feats, { pointToLayer: dot(b[2]), onEachFeature: function (f, l) { l.bindPopup(popup(f.properties)); } }).addTo(map);
      row(host, "band" + i, '<i class="dot plain" style="background:' + b[2] + '"></i>', b[1], people.toLocaleString("en-US"), true);
    });
    var flagged = blocks.features.filter(function (f) { return f.properties.island || f.properties.snap_m > 300; });
    groups.flagged = L.geoJSON(flagged, { pointToLayer: dot(null, "#ffffff"), onEachFeature: function (f, l) { l.bindPopup(popup(f.properties)); } });
    row(host, "flagged", '<i class="dot ring"></i>', "Check: poorly attached blocks", flagged.length, false);
    var gated = blocks.features.filter(function (f) { return f.properties.private; });
    groups.gated = L.geoJSON(gated, { pointToLayer: dot(null, "#6fe8ff"), onEachFeature: function (f, l) { l.bindPopup(popup(f.properties)); } });
    row(host, "gated", '<i class="dot ring" style="border-color:#6fe8ff"></i>', "Blocks on private streets", gated.length, false);
    var ten = meta.baseline_ride_time_to_loop && meta.baseline_ride_time_to_loop.within_10_min, res = meta.residents || {};
    var note = document.createElement("p");
    note.className = "note";
    note.textContent = "Counts are residents (2020 Census), one dot per block." +
      (ten ? " Baseline: " + (ten.share_of_study_area * 100).toFixed(0) + "% of the " + res.population_study_area.toLocaleString("en-US") +
        " residents in the study area are within 10 minutes. No traffic weighting yet, so treat this as a network check." : "");
    host.appendChild(note);
  }

  Promise.all([getJSON("loop_draft.geojson"), getJSON("points.geojson"), getJSON("other_paths.geojson"),
               getJSON("blocks.geojson").catch(function () { return null; })])
    .then(function (res) {
      var loop = res[0], pts = res[1], others = res[2], meta = loop.metadata || {};
      if (res[3]) addBlocks(res[3]);

      // ---- Loop lines, one toggle per tier ----
      var tiersEl = document.getElementById("tiers");
      TIERS.forEach(function (t) {
        var feats = loop.features.filter(function (f) { return f.properties.tier === t[0]; });
        var layer = L.geoJSON(feats, {
          style: { color: t[2], weight: 4, opacity: 0.95 },
          onEachFeature: function (f, l) {
            var p = f.properties, bits = ["<strong>" + esc(p.name || "(unnamed)") + "</strong>", esc(t[1])];
            bits.push(esc(p.highway) + (p.surface ? ", " + esc(p.surface) : "") + (p.bridge ? ", bridge" : "") + (p.tunnel ? ", tunnel" : "") +
              " &bull; " + p.miles.toFixed(2) + " mi");
            bits.push(osm("way", p.way));
            l.bindPopup(bits.join("<br>"));
          }
        });
        groups[t[0]] = layer.addTo(map);
        var m = (meta.tiers && meta.tiers[t[0]]) || { miles: 0 };
        row(tiersEl, t[0], '<i class="sw" style="border-color:' + t[2] + '"></i>', t[1], m.miles.toFixed(1) + " mi", true);
      });
      document.getElementById("total").textContent = meta.miles_total;

      // ---- points: connections and grade-separated crossings ----
      var pointsEl = document.getElementById("points");
      POINTS.forEach(function (pt) {
        var feats = pts.features.filter(function (f) { return f.properties.kind === pt[0]; });
        if (!feats.length && pt[0] !== "separated") return;
        var layer = L.geoJSON(feats, {
          pointToLayer: function (f, ll) {
            var m = L.circleMarker(ll, { radius: pt[3] * dotScale(), color: "#000", weight: 1, fillColor: pt[2], fillOpacity: 1 });
            m.baseRadius = pt[3];
            dots.push(m);
            return m;
          },
          onEachFeature: function (f, l) {
            var p = f.properties, bits = ["<strong>" + esc(pt[1]) + "</strong>"];
            if (p.names && p.names.length) bits.push(esc(p.names.join(", ")));
            if (p.types) bits.push("Touches: " + esc(p.types.join(", ")));
            if (p.how) bits.push(esc(p.how.join(", ")));
            if (p.node) bits.push(osm("node", p.node));
            l.bindPopup(bits.join("<br>"));
          }
        });
        groups[pt[0]] = layer;
        if (pt[4]) layer.addTo(map);
        row(pointsEl, pt[0], '<i class="dot" style="background:' + pt[2] + '"></i>', pt[1], feats.length, pt[4]);
      });

      // ---- context: other paved bike paths, off by default ----
      L.geoJSON(others, {
        style: { color: "#ffffff", weight: 2, opacity: 0.9, dashArray: "5 5" },
        onEachFeature: function (f, l) {
          var p = f.properties;
          l.bindPopup("<strong>" + esc(p.name || "(unnamed bike path)") + "</strong><br>Not in the draft &bull; " + p.miles.toFixed(2) + " mi<br>" + osm("way", p.way));
        }
      }).addTo(groups.others);
      document.getElementById("n-others").textContent = others.features.length;

      document.getElementById("built").textContent = "Data pulled " + (meta.generated || "?") + ". © OpenStreetMap contributors.";
      if (!parseHash()) {
        var wide = map.getSize().x > 700;                     // leave room for the legend on wide screens
        map.fitBounds(L.geoJSON(loop).getBounds(), { paddingTopLeft: [wide ? 310 : 20, 20], paddingBottomRight: [20, 20] });
      }
      msg.textContent = "Ready";
    })
    .catch(function (e) { fail("Could not load the layers (" + e.message + "). Run: py tools/build_loop.py"); });

  // ---- layer checkboxes ----
  document.getElementById("panel").addEventListener("change", function (ev) {
    var key = ev.target.getAttribute && ev.target.getAttribute("data-layer"), layer = key && groups[key];
    if (!layer) return;
    if (ev.target.checked) layer.addTo(map); else map.removeLayer(layer);
    // keep the drawing order: residents at the bottom, then the Loop, then the connection dots
    TIERS.map(function (t) { return t[0]; }).concat(Object.keys(POINT_STYLE)).forEach(function (k) {
      if (groups[k] && map.hasLayer(groups[k])) groups[k].bringToFront();
    });
  });
  if (window.innerWidth < 700) document.getElementById("panel").classList.add("min");   // narrow pane: start with the legend rolled up
  document.getElementById("min").addEventListener("click", function () {
    document.getElementById("panel").classList.toggle("min");
  });

  // ---- status bar and shareable position ----
  function fmt(ll) { return ll.lat.toFixed(5) + ", " + ll.lng.toFixed(5); }
  map.on("mousemove", function (e) { pos.textContent = fmt(e.latlng); });
  map.on("moveend", function () {
    var c = map.getCenter();
    history.replaceState(null, "", "#" + map.getZoom() + "/" + c.lat.toFixed(5) + "/" + c.lng.toFixed(5));
  });
  window.addEventListener("hashchange", function () {
    var h = parseHash();
    if (h) map.setView([h.lat, h.lng], h.z);
  });
})();
