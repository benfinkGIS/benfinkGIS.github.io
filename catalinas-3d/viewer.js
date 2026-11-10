// Santa Catalinas 3D viewer.
// Terrain from a height image, lit live: the sun slider moves real shadows,
// which the fragment shader finds by stepping across the height image toward the sun.
// Units are kilometres. +X is east, +Y is up, north is -Z. The block is centred on the origin.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const DATA = '/catalinas-3d/data/';
const LAT = 32.4;                 // degrees north, for the sun's path
const DEFAULT_SUN_MIN = 17 * 60 + 27;   // 5:27 pm sun time: 7 degrees up, in the west
const MESH_COLS = 1024;           // terrain mesh columns (the lighting uses the full height image)
const SLAB = 0.9;                 // km of block below the lowest ground

const $ = (id) => document.getElementById(id);
const canvasBox = $('scene');
const statusMsg = $('sb-msg');
const statusSun = $('sb-sun');
const errorBox = $('scene-error');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

function fail(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  statusMsg.textContent = 'Viewer not running';
}

const smoothstep = (a, b, x) => { const t = Math.min(Math.max((x - a) / (b - a), 0), 1); return t * t * (3 - 2 * t); };
const mix3 = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);

// ---------- sun ----------
// Position on a day near the equinox (late March or late September) at sun time `minutes`.
function sunAt(minutes) {
  const lat = LAT * Math.PI / 180;
  const hourAngle = (minutes / 60 - 12) * 15 * Math.PI / 180;
  const el = Math.asin(Math.cos(lat) * Math.cos(hourAngle));
  const az = Math.atan2(-Math.sin(hourAngle), -Math.sin(lat) * Math.cos(hourAngle));
  return { el, az: (az + 2 * Math.PI) % (2 * Math.PI) };
}

function compass(azDeg) {
  const names = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'];
  return names[Math.round(azDeg / 45) % 8];
}

function clockLabel(minutes) {
  const h = Math.floor(minutes / 60), m = Math.round(minutes % 60);
  const h12 = ((h + 11) % 12) + 1;
  return `${h12}:${String(m).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`;
}

// ---------- shaders ----------
const terrainVertex = /* glsl */`
  uniform sampler2D uHeight;
  uniform float uExag;
  varying vec2 vUv;
  void main() {
    vUv = uv;
    vec3 p = position;
    p.y = texture2D(uHeight, uv).r * uExag;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }`;

const terrainFragment = /* glsl */`
  precision highp float;
  uniform sampler2D uHeight;
  uniform sampler2D uAlbedo;
  uniform vec2 uSize;        // block size in km (east-west, north-south)
  uniform vec2 uTexel;       // one height cell in uv
  uniform float uExag;
  uniform float uTop;        // highest ground above the base, km (before exaggeration)
  uniform vec3 uSun;         // unit vector to the sun: east, up, north
  uniform vec3 uSunColor;
  uniform vec3 uSkyColor;
  varying vec2 vUv;

  float ground(vec2 uv) { return texture2D(uHeight, uv).r * uExag; }

  float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

  void main() {
    // slope from the height image
    float hl = ground(vUv - vec2(uTexel.x, 0.0)), hr = ground(vUv + vec2(uTexel.x, 0.0));
    float hs = ground(vUv - vec2(0.0, uTexel.y)), hn = ground(vUv + vec2(0.0, uTexel.y));
    vec3 n = normalize(vec3(-(hr - hl) / (2.0 * uTexel.x * uSize.x), 1.0,
                            -(hn - hs) / (2.0 * uTexel.y * uSize.y)));   // east, up, north
    float facing = max(dot(n, uSun), 0.0);

    // shadow: walk toward the sun and see whether the ground rises above the ray
    float lit = 1.0;
    if (facing > 0.0 && uSun.y > 0.0) {
      float h0 = ground(vUv) + 0.006;
      vec2 step = uSun.xz / uSize;            // uv travelled per km along the ground
      float t = 0.03 * (1.0 + hash(gl_FragCoord.xy));
      float top = uTop * uExag;
      for (int i = 0; i < 64; i++) {
        vec2 p = vUv + step * t;
        float ray = h0 + uSun.y * t;
        if (ray > top || p.x < 0.0 || p.x > 1.0 || p.y < 0.0 || p.y > 1.0) break;
        lit = min(lit, clamp((ray - ground(p)) / (t * 0.02), 0.0, 1.0));
        if (lit <= 0.0) break;
        t += max(0.02, t * 0.07);
      }
    } else {
      lit = 0.0;
    }

    vec3 albedo = texture2D(uAlbedo, vUv).rgb;
    float skyShare = 0.5 + 0.5 * n.y;
    vec3 color = albedo * (uSunColor * facing * lit + uSkyColor * skyShare);
    color = 1.0 - exp(-color * 1.35);                 // soft roll-off in the highlights
    gl_FragColor = vec4(pow(color, vec3(1.0 / 2.2)), 1.0);
  }`;

