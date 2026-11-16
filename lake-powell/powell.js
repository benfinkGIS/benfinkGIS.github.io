// Lake Powell year slider: one rendered picture per year, a slider and a level
// chart that both pick the year. Plain script, no libraries.
(function () {
  "use strict";
  var BASE = "/lake-powell/";
  var el = function (id) { return document.getElementById(id); };
  var frame = el("frame"), slider = el("year"), play = el("play");
  var msg = el("sb-msg"), range = el("sb-range");
  var data, years, index = 0, timer = null, loaded = {};

  function num(v, digits) {
    return v.toLocaleString("en-US", { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 });
  }
  function day(iso) {
    var p = iso.split("-");
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+p[1] - 1] + " " + (+p[2]);
  }
  function src(y) { return BASE + "frames/" + y.year + ".jpg"; }

  function show(i) {
    index = Math.max(0, Math.min(years.length - 1, i));
    var y = years[index];
    slider.value = y.year;
    slider.setAttribute("aria-valuetext", y.year + ", " + num(y.below_full_ft) + " feet below full pool");
    frame.src = src(y);
    frame.alt = "Rendered view of the lower end of Lake Powell at its " + y.year + " average level, " +
      num(y.avg_ft) + " feet, " + num(y.below_full_ft) + " feet below full pool.";
    el("r-year").textContent = y.year + (y.complete ? "" : " (to " + day(y.last_day) + ")");
    el("r-below").textContent = y.below_full_ft < 0.5 ? "At full pool" : num(y.below_full_ft) + " ft below full pool";
    el("r-level").textContent = "Average level " + num(y.avg_ft, 1) + " ft";
    el("r-cap").textContent = num(y.pct_capacity) + "% of usable capacity, " + num(y.surface_km2 / 2.58999) + " sq mi of water";
    range.textContent = "High " + num(y.high_ft, 2) + " ft on " + day(y.high_day) + ". Low " + num(y.low_ft, 2) + " ft on " + day(y.low_day) + ".";
    mark();
    carry();
  }

  // keep the year in the address, and on the links between this page and its full-page copy
  function carry() {
    var q = index === years.length - 1 ? "" : "?year=" + years[index].year;
    try { history.replaceState(null, "", location.pathname + q); } catch (e) { /* not allowed here: the links still work */ }
    document.querySelectorAll("a[data-carry]").forEach(function (a) { a.href = a.getAttribute("data-carry") + q; });
  }
  function asked() {
    var m = /[?&]year=(\d{4})\b/.exec(location.search);
    var i = m ? +m[1] - years[0].year : -1;
    return i >= 0 && i < years.length ? i : years.length - 1;
  }

  // ---- level chart -------------------------------------------------------
  // drawn one unit to the pixel, so the lettering stays readable on a phone
  var W = 900, H = 230, L = 46, R = 128, T = 14, B = 26, Y0 = 3350, Y1 = 3720;
  var svg, cursor, dot, now, narrow = false, wired = false;
  function sx(year) { return L + (year - years[0].year) / (years[years.length - 1].year - years[0].year) * (W - L - R); }
  function sy(ft) { return T + (Y1 - ft) / (Y1 - Y0) * (H - T - B); }
  function node(name, attrs, text) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    svg.appendChild(n);
    return n;
  }
  function chart() {
    svg = el("chart-svg");
    if (!svg) return;                                           // the full-page viewer has no chart
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    W = Math.max(300, Math.round(el("chart").clientWidth - 4));
    narrow = W < 640;
    R = narrow ? 12 : 178; T = narrow ? 20 : 14; L = narrow ? 40 : 46;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    [3400, 3500, 3600].forEach(function (ft) {
      node("line", { class: "grid", x1: L, x2: W - R, y1: sy(ft), y2: sy(ft) });
    });
    [3400, 3500, 3600, 3700].forEach(function (ft) {
      node("text", { x: L - 6, y: sy(ft) + 4, "text-anchor": "end" }, num(ft));
    });
    for (var yr = 1970; yr <= years[years.length - 1].year; yr += (narrow ? 20 : 10)) {
      node("text", { x: sx(yr), y: H - 8, "text-anchor": "middle" }, yr);
    }
    var up = years.map(function (y) { return sx(y.year) + "," + sy(y.high_ft); });
    var down = years.slice().reverse().map(function (y) { return sx(y.year) + "," + sy(y.low_ft); });
    node("polygon", { class: "range", points: up.concat(down).join(" ") });
    [["Full pool", data.full_pool_ft], ["Minimum power pool", data.min_power_pool_ft], ["Dead pool", data.dead_pool_ft]]
      .forEach(function (r) {
        node("line", { class: "ref", x1: L, x2: W - R, y1: sy(r[1]), y2: sy(r[1]) });
        if (narrow) {          // no room beside the plot: sit on the line, at its right-hand end
          node("text", { x: W - R - 2, y: sy(r[1]) - 4, "text-anchor": "end" }, r[0] + ", " + num(r[1]) + " ft");
        } else {
          node("text", { x: W - R + 6, y: sy(r[1]) + 4 }, r[0] + ", " + num(r[1]) + " ft");
        }
      });
    node("polyline", { class: "avg", points: years.map(function (y) { return sx(y.year) + "," + sy(y.avg_ft); }).join(" ") });
    cursor = node("line", { class: "cursor", y1: T, y2: H - B });
    dot = node("circle", { class: "dot", r: 5 });
    now = node("text", { class: "now", "text-anchor": "middle" });
    if (wired) return;
    wired = true;
    var box = el("chart");
    function pick(ev) {
      var r = svg.getBoundingClientRect();
      var x = (ev.clientX - r.left) / r.width * W;
      var year = years[0].year + (x - L) / (W - L - R) * (years[years.length - 1].year - years[0].year);
      stop();
      show(Math.round(year) - years[0].year);
    }
    var down_ = false;
    box.addEventListener("pointerdown", function (ev) { down_ = true; box.setPointerCapture(ev.pointerId); pick(ev); });
    box.addEventListener("pointermove", function (ev) { if (down_) pick(ev); });
    box.addEventListener("pointerup", function () { down_ = false; });
    box.addEventListener("pointercancel", function () { down_ = false; });
  }
  function mark() {
    if (!cursor) return;
    var y = years[index], x = sx(y.year);
    cursor.setAttribute("x1", x); cursor.setAttribute("x2", x);
    dot.setAttribute("cx", x); dot.setAttribute("cy", sy(y.avg_ft));
    now.setAttribute("x", Math.max(L + 14, Math.min(W - R - 14, x)));
    now.setAttribute("y", narrow ? 12 : T - 3);
    now.textContent = y.year;
  }

  // ---- playing and loading ------------------------------------------------
  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    play.textContent = "Play";
    play.setAttribute("aria-pressed", "false");
  }
  function start() {
    if (index >= years.length - 1) show(0);
    play.textContent = "Pause";
    play.setAttribute("aria-pressed", "true");
    timer = setInterval(function () {
      if (index >= years.length - 1) { stop(); return; }
      if (loaded[years[index + 1].year]) show(index + 1);      // wait for the next picture rather than flash
    }, 420);
  }
  function preload() {
    var done = 0, queue = years.slice().reverse();              // newest first: that is where the page opens
    function next() {
      var y = queue.shift();
      if (!y) {
        msg.textContent = svg ? "Drag the slider, press Play, or drag across the chart." : "Drag the slider or press Play.";
        return;
      }
      var im = new Image();
      im.onload = im.onerror = function () {
        loaded[y.year] = true;
        done += 1;
        msg.textContent = "Loading pictures: " + done + " of " + years.length;
        next();
      };
      im.src = src(y);
    }
    next(); next(); next();
  }

  fetch(BASE + "data/years.json").then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (d) {
    data = d; years = d.years;
    slider.min = years[0].year; slider.max = years[years.length - 1].year; slider.step = 1;
    el("end-first").textContent = years[0].year;
    el("end-last").textContent = years[years.length - 1].year;
    chart();
    show(asked());
    preload();
    slider.addEventListener("input", function () { stop(); show(+slider.value - years[0].year); });
    play.addEventListener("click", function () { if (timer) stop(); else start(); });
    el("prev").addEventListener("click", function () { stop(); show(index - 1); });
    el("next").addEventListener("click", function () { stop(); show(index + 1); });
    el("go-full").addEventListener("click", function () { stop(); show(1983 - years[0].year); });
    el("go-now").addEventListener("click", function () { stop(); show(years.length - 1); });
    var redraw = null;
    window.addEventListener("resize", function () {
      clearTimeout(redraw);
      redraw = setTimeout(function () { chart(); mark(); }, 150);
    });
  }).catch(function (err) {
    var e = el("scene-error");
    e.hidden = false;
    e.textContent = "The pictures could not be loaded (" + err.message + ").";
    msg.textContent = "Not loaded.";
  });
})();
