// Neighborhood Canopy 3D viewer.
// A 400 m block of each neighborhood built from the lidar: ground and buildings as one
// surface with the aerial photo on it, today's canopy as the lidar canopy surface, and the
// proposed trees at mature size. The sun slider moves real shadows through 15 July.
// Reads data/3d/ (written by tools/canopy/24_web3d_export.py). Units are metres.
// +X is east, +Y is up, north is -Z. The block is centred on the origin.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const DATA = '/tucson-canopy/data/3d/';
const SITES = [['dunbar_spring', 'Dunbar Spring'], ['western_hills_ii', 'Western Hills']];
const PLANTS = ['Today', 'Street trees', 'Streets and homes', 'Full build-out'];
const DAY_OF_YEAR = 196;            // 15 July
const DEFAULT_MINUTES = 16 * 60;    // 4 p.m., the hour the shade figures use
const BASE_Y = -5;                  // underside of the block
const BACKDROP = 0xe7e6e0;
const TODAY_GREEN = [0x1f3d16, 0x33592a];

const $ = (id) => document.getElementById(id);
const box = $('scene3d');
const statusMsg = $('sb3-msg');
const statusSun = $('sb3-sun');
const errorBox = $('scene3d-error');
const FULL = document.body.classList.contains('fullmap');

function fail(message) {
  if (errorBox) { errorBox.textContent = message; errorBox.hidden = false; }
  if (statusMsg) statusMsg.textContent = 'Viewer not running';
}

// ---------- sun: NOAA's general solar position equations ----------
function sunAt(minutes, lat, lon) {
  const g = 2 * Math.PI / 365 * (DAY_OF_YEAR - 1 + (minutes / 60 - 12) / 24);
  const eqtime = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g)
    - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
  const decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g)
    + 0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
  const solarMinutes = minutes + eqtime + 4 * lon + 7 * 60;        // Mountain Standard Time is UTC-7
  const ha = (solarMinutes / 4 - 180) * Math.PI / 180;
  const la = lat * Math.PI / 180;
  const el = Math.asin(Math.sin(la) * Math.sin(decl) + Math.cos(la) * Math.cos(decl) * Math.cos(ha));
  const az = Math.atan2(Math.sin(ha), Math.cos(ha) * Math.sin(la) - Math.tan(decl) * Math.cos(la)) + Math.PI;
  return { el, az: (az + 2 * Math.PI) % (2 * Math.PI) };
}
function compass(deg) {
  return ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'][Math.round(deg / 45) % 8];
}
function clock(minutes) {
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return ((h + 11) % 12 + 1) + ':' + String(m).padStart(2, '0') + (h < 12 ? ' a.m.' : ' p.m.');
}

// ---------- state, shared with the page's own settings when they are there ----------
const state = { site: 'western_hills_ii', plant: 1, minutes: DEFAULT_MINUTES };
(function readQuery() {
  const q = new URLSearchParams(location.search);
  if (SITES.some((s) => s[0] === q.get('site'))) state.site = q.get('site');
  const p = parseInt(q.get('plant'), 10);
  if (p >= 0 && p <= 3) state.plant = p;
  const t = parseInt(q.get('time'), 10);
  if (t >= 360 && t <= 1140) state.minutes = t;
})();
function writeQuery() {
  const query = '?site=' + state.site + '&plant=' + state.plant + '&time=' + state.minutes;
  if (FULL) history.replaceState(null, '', location.pathname + query);
  document.querySelectorAll('a[data-carry3d]').forEach((a) => { a.href = a.getAttribute('data-carry3d') + query; });
  document.querySelectorAll('a[data-carryback]').forEach((a) => {
    a.href = a.getAttribute('data-carryback') + '?site=' + state.site + '&plant=' + Math.max(state.plant, 1) + '&show=canopy';
  });
}

