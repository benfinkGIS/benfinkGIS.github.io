/* A Beer Off The Loop: map, figures and list.
   Reads data/spots.json (written by tools/build_loop_beer.py) and the Loop's lines from the
   Tucson Loop Access project. Leaflet 1.9.4 is loaded by the page. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;          // names come from data: never innerHTML
    return e;
  }
  var plural = function (n, one, many) { return n + " " + (n === 1 ? one : many); };

  // fixed order: a kind keeps its colour whatever else is switched on
  var KINDS = [
    ["brewery", "Breweries and cideries", "Brewery or cidery"],
    ["bar", "Bars", "Bar"],
    ["beerwine", "Beer and wine bars", "Beer and wine bar"],
    ["restaurant", "Restaurants", "Restaurant"],
    ["venue", "Hotels and venues", "Hotel or venue"]
  ];
  var KIND = {};
  KINDS.forEach(function (k, i) { KIND[k[0]] = { many: k[1], one: k[2], order: i }; });
  var LIMITS = [2, 5, 10];
  var GAP_CROW_MI = 0.25, GAP_EXTRA_MI = 0.4, GAP_ROWS = 10;

  var meta, spots, loop;
  var lim = 5, on = { brewery: true, bar: true, beerwine: true, restaurant: false, venue: false };
  var picked = null;
  var map, base, labels, imagery, routeLayer, fullBounds, markers = [];

  function shown(s) { return on[s.kind] && s.min <= lim; }
  function mi(x) { return x < 0.1 ? Math.round(x * 5280 / 10) * 10 + " ft" : x.toFixed(x < 1 ? 2 : 1) + " mi"; }
  function mins(x) { return x < 1 ? "under 1 min" : x.toFixed(0) + " min"; }
  function setMsg(t) { var m = $("sb-msg"); if (m) m.textContent = t; }
  function swatch(kind, extra) {
    var s = el("span", "sw " + kind + (extra ? " " + extra : ""));
    s.style.background = "var(--k-" + kind + ")";
    return s;
  }

  // ---- settings: toolbar-style buttons; the choices ride along in the address ----
  function readQuery() {
    var q = new URLSearchParams(location.search), w = +q.get("within"), show = q.get("show");
    if (LIMITS.indexOf(w) >= 0) lim = w;
    if (show) {
      var want = show.split(",");
      KINDS.forEach(function (k) { on[k[0]] = want.indexOf(k[0]) >= 0; });
    }
  }
  function writeQuery() {
    var show = KINDS.filter(function (k) { return on[k[0]]; }).map(function (k) { return k[0]; }).join(",");
    history.replaceState(null, "", location.pathname + "?within=" + lim + "&show=" + show);
  }
  function buildSettings() {
    LIMITS.forEach(function (t) {
      var b = el("button", null, t + " min");
      b.type = "button";
      b.addEventListener("click", function () { lim = t; render(); });
      $("lim-buttons").appendChild(b);
    });
    KINDS.forEach(function (k) {
      var b = el("button");
      b.type = "button";
      b.appendChild(swatch(k[0]));
      b.appendChild(document.createTextNode(k[1]));
      b.addEventListener("click", function () { on[k[0]] = !on[k[0]]; render(); });
      $("kind-buttons").appendChild(b);
    });
  }
  function renderSettings() {
    LIMITS.forEach(function (t, i) { $("lim-buttons").children[i].setAttribute("aria-pressed", t === lim ? "true" : "false"); });
    KINDS.forEach(function (k, i) { $("kind-buttons").children[i].setAttribute("aria-pressed", on[k[0]] ? "true" : "false"); });
    writeQuery();
  }

  // ---- headline figures ----
  function renderLead(list) {
    $("hero-num").textContent = list.length;
    $("hero-lab").textContent = (list.length === 1 ? "place" : "places") + " to grab a beer within a " + lim +
      "-minute ride of the Loop (about " + (lim / 60 * meta.speed_mph).toFixed(1) + " miles)";
    var brews = spots.filter(function (s) { return s.kind === "brewery" && s.min <= lim; });
    $("brew-num").textContent = brews.length;
    $("brew-lab").textContent = (brews.length === 1 ? "brewery or cidery" : "breweries and cideries") + " within " + lim + " minutes";
    var first = spots.filter(function (s) { return s.kind === "brewery"; })[0];   // spots are sorted nearest first
    var num = $("near-num");
    num.className = "num small";
    num.textContent = first ? first.name : "none";
    $("near-lab").textContent = first ? "is the nearest brewery: " + mins(first.min) + ", " + mi(first.mi) + " off the " + first.section + " path" : "";
  }

  // ---- map ----
  function icon(s, isOn) {
    var size = s.kind === "brewery" ? 17 : 12;
    return L.divIcon({ className: "spot-mark " + s.kind + (isOn ? " on" : ""), iconSize: [size, size],
      html: '<i style="background:var(--k-' + s.kind + ')"></i>' });   // kind is one of five fixed words
  }
  function popup(s) {
    var box = el("div");
    box.appendChild(el("strong", null, s.name));
    var kl = el("div", "kindline");
    kl.appendChild(swatch(s.kind));
    kl.appendChild(document.createTextNode(KIND[s.kind].one));
    box.appendChild(kl);
    if (s.addr) box.appendChild(el("div", null, s.addr));
    var ride = el("div", "ride");
    ride.appendChild(el("b", null, mins(s.min)));
    ride.appendChild(document.createTextNode(" by bike, " + mi(s.mi) + " from the " + s.section + " path"));
    ride.appendChild(el("div", "src", mi(s.crow_mi) + " from the path in a straight line"));
    box.appendChild(ride);
    box.appendChild(el("div", "src", "Licence: " + s.lic.join(", ").toLowerCase()));
    if (s.hours) box.appendChild(el("div", "src", "Hours (OpenStreetMap): " + s.hours));
    if (/^https?:\/\//.test(s.web)) {
      var a = el("a", null, "Website");
      a.href = s.web; a.target = "_blank"; a.rel = "noopener noreferrer";
      box.appendChild(a);
    }
    return box;
  }
  function select(i, fly) {
    if (picked !== null && markers[picked]) markers[picked].setIcon(icon(spots[picked], false));
    picked = i;
    routeLayer.clearLayers();
    document.querySelectorAll("#t-spots tr.on").forEach(function (r) { r.classList.remove("on"); });
    if (i === null) return;
    var s = spots[i], line = s.route.map(function (c) { return [c[1], c[0]]; });
    if (line.length > 1) {
      L.polyline(line, { pane: "route", interactive: false, color: "#ffffff", weight: 7, opacity: 0.95 }).addTo(routeLayer);
      L.polyline(line, { pane: "route", interactive: false, color: "#000080", weight: 3, dashArray: "7 5" }).addTo(routeLayer);
    }
    L.circleMarker([s.exit[1], s.exit[0]], { pane: "route", interactive: false, radius: 5, color: "#000080", weight: 2, fillColor: "#ffffff", fillOpacity: 1 }).addTo(routeLayer);
    markers[i].setIcon(icon(s, true));
    markers[i].setZIndexOffset(5000);
    if (fly) {
      var b = L.latLngBounds(line.length > 1 ? line : [[s.lat, s.lon]]).pad(0.5);
      map.fitBounds(b, { maxZoom: 16, padding: [30, 30], animate: false });   // the popup's own pan would cut an animated zoom short
    }
    markers[i].bindPopup(popup(s), { maxWidth: 260 }).openPopup();
    var row = document.querySelector('#t-spots tr[data-i="' + i + '"]');
    if (row) row.classList.add("on");
    setMsg(s.name + ": " + mins(s.min) + ", " + mi(s.mi) + " from the " + s.section + " path");
  }
  function buildMap() {
    var mapEl = $("map");
    var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
    map = L.map(mapEl, { zoomControl: false, minZoom: 9, maxZoom: 18, zoomSnap: 0.25, scrollWheelZoom: false });
    map.on("click focus", function () { map.scrollWheelZoom.enable(); });
    mapEl.addEventListener("mouseleave", function () { map.scrollWheelZoom.disable(); });
    ["loop", "route", "labels"].forEach(function (p, i) { map.createPane(p).style.zIndex = 420 + 5 * i; });
    ["loop", "route", "labels"].forEach(function (p) { map.getPane(p).style.pointerEvents = "none"; });
    base = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 18,
      attribution: "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS user community" }).addTo(map);
    labels = L.tileLayer(ESRI + "Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 18, pane: "labels" }).addTo(map);
    imagery = L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 18, maxZoom: 18,
      attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS user community" });
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution('Places: Arizona liquor licences via City of Tucson GIS; paths &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors');
    L.control.scale({ imperial: true, metric: false }).addTo(map);

    var lines = loop.lines.map(function (ln) { return ln.map(function (c) { return [c[1], c[0]]; }); });
    L.polyline(lines, { pane: "loop", interactive: false, color: "#ffffff", weight: 6, opacity: 0.95 }).addTo(map);
    var loopLine = L.polyline(lines, { pane: "loop", interactive: false, color: "#000000", weight: 2.5 }).addTo(map);
    routeLayer = L.layerGroup().addTo(map);
    fullBounds = loopLine.getBounds();
    map.fitBounds(fullBounds, { padding: [10, 10] });

    spots.forEach(function (s, i) {
      var m = L.marker([s.lat, s.lon], { icon: icon(s, false), title: s.name + " (" + KIND[s.kind].one.toLowerCase() + ", " + mins(s.min) + ")",
        alt: s.name, riseOnHover: true, zIndexOffset: 1000 - 200 * KIND[s.kind].order });
      m.on("click", function () { select(i, false); });
      markers.push(m);
    });
    map.on("popupclose", function () { setMsg(statusText()); });

    function onClick(id, fn) { var b = $(id); if (b) b.addEventListener("click", fn); }
    onClick("tb-in", function () { map.zoomIn(); });
    onClick("tb-out", function () { map.zoomOut(); });
    onClick("tb-full", function () { map.closePopup(); select(null); map.fitBounds(fullBounds, { padding: [10, 10] }); });
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
  var lastCount = 0;
  function statusText() { return plural(lastCount, "place", "places") + " shown. Click one for the ride from the Loop."; }
  function renderMap(list) {
    spots.forEach(function (s, i) {
      var want = shown(s);
      if (want && !map.hasLayer(markers[i])) markers[i].addTo(map);
      if (!want && map.hasLayer(markers[i])) map.removeLayer(markers[i]);
    });
    if (picked !== null && !shown(spots[picked])) select(null);
    lastCount = list.length;
    if (picked === null) setMsg(statusText());
    var legend = $("map-legend");
    legend.textContent = "";
    KINDS.forEach(function (k) {
      if (!on[k[0]]) return;
      var li = el("li");
      li.appendChild(swatch(k[0], k[0] === "brewery" ? "" : "dot"));
      li.appendChild(el("span", null, k[1]));
      legend.appendChild(li);
    });
    [["line", "The Loop (draft extent)"], ["routeline", "Ride to the chosen place"]].forEach(function (x) {
      var li = el("li");
      li.appendChild(el("span", x[0]));
      li.appendChild(el("span", null, x[1]));
      legend.appendChild(li);
    });
  }

  // ---- stops by part of the Loop: bars stacked by kind ----
  function renderSections(list) {
    var host = $("sections"), by = {};
    host.textContent = "";
    list.forEach(function (s) { (by[s.section] = by[s.section] || []).push(s); });
    var names = Object.keys(by).sort(function (a, b) { return by[b].length - by[a].length || a.localeCompare(b); });
    $("sec-cap").textContent = names.length
      ? "Places within " + lim + " minutes, by the part of the Loop the ride leaves from. Pick a name to zoom the map there."
      : "Nothing to show with these settings.";
    var max = names.length ? by[names[0]].length : 1;
    names.forEach(function (name) {
      var group = by[name];
      var pick = el("button", "pick");
      pick.type = "button";
      pick.appendChild(el("span", "nm", name));
      pick.addEventListener("click", function () {
        map.closePopup(); select(null);
        map.fitBounds(L.latLngBounds(group.map(function (s) { return [s.lat, s.lon]; })).pad(0.15), { maxZoom: 15 });
        $("map").scrollIntoView({ behavior: "smooth", block: "center" });
      });
      var track = el("div", "track"), stack = el("div", "stack"), parts = [];
      stack.style.width = "calc((100% - 150px) * " + (group.length / max).toFixed(4) + ")";
      KINDS.forEach(function (k) {
        var n = group.filter(function (s) { return s.kind === k[0]; }).length;
        if (!n) return;
        var seg = el("i");
        seg.style.flex = n + " 1 0";
        seg.style.background = "var(--k-" + k[0] + ")";
        stack.appendChild(seg);
        parts.push(n + " " + (n === 1 ? k[2] : k[1]).toLowerCase());
      });
      stack.setAttribute("role", "img");
      stack.setAttribute("aria-label", name + ": " + parts.join(", "));
      stack.title = parts.join(", ");
      track.appendChild(stack);
      var val = el("span", "val", String(group.length));
      var nb = group.filter(function (s) { return s.kind === "brewery"; }).length;
      if (nb) { val.appendChild(document.createTextNode(" ")); val.appendChild(el("small", null, "(" + plural(nb, "brewery", "breweries") + ")")); }
      track.appendChild(val);
      host.appendChild(pick);
      host.appendChild(track);
    });
  }

  // ---- the list ----
  function head(table, cols) {
    table.textContent = "";
    var tr = el("tr");
    cols.forEach(function (c) { var th = el("th", c[1] || null, c[0]); th.scope = "col"; tr.appendChild(th); });
    var thead = el("thead");
    thead.appendChild(tr);
    table.appendChild(thead);
    var body = el("tbody");
    table.appendChild(body);
    return body;
  }
  function nameCell(s, i) {
    var td = el("td"), b = el("button", "linkbtn", s.name);
    b.type = "button";
    b.addEventListener("click", function () {
      if (!shown(s)) { on[s.kind] = true; if (s.min > lim) lim = LIMITS.filter(function (t) { return t >= s.min; })[0] || 10; render(); }
      select(i, true);
      $("map").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    td.appendChild(b);
    if (s.addr) td.appendChild(el("div", "src", s.addr));
    return td;
  }
  function kindCell(s) {
    var td = el("td", "kind");
    td.appendChild(swatch(s.kind));
    td.appendChild(document.createTextNode(KIND[s.kind].one));
    return td;
  }
  function renderList(list) {
    $("list-cap").textContent = list.length
      ? plural(list.length, "place", "places") + " within " + lim + " minutes. Pick a name to see it on the map."
      : "Nothing to show with these settings.";
    var body = head($("t-spots"), [["Place"], ["Kind"], ["Part of the Loop"], ["Ride", "num"], ["Distance", "num"]]);
    list.forEach(function (s) {
      var tr = el("tr");
      tr.setAttribute("data-i", s.i);
      if (s.i === picked) tr.className = "on";
      tr.appendChild(nameCell(s, s.i));
      tr.appendChild(kindCell(s));
      tr.appendChild(el("td", null, s.section));
      tr.appendChild(el("td", "num", mins(s.min)));
      tr.appendChild(el("td", "num", mi(s.mi)));
      body.appendChild(tr);
    });
  }

  // ---- close in a straight line, a long way round by bike ----
  function renderGaps() {
    var rows = spots.filter(function (s) { return on[s.kind] && s.crow_mi <= GAP_CROW_MI && s.mi - s.crow_mi >= GAP_EXTRA_MI; })
      .sort(function (a, b) { return (b.mi - b.crow_mi) - (a.mi - a.crow_mi); }).slice(0, GAP_ROWS);
    var table = $("t-gaps");
    $("gap-cap").textContent = rows.length
      ? "Places of the kinds switched on that sit within a quarter mile of the path in a straight line, but at least " +
        GAP_EXTRA_MI + " miles farther by the streets. Longest detour first."
      : "No place of the kinds switched on is close to the path and a long way round.";
    if (!rows.length) { table.textContent = ""; return; }
    var body = head(table, [["Place"], ["Kind"], ["Straight line", "num"], ["By bike", "num"], ["Ride", "num"]]);
    rows.forEach(function (s) {
      var tr = el("tr");
      tr.appendChild(nameCell(s, s.i));
      tr.appendChild(kindCell(s));
      tr.appendChild(el("td", "num", mi(s.crow_mi)));
      tr.appendChild(el("td", "num", mi(s.mi)));
      tr.appendChild(el("td", "num", mins(s.min)));
      body.appendChild(tr);
    });
  }

  function render() {
    var list = spots.filter(shown);
    renderSettings();
    renderLead(list);
    renderMap(list);
    renderSections(list);
    renderList(list);
    renderGaps();
  }

  function fill() {
    var moved = (meta.moved || []).length;
    var values = { licences: meta.licences_downloaded, mph: meta.speed_mph, moved: plural(moved, "place", "places") };
    document.querySelectorAll("[data-fill]").forEach(function (n) {
      var v = values[n.getAttribute("data-fill")];
      if (v != null) n.textContent = v;
    });
  }

  function fail(msg) {
    var e = $("map-error");
    if (e) { e.textContent = msg; e.hidden = false; }
    setMsg("Could not load the data.");
  }
  function getJSON(url) {
    return fetch(url).then(function (r) { if (!r.ok) throw new Error(url + ": " + r.status); return r.json(); });
  }

  if (typeof L === "undefined") { fail("The map library did not load, so the map and list cannot be shown."); return; }
  Promise.all([getJSON("/tucson-loop-beer/data/spots.json"), getJSON("/tucson-loop-access/data/loop.json")]).then(function (res) {
    meta = res[0].meta;
    spots = res[0].spots;
    spots.forEach(function (s, i) { s.i = i; });
    loop = res[1];
    readQuery();
    fill();
    buildSettings();
    buildMap();
    render();
  }).catch(function (err) {
    fail("The data for this page did not load. Try again later.");
    if (window.console) console.error(err);
  });
})();
