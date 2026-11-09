/* Tucson Golf Course Water Map: course footprints on satellite imagery.
   Leaflet 1.9.4 (loaded in index.html). Boundaries come from data/courses.geojson,
   built by tools/build_courses.py from OpenStreetMap. */
(function () {
  "use strict";

  var mapEl = document.getElementById("map");
  if (!mapEl || typeof L === "undefined") return;

  var statusMsg = document.getElementById("sb-msg");
  var statusPos = document.getElementById("sb-pos");
  var tableBody = document.getElementById("course-rows");
  var countEls = document.querySelectorAll("[data-course-count]");
  var READY = "Ready";

  var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  var map = L.map(mapEl, {
    zoomControl: false,        // the retro toolbar buttons below do this
    minZoom: 8,
    maxZoom: 20,
    zoomSnap: 0.5,
    scrollWheelZoom: false,    // switched on by clicking the map, so the page can still scroll
    center: [32.2226, -110.9747],
    zoom: 10
  });
  map.on("click focus", function () { map.scrollWheelZoom.enable(); });
  mapEl.addEventListener("mouseleave", function () { map.scrollWheelZoom.disable(); });

  L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxNativeZoom: 19,
    maxZoom: 20,
    attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community"
  }).addTo(map);

  // Roads and place names on top of the imagery, switched by the Labels button.
  var labels = L.layerGroup([
    L.tileLayer(ESRI + "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 19, maxZoom: 20 }),
    L.tileLayer(ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 19, maxZoom: 20 })
  ]).addTo(map);

  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('Course boundaries &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors');

  var STYLE = { color: "#ffe600", weight: 2, opacity: 0.95, fillColor: "#ffe600", fillOpacity: 0.14 };
  var HOVER = { weight: 3, fillOpacity: 0.32 };
  var layers = [];            // one entry per course, in file order
  var courses;                // L.geoJSON layer
  var fullBounds;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : ""; }
  function acresText(n) { return n.toLocaleString("en-US") + " acres"; }

  function popupHtml(p) {
    var rows = [];
    rows.push("<strong>" + esc(p.name) + "</strong>");
    var facts = [acresText(p.acres) + " mapped"];
    if (p.holes) facts.push(esc(p.holes) + " holes");
    if (p.access) facts.push(esc(p.access.charAt(0).toUpperCase() + p.access.slice(1)));
    rows.push(facts.join(" &bull; "));
    var links = [];
    if (safeUrl(p.website)) links.push('<a href="' + esc(safeUrl(p.website)) + '" target="_blank" rel="noopener">Website</a>');
    if (safeUrl(p.osm)) links.push('<a href="' + esc(safeUrl(p.osm)) + '" target="_blank" rel="noopener">OpenStreetMap</a>');
    if (links.length) rows.push(links.join(" &bull; "));
    if (p.note) rows.push("<em>Note: " + esc(p.note) + "</em>");
    return rows.join("<br>");
  }

  function setMsg(t) { if (statusMsg) statusMsg.textContent = t || READY; }

  function selectCourse(i) {
    var layer = layers[i];
    if (!layer) return;
    map.fitBounds(layer.getBounds(), { maxZoom: 17, padding: [30, 30] });
    layer.openPopup();
    mapEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function buildTable(features) {
    if (!tableBody) return;
    var html = features.map(function (f, i) {
      var p = f.properties;
      return "<tr><td><button type=\"button\" class=\"linkbtn\" data-i=\"" + i + "\">" + esc(p.name) + "</button>" +
        (p.note ? " <span class=\"flag\" title=\"" + esc(p.note) + "\">(outline incomplete)</span>" : "") + "</td>" +
        "<td class=\"num\">" + p.acres.toLocaleString("en-US") + "</td>" +
        "<td>" + (p.holes ? esc(p.holes) : "&ndash;") + "</td>" +
        "<td>" + (p.access ? esc(p.access) : "&ndash;") + "</td></tr>";
    }).join("");
    tableBody.innerHTML = html;
    tableBody.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-i]");
      if (b) selectCourse(+b.getAttribute("data-i"));
    });
  }

  function fail(msg) {
    setMsg(msg);
    var box = document.getElementById("map-error");
    if (box) { box.textContent = msg; box.hidden = false; }
  }

  fetch("/tucson-golf-water/data/courses.geojson")
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (data) {
      var features = data.features;
      courses = L.geoJSON(data, {
        style: function () { return STYLE; },
        onEachFeature: function (f, layer) {
          layers.push(layer);
          layer.bindPopup(popupHtml(f.properties), { maxWidth: 260 });
          layer.bindTooltip(esc(f.properties.name), { sticky: true, className: "course-tip", direction: "top" });
          layer.on("mouseover", function () { layer.setStyle(HOVER); setMsg(f.properties.name); });
          layer.on("mouseout", function () { courses.resetStyle(layer); setMsg(READY); });
        }
      }).addTo(map);
      fullBounds = courses.getBounds();
      map.fitBounds(fullBounds, { padding: [20, 20] });
      buildTable(features);
      countEls.forEach(function (el) { el.textContent = features.length; });
      setMsg(READY);
    })
    .catch(function () { fail("Could not load the course boundaries. Try reloading the page."); });

  // ---- retro toolbar ----
  function on(id, fn) { var el = document.getElementById(id); if (el) el.addEventListener("click", fn); }
  on("tb-in", function () { map.zoomIn(); });
  on("tb-out", function () { map.zoomOut(); });
  on("tb-full", function () { if (fullBounds) map.fitBounds(fullBounds, { padding: [20, 20] }); });
  var labelBtn = document.getElementById("tb-labels");
  if (labelBtn) labelBtn.addEventListener("click", function () {
    var show = labelBtn.getAttribute("aria-pressed") !== "true";
    labelBtn.setAttribute("aria-pressed", show ? "true" : "false");
    if (show) labels.addTo(map); else map.removeLayer(labels);
  });

  // ---- status bar coordinates ----
  function fmt(latlng) {
    return Math.abs(latlng.lat).toFixed(4) + "° " + (latlng.lat >= 0 ? "N" : "S") + ", " +
           Math.abs(latlng.lng).toFixed(4) + "° " + (latlng.lng >= 0 ? "E" : "W");
  }
  if (statusPos) {
    map.on("mousemove", function (e) { statusPos.textContent = fmt(e.latlng); });
    map.on("mouseout", function () { statusPos.textContent = fmt(map.getCenter()); });
  }
})();