// ---------- loading ----------
const cache = {};
async function pixels(url) {
  const blob = await (await fetch(url)).blob();
  const bmp = await createImageBitmap(blob, { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
  const c = document.createElement('canvas');
  c.width = bmp.width; c.height = bmp.height;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bmp, 0, 0);
  return ctx.getImageData(0, 0, bmp.width, bmp.height);
}
async function loadSite(id) {
  if (cache[id]) return cache[id];
  const meta = await (await fetch(DATA + id + '.json')).json();
  const img = await pixels(DATA + id + '_heights.png');
  const n = meta.cells, ground = new Float32Array(n * n), canopy = new Float32Array(n * n);
  for (let i = 0; i < n * n; i++) {
    ground[i] = (img.data[i * 4] * 256 + img.data[i * 4 + 1]) / 100;
    canopy[i] = img.data[i * 4 + 2] / 10;
  }
  const photo = await new THREE.TextureLoader().loadAsync(DATA + id + '_photo.jpg');
  photo.colorSpace = THREE.SRGBColorSpace;
  photo.anisotropy = 8;
  cache[id] = { meta, ground, canopy, photo };
  return cache[id];
}

// ---------- geometry ----------
// A surface over the block from a height per cell. Row 0 of the data is the north edge.
function surface(n, cell, heightAt, keepQuad) {
  const pos = new Float32Array(n * n * 3), uv = new Float32Array(n * n * 2), half = n * cell / 2;
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const i = r * n + c;
      pos[i * 3] = (c + 0.5) * cell - half;
      pos[i * 3 + 1] = heightAt(i);
      pos[i * 3 + 2] = (r + 0.5) * cell - half;
      uv[i * 2] = (c + 0.5) / n;
      uv[i * 2 + 1] = 1 - (r + 0.5) / n;
    }
  }
  const idx = [];
  for (let r = 0; r < n - 1; r++) {
    for (let c = 0; c < n - 1; c++) {
      const a = r * n + c, b = a + 1, d = a + n, e = d + 1;
      if (keepQuad && !keepQuad(a, b, d, e)) continue;
      idx.push(a, d, b, b, d, e);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  geo.setIndex(new THREE.BufferAttribute(new Uint32Array(idx), 1));
  geo.computeVertexNormals();
  return geo;
}
function thin(arr, n, step, pick) {            // every `step`th cell, for small screens
  if (step === 1) return { a: arr, n };
  const m = Math.floor(n / step), out = new Float32Array(m * m);
  for (let r = 0; r < m; r++) {
    for (let c = 0; c < m; c++) {
      let v = pick === 'max' ? 0 : arr[r * step * n + c * step];
      if (pick === 'max') for (let y = 0; y < step; y++) for (let x = 0; x < step; x++) v = Math.max(v, arr[(r * step + y) * n + c * step + x]);
      out[r * m + c] = v;
    }
  }
  return { a: out, n: m };
}
function blur(a, n) {
  const out = new Float32Array(a.length);
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      let s = 0, k = 0;
      for (let y = Math.max(r - 1, 0); y <= Math.min(r + 1, n - 1); y++) {
        for (let x = Math.max(c - 1, 0); x <= Math.min(c + 1, n - 1); x++) { s += a[y * n + x]; k++; }
      }
      out[r * n + c] = s / k;
    }
  }
  return out;
}
// Sides of the block, from the edge of the ground down to its underside
function skirt(ground, n, cell) {
  const half = n * cell / 2, ring = [];
  for (let c = 0; c < n; c++) ring.push([0, c]);
  for (let r = 1; r < n; r++) ring.push([r, n - 1]);
  for (let c = n - 2; c >= 0; c--) ring.push([n - 1, c]);
  for (let r = n - 2; r > 0; r--) ring.push([r, 0]);
  const pos = new Float32Array(ring.length * 6), idx = [];
  ring.forEach(([r, c], i) => {
    const x = (c + 0.5) * cell - half, z = (r + 0.5) * cell - half;
    pos.set([x, ground[r * n + c], z, x, BASE_Y, z], i * 6);
    const j = (i + 1) % ring.length;
    idx.push(i * 2, j * 2, i * 2 + 1, j * 2, j * 2 + 1, i * 2 + 1);
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  return geo;
}
function crownGeometry(seed) {             // a lumpy ball, one per species
  const geo = new THREE.IcosahedronGeometry(1, 2), p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
    const lump = 1 + 0.10 * Math.sin(4.1 * x + seed) * Math.sin(3.7 * z + 1.3) + 0.06 * Math.sin(7.3 * y + 2 * seed);
    p.setXYZ(i, x * lump, y * lump, z * lump);
  }
  geo.computeVertexNormals();
  return geo;
}

// ---------- scene ----------
let renderer, scene, camera, controls, sun, sky, group = null, current = null, dirty = true;
const treeMeshes = [];           // [{ tier, mesh }]

function groundMaterial(photo) {
  const mat = new THREE.MeshLambertMaterial({ map: photo });
  // Walls are steep faces with the roof's pixels smeared down them: paint them plain,
  // and lift the photo a little so its own shadows do not fight the live ones.
  mat.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying float vUp;')
      .replace('#include <defaultnormal_vertex>', '#include <defaultnormal_vertex>\nvUp = normalize(mat3(modelMatrix) * objectNormal).y;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying float vUp;')
      .replace('#include <map_fragment>', '#include <map_fragment>\n' +
        'diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.34, 0.26, 0.19), 0.22);\n' +
        'diffuseColor.rgb = mix(vec3(0.57, 0.48, 0.37), diffuseColor.rgb, smoothstep(0.35, 0.62, vUp));');
  };
  return mat;
}
function buildSite(data) {
  if (group) {
    scene.remove(group);
    group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
  }
  treeMeshes.length = 0;
  group = new THREE.Group();
  const meta = data.meta;
  const step = (matchMedia('(max-width: 700px)').matches || (navigator.deviceMemory && navigator.deviceMemory <= 4)) ? 2 : 1;
  const cell = meta.cell_m * step;
  const g = thin(data.ground, meta.cells, step, 'first'), k = thin(data.canopy, meta.cells, step, 'max'), n = g.n;

  const land = new THREE.Mesh(surface(n, cell, (i) => g.a[i]), groundMaterial(data.photo));
  land.receiveShadow = true; land.castShadow = true;
  group.add(land);
  const side = new THREE.Mesh(skirt(g.a, n, cell), new THREE.MeshLambertMaterial({ color: 0x6b5847 }));
  group.add(side);

  // today's canopy: the lidar canopy surface, dropped below ground where there is none
  const smooth = blur(blur(k.a, n), n);
  const has = (i) => k.a[i] > 0;
  const crowns = surface(n, cell, (i) => has(i) ? g.a[i] + Math.max(smooth[i], 1.2) : g.a[i] - 1.5,
    (a, b, d, e) => has(a) || has(b) || has(d) || has(e));
  const colours = new Float32Array(crowns.attributes.position.count * 3);
  const dark = new THREE.Color(TODAY_GREEN[0]), light = new THREE.Color(TODAY_GREEN[1]), tmp = new THREE.Color();
  for (let i = 0; i < colours.length / 3; i++) {
    const x = crowns.attributes.position.getX(i), z = crowns.attributes.position.getZ(i);
    tmp.copy(dark).lerp(light, 0.5 + 0.5 * Math.sin(x * 0.31) * Math.cos(z * 0.27));
    colours.set([tmp.r, tmp.g, tmp.b], i * 3);
  }
  crowns.setAttribute('color', new THREE.BufferAttribute(colours, 3));
  const canopy = new THREE.Mesh(crowns, new THREE.MeshLambertMaterial({ vertexColors: true }));
  canopy.castShadow = true; canopy.receiveShadow = true;
  group.add(canopy);

  // proposed trees: one instanced crown and trunk per species and scenario
  const base = meta.crown_base_m, bark = new THREE.MeshLambertMaterial({ color: 0x4a3526 });
  const trunkGeo = new THREE.CylinderGeometry(0.12, 0.17, 1, 6);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
  let rand = 7;
  const random = () => { rand = (rand * 16807) % 2147483647; return rand / 2147483647; };
  meta.species.forEach((sp, s) => {
    const geo = crownGeometry(s), mat = new THREE.MeshLambertMaterial({ color: sp.colour });
    const half = (sp.height - base) / 2;
    for (let tier = 1; tier <= 3; tier++) {
      const mine = meta.trees.filter((t) => t[3] === s && t[4] === tier);
      if (!mine.length) continue;
      const crown = new THREE.InstancedMesh(geo, mat, mine.length);
      const trunk = new THREE.InstancedMesh(trunkGeo, bark, mine.length);
      mine.forEach((t, i) => {
        const j = 0.92 + 0.14 * random(), x = t[0], z = -t[1], y = t[2];
        q.setFromAxisAngle(up, random() * Math.PI * 2);
        m4.compose(new THREE.Vector3(x, y + base + half, z), q, new THREE.Vector3(sp.radius * j, half * j, sp.radius * j));
        crown.setMatrixAt(i, m4);
        const h = base + half * 0.7;
        m4.compose(new THREE.Vector3(x, y + h / 2, z), q, new THREE.Vector3(1, h, 1));
        trunk.setMatrixAt(i, m4);
      });
      crown.castShadow = true; crown.receiveShadow = true; trunk.castShadow = true;
      group.add(crown, trunk);
      treeMeshes.push({ tier, mesh: crown }, { tier, mesh: trunk });
    }
  });
  scene.add(group);
}
function applyPlant() {
  treeMeshes.forEach((t) => { t.mesh.visible = t.tier <= state.plant; });
  dirty = true;
}
function applySun() {
  const meta = current.meta, s = sunAt(state.minutes, meta.lonlat[1], meta.lonlat[0]);
  const el = Math.max(s.el, 0.02), dir = new THREE.Vector3(Math.sin(s.az) * Math.cos(el), Math.sin(el), -Math.cos(s.az) * Math.cos(el));
  sun.position.copy(dir).multiplyScalar(900);
  const up = Math.min(Math.max(s.el / 0.35, 0), 1);       // fades in over the first 20 degrees
  sun.intensity = 3.1 * up;
  sun.color.setHSL(0.09, 0.55 * (1 - up) + 0.12, 0.5 + 0.4 * up);
  sky.intensity = 0.4 + 0.45 * up;
  const deg = s.el * 180 / Math.PI, azDeg = s.az * 180 / Math.PI;
  if (statusSun) statusSun.textContent = deg < 0.5 ? 'Sun below the horizon' : 'Sun ' + Math.round(deg) + '° up, in the ' + compass(azDeg);
  if ($('sun3d-label')) $('sun3d-label').textContent = clock(state.minutes);
  dirty = true;
}
function describe() {
  const meta = current.meta, n = meta.trees.filter((t) => t[4] <= state.plant).length;
  statusMsg.textContent = meta.name + ': ' + (state.plant
    ? PLANTS[state.plant].toLowerCase() + ', ' + n.toLocaleString('en-US') + ' proposed trees in this block'
    : 'today, a ' + meta.size_m + ' m block');
  const press = (id, on) => { Array.prototype.forEach.call($(id).children, (b, i) => b.setAttribute('aria-pressed', i === on ? 'true' : 'false')); };
  press('site3d-buttons', SITES.findIndex((s) => s[0] === state.site));
  press('plant3d-buttons', state.plant);
  writeQuery();
}
function homeView(top) {
  // stand further back in a narrow window so the whole block stays in view
  const S = current.meta.size_m * Math.max(1, 1.5 / camera.aspect);
  if (top) camera.position.set(0, 1.55 * S, 0.01);
  else camera.position.set(-0.22 * S, 0.74 * S, 1.16 * S);
  controls.target.set(0, 0, 0);
  controls.update();
  dirty = true;
}
async function show(siteChanged) {
  try {
    statusMsg.textContent = 'Loading…';
    const data = await loadSite(state.site);
    if (siteChanged || current !== data) { current = data; buildSite(data); homeView(false); }
    applyPlant();
    applySun();
    describe();
  } catch (e) {
    fail('The 3D block did not load (' + e.message + '). Try reloading the page.');
  }
}