const skirtVertex = /* glsl */`
  uniform sampler2D uHeight;
  uniform float uExag;
  uniform float uBase;
  attribute float aTop;
  varying float vTop;
  void main() {
    vec3 p = position;
    p.y = mix(uBase, texture2D(uHeight, uv).r * uExag, aTop);
    vTop = aTop;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }`;

const skirtFragment = /* glsl */`
  precision highp float;
  varying float vTop;
  void main() {
    vec3 c = mix(vec3(0.085, 0.072, 0.063), vec3(0.14, 0.12, 0.105), vTop);
    gl_FragColor = vec4(c, 1.0);
  }`;

// ---------- data ----------
async function loadHeights(meta) {
  const res = await fetch(DATA + 'height.png');
  if (!res.ok) throw new Error('height.png ' + res.status);
  const bitmap = await createImageBitmap(await res.blob(),
    { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
  const cols = bitmap.width, rows = bitmap.height;
  const cv = document.createElement('canvas');
  cv.width = cols; cv.height = rows;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0);
  const px = ctx.getImageData(0, 0, cols, rows).data;
  const km = new Float32Array(cols * rows);          // row 0 = south edge
  const scale = meta.height_step_m / 1000;
  for (let r = 0; r < rows; r++) {
    const out = (rows - 1 - r) * cols;
    for (let c = 0; c < cols; c++) {
      const i = (r * cols + c) * 4;
      km[out + c] = (px[i] * 256 + px[i + 1]) * scale;
    }
  }
  return { km, cols, rows };
}

function loadTexture(url, renderer) {
  return new Promise((resolve, reject) => {
    new THREE.TextureLoader().load(url, (tex) => {
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
      tex.minFilter = THREE.LinearMipmapLinearFilter;
      resolve(tex);
    }, undefined, () => reject(new Error('could not load ' + url)));
  });
}

// ---------- scene ----------
async function main() {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  } catch (e) {
    fail('This browser could not start WebGL, which the 3D viewer needs. The still images below show the same model.');
    return;
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.setClearColor(0x0d0e10);
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', '3D model of the Santa Catalina Mountains. Drag to orbit, right-drag to pan, scroll to zoom.');
  canvasBox.prepend(canvas);

  statusMsg.textContent = 'Loading terrain and imagery (9 MB)…';
  let meta, heights, albedo;
  try {
    meta = await (await fetch(DATA + 'meta.json')).json();
    [heights, albedo] = await Promise.all([loadHeights(meta), loadTexture(DATA + 'texture_4k.jpg', renderer)]);
  } catch (e) {
    fail('The terrain files did not load (' + e.message + '). Try reloading the page.');
    return;
  }

  const W = meta.width_m / 1000, H = meta.height_m / 1000;
  const topKm = (meta.elev_max_m - meta.elev_min_m) / 1000;
  const gl = renderer.getContext();
  const floatLinear = !!gl.getExtension('OES_texture_float_linear');
  const heightTex = new THREE.DataTexture(
    floatLinear ? heights.km : Uint16Array.from(heights.km, THREE.DataUtils.toHalfFloat),
    heights.cols, heights.rows, THREE.RedFormat, floatLinear ? THREE.FloatType : THREE.HalfFloatType);
  heightTex.magFilter = heightTex.minFilter = THREE.LinearFilter;
  heightTex.wrapS = heightTex.wrapT = THREE.ClampToEdgeWrapping;
  heightTex.needsUpdate = true;

  const uniforms = {
    uHeight: { value: heightTex },
    uAlbedo: { value: albedo },
    uSize: { value: new THREE.Vector2(W, H) },
    uTexel: { value: new THREE.Vector2(1 / heights.cols, 1 / heights.rows) },
    uExag: { value: 1 },
    uTop: { value: topKm },
    uBase: { value: -SLAB },
    uSun: { value: new THREE.Vector3(0, 1, 0) },
    uSunColor: { value: new THREE.Vector3(1, 1, 1) },
    uSkyColor: { value: new THREE.Vector3(0.2, 0.25, 0.35) },
  };

  // terrain: a flat grid; the vertex shader lifts it. Height samples sit at cell centres.
  const meshCols = MESH_COLS, meshRows = Math.round(MESH_COLS * H / W);
  const pos = new Float32Array(meshCols * meshRows * 3);
  const uvs = new Float32Array(meshCols * meshRows * 2);
  const u0 = 0.5 / heights.cols, v0 = 0.5 / heights.rows;
  for (let r = 0, k = 0; r < meshRows; r++) {
    const v = v0 + (1 - 2 * v0) * r / (meshRows - 1);
    for (let c = 0; c < meshCols; c++, k++) {
      const u = u0 + (1 - 2 * u0) * c / (meshCols - 1);
      pos[k * 3] = (u - 0.5) * W; pos[k * 3 + 2] = (0.5 - v) * H;
      uvs[k * 2] = u; uvs[k * 2 + 1] = v;
    }
  }
  const index = new Uint32Array((meshCols - 1) * (meshRows - 1) * 6);
  for (let r = 0, k = 0; r < meshRows - 1; r++) {
    for (let c = 0; c < meshCols - 1; c++) {
      const a = r * meshCols + c, b = a + 1, d = a + meshCols, e = d + 1;
      index[k++] = a; index[k++] = b; index[k++] = d;
      index[k++] = b; index[k++] = e; index[k++] = d;
    }
  }
  const terrainGeo = new THREE.BufferGeometry();
  terrainGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  terrainGeo.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  terrainGeo.setIndex(new THREE.BufferAttribute(index, 1));
  const terrain = new THREE.Mesh(terrainGeo, new THREE.ShaderMaterial({
    uniforms, vertexShader: terrainVertex, fragmentShader: terrainFragment }));
  terrain.frustumCulled = false;

  // sides of the block
  const ring = [];
  const edge = (n, f) => { for (let i = 0; i < n; i++) ring.push(f(i / n)); };
  const lo = [u0, v0], hi = [1 - u0, 1 - v0];
  edge(meshCols, (t) => [lo[0] + (hi[0] - lo[0]) * t, lo[1]]);
  edge(meshRows, (t) => [hi[0], lo[1] + (hi[1] - lo[1]) * t]);
  edge(meshCols, (t) => [hi[0] - (hi[0] - lo[0]) * t, hi[1]]);
  edge(meshRows, (t) => [lo[0], hi[1] - (hi[1] - lo[1]) * t]);
  const n = ring.length;
  const sPos = new Float32Array(n * 6), sUv = new Float32Array(n * 4), sTop = new Float32Array(n * 2);
  const sIdx = new Uint32Array(n * 6);
  ring.forEach(([u, v], i) => {
    for (let k = 0; k < 2; k++) {
      const j = i * 2 + k;
      sPos[j * 3] = (u - 0.5) * W; sPos[j * 3 + 2] = (0.5 - v) * H;
      sUv[j * 2] = u; sUv[j * 2 + 1] = v;
      sTop[j] = k === 0 ? 1 : 0;
    }
    const a = i * 2, b = a + 1, c = ((i + 1) % n) * 2, d = c + 1;
    sIdx.set([a, c, b, c, d, b], i * 6);
  });
  const skirtGeo = new THREE.BufferGeometry();
  skirtGeo.setAttribute('position', new THREE.BufferAttribute(sPos, 3));
  skirtGeo.setAttribute('uv', new THREE.BufferAttribute(sUv, 2));
  skirtGeo.setAttribute('aTop', new THREE.BufferAttribute(sTop, 1));
  skirtGeo.setIndex(new THREE.BufferAttribute(sIdx, 1));
  const skirt = new THREE.Mesh(skirtGeo, new THREE.ShaderMaterial({
    uniforms, vertexShader: skirtVertex, fragmentShader: skirtFragment, side: THREE.DoubleSide }));
  skirt.frustumCulled = false;

  const scene = new THREE.Scene();
  scene.add(terrain, skirt);

  const camera = new THREE.PerspectiveCamera(24, 16 / 10, 0.05, 800);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = !reducedMotion;
  controls.dampingFactor = 0.09;
  controls.rotateSpeed = 0.6;
  controls.screenSpacePanning = false;        // pan along the ground, like a map
  controls.zoomToCursor = true;
  controls.minDistance = 1.5;
  controls.maxDistance = 240;
  controls.maxPolarAngle = THREE.MathUtils.degToRad(87);
  controls.keyPanSpeed = 14;
  controls.listenToKeyEvents(canvas);

  // camera position and look-at point, km
  const VIEWS = {
    block: { pos: [-15, 32, 65], look: [0.5, 0, 4], fit: true, say: 'Whole block from the south-west' },
    front: { pos: [-5, 2.7, 31], look: [1, 1.0, 4], say: 'Front range from above the Foothills' },
    west: { pos: [-58, 13, 20], look: [-6, 0.6, 3], say: 'Pusch Ridge from above Oro Valley' },
    top: { pos: [0, 118, 0.01], look: [0, 0, 0], fit: true, say: 'Straight down, north up' },
  };
  let flight = null;
  function goTo(name, instant = false) {
    const view = VIEWS[name];
    const toPos = new THREE.Vector3(...view.pos), toLook = new THREE.Vector3(...view.look);
    // on a tall, narrow screen step back so the whole block still fits
    if (view.fit && camera.aspect < 1.5) toPos.sub(toLook).multiplyScalar(1.5 / camera.aspect).add(toLook);
    if (reducedMotion || instant) {
      camera.position.copy(toPos); controls.target.copy(toLook); controls.update(); flight = null;
    } else {
      flight = { t0: performance.now(), fromPos: camera.position.clone(), fromLook: controls.target.clone(), toPos, toLook };
    }
    statusMsg.textContent = view.say;
    dirty = true;
  }

  // ---------- sun ----------
  function setSun(minutes) {
    const { el, az } = sunAt(minutes);
    const elDeg = el * 180 / Math.PI, azDeg = az * 180 / Math.PI;
    uniforms.uSun.value.set(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el));
    const high = smoothstep(2, 30, elDeg);
    const sun = mix3([1.0, 0.66, 0.34], [1.0, 0.95, 0.86], high)
      // dimmed toward midday, the way a camera's exposure would be set for brighter light
      .map((v) => v * 5.2 * Math.pow(smoothstep(-1.5, 10, elDeg), 0.8) * (1 - 0.6 * smoothstep(8, 50, elDeg)));
    const sky = mix3([0.30, 0.40, 0.66], [0.50, 0.62, 0.85], high)
      .map((v) => v * (0.16 + 0.12 * smoothstep(-6, 25, elDeg)));
    uniforms.uSunColor.value.set(...sun);
    uniforms.uSkyColor.value.set(...sky);
    const text = elDeg < 0.3
      ? `${clockLabel(minutes)} sun time: sun on the horizon`
      : `${clockLabel(minutes)} sun time: sun ${Math.round(elDeg)}° up, in the ${compass(azDeg)}`;
    statusSun.textContent = text;
    $('sun').setAttribute('aria-valuetext', text);
    dirty = true;
  }

  // ---------- summit labels ----------
  const labelBox = $('labels');
  const cols = heights.cols, rows = heights.rows;
  function groundAt(x, z) {        // km above the base at a point, from the height grid
    const fx = Math.min(Math.max((x / W + 0.5) * cols - 0.5, 0), cols - 1.001);
    const fy = Math.min(Math.max((0.5 - z / H) * rows - 0.5, 0), rows - 1.001);
    const c = Math.floor(fx), r = Math.floor(fy), tx = fx - c, ty = fy - r, i = r * cols + c;
    const k = heights.km;
    return (k[i] * (1 - tx) + k[i + 1] * tx) * (1 - ty) + (k[i + cols] * (1 - tx) + k[i + cols + 1] * tx) * ty;
  }
  const summits = meta.summits.map((s) => {
    const x = s.x / 1000 - W / 2, z = H / 2 - s.y / 1000;
    const el = document.createElement('span');
    el.className = 'peak';
    el.textContent = `${s.name} ${Math.round(s.elev_m * 3.28084).toLocaleString('en-US')} ft`;
    labelBox.appendChild(el);
    return { x, z, h: groundAt(x, z), el };
  });
  const tmp = new THREE.Vector3();
  function hiddenByTerrain(p) {
    const ex = uniforms.uExag.value;
    for (let i = 1; i < 60; i++) {
      const t = i / 60;
      const x = camera.position.x + (p.x - camera.position.x) * t;
      const y = camera.position.y + (p.y - camera.position.y) * t;
      const z = camera.position.z + (p.z - camera.position.z) * t;
      if (Math.abs(x) < W / 2 && Math.abs(z) < H / 2 && groundAt(x, z) * ex > y + 0.03) return true;
    }
    return false;
  }
  summits.sort((a, b) => b.h - a.h);          // highest first: they win when labels collide
  for (const s of summits) { s.w = s.el.offsetWidth + 6; s.el.hidden = true; }
  function placeLabels() {
    const show = $('tb-labels').getAttribute('aria-pressed') === 'true';
    const w = canvasBox.clientWidth, h = canvasBox.clientHeight;
    const placed = [];
    for (const s of summits) {
      tmp.set(s.x, s.h * uniforms.uExag.value + 0.05, s.z);
      const world = tmp.clone();
      tmp.project(camera);
      let visible = show && tmp.z < 1 && Math.abs(tmp.x) < 1 && Math.abs(tmp.y) < 1 && !hiddenByTerrain(world);
      const x = (tmp.x * 0.5 + 0.5) * w, y = (0.5 - tmp.y * 0.5) * h;
      if (visible && placed.some((p) => Math.abs(p.x - x) < (p.w + s.w) / 2 && Math.abs(p.y - y) < 22)) visible = false;
      s.el.hidden = !visible;
      if (visible) {
        placed.push({ x, y, w: s.w });
        s.el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -135%)`;
      }
    }
  }

  // ---------- render loop: only draws when something changed ----------
  let dirty = true;
  function resize() {
    const w = canvasBox.clientWidth, h = canvasBox.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    dirty = true;
  }
  new ResizeObserver(resize).observe(canvasBox);
  controls.addEventListener('change', () => { dirty = true; });
  controls.addEventListener('start', () => { flight = null; });

  function frame(now) {
    if (flight) {
      const t = Math.min((now - flight.t0) / 900, 1), e = t * t * (3 - 2 * t);
      camera.position.lerpVectors(flight.fromPos, flight.toPos, e);
      controls.target.lerpVectors(flight.fromLook, flight.toLook, e);
      if (t >= 1) flight = null;
      dirty = true;
    }
    // keep the point being orbited inside the block
    controls.target.x = THREE.MathUtils.clamp(controls.target.x, -W / 2, W / 2);
    controls.target.z = THREE.MathUtils.clamp(controls.target.z, -H / 2, H / 2);
    controls.target.y = THREE.MathUtils.clamp(controls.target.y, 0, topKm * uniforms.uExag.value);
    controls.update();
    if (dirty) {
      dirty = false;
      renderer.render(scene, camera);
      placeLabels();
    }
    requestAnimationFrame(frame);
  }

  // ---------- toolbar ----------
  for (const name of Object.keys(VIEWS)) $('view-' + name).addEventListener('click', () => goTo(name));
  function zoom(factor) {
    flight = null;
    const offset = camera.position.clone().sub(controls.target).multiplyScalar(factor);
    const d = THREE.MathUtils.clamp(offset.length(), controls.minDistance, controls.maxDistance);
    camera.position.copy(controls.target).add(offset.setLength(d));
    dirty = true;
  }
  $('tb-in').addEventListener('click', () => zoom(0.7));
  $('tb-out').addEventListener('click', () => zoom(1 / 0.7));
  const viewerBox = canvasBox.closest('.viewer');
  const full = $('tb-full');
  if (!viewerBox.requestFullscreen) full.hidden = true;
  full.addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen(); else viewerBox.requestFullscreen();
  });
  document.addEventListener('fullscreenchange', () => {
    full.setAttribute('aria-pressed', String(document.fullscreenElement === viewerBox));
  });
  $('tb-labels').addEventListener('click', (e) => {
    const on = e.currentTarget.getAttribute('aria-pressed') !== 'true';
    e.currentTarget.setAttribute('aria-pressed', String(on));
    dirty = true;
  });
  const sunInput = $('sun');
  sunInput.addEventListener('input', () => setSun(Number(sunInput.value)));
  $('sun-golden').addEventListener('click', () => { sunInput.value = DEFAULT_SUN_MIN; setSun(DEFAULT_SUN_MIN); });
  for (const b of document.querySelectorAll('[data-exag]')) {
    b.addEventListener('click', () => {
      uniforms.uExag.value = Number(b.dataset.exag);
      for (const o of document.querySelectorAll('[data-exag]')) o.setAttribute('aria-pressed', String(o === b));
      dirty = true;
    });
  }
  const hd = $('tb-hd');
  if (renderer.capabilities.maxTextureSize < 8192) {
    hd.disabled = true;
    hd.title = 'This device cannot show the larger image';
  }
  hd.addEventListener('click', async () => {
    if (hd.getAttribute('aria-pressed') === 'true') return;
    hd.disabled = true;
    statusMsg.textContent = 'Loading sharper imagery (17 MB)…';
    try {
      const big = await loadTexture(DATA + 'texture_8k.jpg', renderer);
      uniforms.uAlbedo.value.dispose();
      uniforms.uAlbedo.value = big;
      hd.setAttribute('aria-pressed', 'true');
      statusMsg.textContent = 'Sharper imagery loaded (about 6 m per pixel)';
    } catch (e) {
      statusMsg.textContent = 'The sharper imagery did not load';
    }
    hd.disabled = false;
    dirty = true;
  });

  resize();
  sunInput.value = DEFAULT_SUN_MIN;
  setSun(DEFAULT_SUN_MIN);
  goTo('block', true);
  statusMsg.textContent = 'Drag to orbit. Right-drag or two fingers to pan. Scroll or pinch to zoom.';
  canvasBox.classList.add('ready');
  requestAnimationFrame(frame);
}

main().catch((e) => fail('The viewer stopped with an error: ' + e.message));