function start() {
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  } catch (e) {
    fail('This browser could not start WebGL, which the 3D viewer needs. The still images below show the same scenes.');
    return;
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.NeutralToneMapping;
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', '3D view of a block of the neighborhood. Drag to orbit, scroll to zoom, arrow keys to pan.');
  box.appendChild(canvas);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(BACKDROP);
  camera = new THREE.PerspectiveCamera(38, 1, 2, 6000);
  sky = new THREE.HemisphereLight(0xdfe8f2, 0x8f8272, 1.2);
  scene.add(sky);
  sun = new THREE.DirectionalLight(0xfff1dc, 2.6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(4096, 4096);
  Object.assign(sun.shadow.camera, { left: -340, right: 340, top: 340, bottom: -340, near: 100, far: 1800 });
  sun.shadow.camera.updateProjectionMatrix();      // or the shadow box stays at its 10 m default
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.6;
  scene.add(sun, sun.target);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(8000, 8000), new THREE.MeshLambertMaterial({ color: BACKDROP }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = BASE_Y;
  floor.receiveShadow = true;
  scene.add(floor);

  controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.maxPolarAngle = Math.PI * 0.47;
  controls.minDistance = 30;
  controls.maxDistance = 1500;
  controls.screenSpacePanning = false;
  controls.listenToKeyEvents(canvas);
  controls.addEventListener('change', () => { dirty = true; });

  function resize() {
    const w = box.clientWidth, h = box.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    dirty = true;
  }
  new ResizeObserver(resize).observe(box);
  resize();
  (function frame() {
    controls.update();
    if (dirty && current) { renderer.render(scene, camera); dirty = false; }
    requestAnimationFrame(frame);
  })();

  // controls in the window
  function button(parent, label, fn) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.addEventListener('click', fn);
    $(parent).appendChild(b);
  }
  SITES.forEach((s) => button('site3d-buttons', s[1], () => { if (state.site !== s[0]) { state.site = s[0]; show(true); } }));
  PLANTS.forEach((p, i) => button('plant3d-buttons', p, () => { state.plant = i; show(false); }));
  $('tb3-home').addEventListener('click', () => homeView(false));
  $('tb3-top').addEventListener('click', () => homeView(true));
  $('tb3-in').addEventListener('click', () => { camera.position.sub(controls.target).multiplyScalar(0.75).add(controls.target); dirty = true; });
  $('tb3-out').addEventListener('click', () => { camera.position.sub(controls.target).multiplyScalar(1.33).add(controls.target); dirty = true; });
  const slider = $('sun3d');
  slider.value = String(state.minutes);
  slider.addEventListener('input', () => { state.minutes = Number(slider.value); if (current) { applySun(); writeQuery(); } });
  // follow the page's own settings when they change
  document.addEventListener('canopy:state', (e) => {
    const d = e.detail, siteChanged = d.site !== state.site;
    if (!siteChanged && d.plant === state.plant) return;
    state.site = d.site;
    state.plant = d.plant;
    show(siteChanged);
  });
  show(true);
}

if (!box) {
  // no viewer on this page
} else if (FULL || !('IntersectionObserver' in window)) {
  start();
} else {
  // on the project page, wait until the viewer is near the screen before loading anything
  statusMsg.textContent = 'The 3D block loads when you scroll here.';
  const io = new IntersectionObserver((entries) => {
    if (entries.some((en) => en.isIntersecting)) { io.disconnect(); start(); }
  }, { rootMargin: '300px' });
  io.observe(box);
  writeQuery();
}
