/* ============================================================
   Access-Twin — 3D walkthrough.

   Renders the generated civic building and drives four mobility
   agents along the routes the Python analysis actually produced.
   Nothing here decides who can go where; it animates a verdict.

   World axes: building x -> three.js x, building y -> three.js z,
   elevation -> three.js y. Every conversion goes through v3().
   ============================================================ */

const D = window.__SCENE__;

/* ---------- palette, read from CSS so themes drive the 3D too ---------- */
let TOK = {};
function tokens() {
  const cs = getComputedStyle(document.documentElement);
  const g = n => cs.getPropertyValue(n).trim();
  const dark = (document.documentElement.getAttribute("data-theme")
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  TOK = {
    dark,
    bg: g("--stage-bg"), fog: g("--stage-fog"),
    floor: g("--m-floor"), wall: g("--m-wall"), glass: g("--m-glass"),
    ramp: g("--m-ramp"), concrete: g("--m-concrete"), timber: g("--m-timber"),
    fabric: g("--m-fabric"), porcelain: g("--m-porcelain"),
    steel: g("--m-steel"), soffit: g("--m-soffit"),
    gallery: g("--m-gallery"), parapet: g("--m-parapet"),
    ok: g("--ok"), bad: g("--bad"), warn: g("--warn"), accent: g("--accent"),
    ink: g("--ink")
  };
  D.profiles.forEach(p => p.c = dark ? p.color.dark : p.color.light);
}
tokens();

const v3 = (x, y, z) => new THREE.Vector3(x, z, y);   // world -> scene

/* ---------- renderer ---------- */
const stage = document.getElementById("stage");
const el0 = id => document.getElementById(id);

/* A projector or a locked-down laptop that cannot do WebGL would
   otherwise show a black rectangle and nothing else. Fail to the text
   findings, which carry every number the 3D view does. */
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  if (!renderer.getContext()) throw new Error("no context");
} catch (err) {
  if (el0("boot")) el0("boot").hidden = true;

/* A first-time viewer lands on a panel of numbers with no idea what
   building this is or why it is being audited. One card, two doors. */
(function intro() {
  const box = el0("intro");
  if (!box || wantsWalk) return;
  box.hidden = false;
  playing = false;
  const close = walk => {
    box.hidden = true;
    if (walk) { setInspect(false); playing = true; goto(0); }
    else { playing = false; }
  };
  el0("introaudit").addEventListener("click", () => close(false));
  el0("introwalk").addEventListener("click", () => close(true));
  box.addEventListener("click", e => { if (e.target === box) close(false); });
  addEventListener("keydown", function esc(e) {
    if (e.key === "Escape" && !box.hidden) { close(false); }
  });
  el0("introaudit").focus();
})();
  if (el0("nogl")) el0("nogl").hidden = false;
  const det = el0("findings");
  if (det) det.open = true;
  console.error("WebGL unavailable", err);
  return;
}
/* On a 4K projector a full-resolution buffer with 4096 shadows will
   crawl. Start conservative and step down further if frames are slow. */
let pixelCap = Math.min(2, devicePixelRatio || 1);
renderer.setPixelRatio(pixelCap);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.08;
renderer.outputColorSpace = THREE.SRGBColorSpace;
stage.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 400);

const [BW, BH, BZ] = D.size;
const CTR = v3(BW / 2, BH / 2, 0);

function applyEnv() {
  scene.background = new THREE.Color(TOK.bg);
  scene.fog = new THREE.Fog(TOK.fog, 34, 96);
}
applyEnv();

/* ---------- lighting ---------- */
const hemi = new THREE.HemisphereLight(0xffffff, 0x404852, 0.30);
scene.add(hemi);
const key = new THREE.DirectionalLight(0xfff4e6, 2.5);
key.position.set(18, 26, -6);
key.castShadow = true;
key.shadow.mapSize.set(devicePixelRatio > 1.5 ? 2048 : 4096,
                      devicePixelRatio > 1.5 ? 2048 : 4096);
key.shadow.camera.near = 1;
key.shadow.camera.far = 90;
const SH = 26;
Object.assign(key.shadow.camera, { left: -SH, right: SH, top: SH, bottom: -SH });
key.shadow.bias = -0.0009;
key.shadow.normalBias = 0.02;
key.target.position.copy(CTR);
scene.add(key, key.target);
const fill = new THREE.DirectionalLight(0xbcd0e0, 0.25);
fill.position.set(-14, 12, 20);
scene.add(fill);

/* ---------- materials ---------- */
const MAT = {};
let SURF = null, ENV = null;
function buildMaterials() {
  if (!SURF) {
    SURF = {
      tile: makeSurface(THREE, "tile", 6),
      concrete: makeSurface(THREE, "concrete", 5),
      plaster: makeSurface(THREE, "plaster", 4),
      wood: makeSurface(THREE, "wood", 3),
      fabric: makeSurface(THREE, "fabric", 6)
    };
  }
  if (ENV) ENV.dispose();
  ENV = makeEnvironment(THREE, renderer, TOK.dark);
  scene.environment = ENV;

  // Maps are shared, but each material clones its own repeat so a 12 m
  // floor and a 0.4 m table top do not show the same tile size.
  const tex = (kit, rep) => {
    if (!kit) return {};
    const map = kit.map.clone(), normalMap = kit.normalMap.clone();
    map.needsUpdate = normalMap.needsUpdate = true;
    [map, normalMap].forEach(t => {
      t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.repeat.set(rep, rep);
    });
    map.colorSpace = THREE.SRGBColorSpace;
    return { map, normalMap, normalScale: new THREE.Vector2(0.55, 0.55) };
  };
  const mk = (col, rough, metal, kit, rep, extra) =>
    new THREE.MeshStandardMaterial(Object.assign(
      { color: new THREE.Color(col), roughness: rough, metalness: metal || 0,
        envMapIntensity: TOK.dark ? 0.8 : 1.0 },
      tex(kit, rep || 4), extra || {}));

  MAT.wall      = mk(TOK.wall, 0.95, 0, SURF.plaster, 7);
  MAT.floor     = mk(TOK.floor, 0.70, 0, SURF.tile, 10);
  MAT.gallery   = mk(TOK.gallery, 0.66, 0, SURF.tile, 5);
  MAT.ramp      = mk(TOK.ramp, 0.80, 0, SURF.concrete, 4);
  MAT.concrete  = mk(TOK.concrete, 0.90, 0, SURF.concrete, 4);
  MAT.timber    = mk(TOK.timber, 0.60, 0, SURF.wood, 2);
  MAT.fabric    = mk(TOK.fabric, 0.98, 0, SURF.fabric, 3);
  MAT.porcelain = mk(TOK.porcelain, 0.14, 0.02);
  MAT.steel     = mk(TOK.steel, 0.26, 0.88);
  MAT.soffit    = mk(TOK.soffit, 0.92, 0, SURF.plaster, 5);
  MAT.parapet   = mk(TOK.parapet, 0.92, 0, SURF.plaster, 4);
  MAT.header    = mk(TOK.wall, 0.95, 0, SURF.plaster, 4);
  MAT.glass     = mk(TOK.glass, 0.06, 0.10, null, 1, {
    transparent: true, opacity: 0.16, side: THREE.DoubleSide });

  // Floor finishes get their own material so carpet actually reads as
  // carpet in the ordinary render, not only under the material overlay.
  // Deep pile takes a stronger normal and a rougher surface, which is
  // most of what separates it visually from the low-pile next to it.
  (D.surfaces || []).forEach(sf => {
    const kit = sf.name.startsWith("carpet") ? SURF.fabric
      : sf.name === "timber" ? SURF.wood
      : sf.name === "tile" ? SURF.tile : SURF.concrete;
    const deep = sf.name === "carpet_deep";
    const m = mk(sf.color, deep ? 1.0 : sf.name.startsWith("carpet") ? 0.95
                 : 0.72, 0, kit, deep ? 26 : 14);
    if (m.normalScale) m.normalScale.set(deep ? 1.5 : 0.7, deep ? 1.5 : 0.7);
    m.envMapIntensity = deep ? 0.25 : (TOK.dark ? 0.8 : 1.0);
    m.dithering = true;
    MAT["surf_" + sf.name] = m;
  });
}
buildMaterials();

/* ---------- building geometry ---------- */
const building = new THREE.Group();
scene.add(building);

function rampGeometry(w, d, h0, h1, axis) {
  /* A wedge: a box whose top face rises along one axis. Built by hand
     rather than by shearing a BoxGeometry so the side faces stay
     planar and the normals come out right for shading. */
  const g = new THREE.BufferGeometry();
  const x0 = -w / 2, x1 = w / 2, z0 = -d / 2, z1 = d / 2;
  const t = (u) => axis === "x" ? u : u;   // top height chooser below
  const hAt = (xi, zi) => axis === "x"
    ? (xi === 0 ? h0 : h1)
    : (zi === 0 ? h0 : h1);
  const P = [
    [x0, 0, z0], [x1, 0, z0], [x1, 0, z1], [x0, 0, z1],          // base 0..3
    [x0, hAt(0, 0), z0], [x1, hAt(1, 0), z0],
    [x1, hAt(1, 1), z1], [x0, hAt(0, 1), z1]                      // top 4..7
  ];
  const F = [
    [4, 5, 6], [4, 6, 7],       // top
    [0, 2, 1], [0, 3, 2],       // bottom
    [0, 1, 5], [0, 5, 4],       // -z
    [1, 2, 6], [1, 6, 5],       // +x
    [2, 3, 7], [2, 7, 6],       // +z
    [3, 0, 4], [3, 4, 7]        // -x
  ];
  const pos = [];
  F.forEach(f => f.forEach(i => pos.push(...P[i])));
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.computeVertexNormals();
  return g;
}

const SOLID_MESHES = [];

/* Identical furniture is drawn once.
   84 auditorium seats and 37 cafe chairs were each assembled from five
   or six little boxes, giving 1,059 draw calls to put 36,000 triangles
   on screen -- about 34 triangles per call, which is entirely
   submission-bound. Anything repeated enough times is built once as a
   prototype and drawn as an InstancedMesh, so 84 seats cost five calls
   instead of four hundred, in the shadow pass as well as the main one. */
const INSTANCE_MIN = 6;

function instanceFurniture() {
  const groups = new Map();
  D.solids.forEach(s => {
    if (s.kind !== "furniture" && s.kind !== "fixture") return;
    const w = +(s.x1 - s.x0).toFixed(3), d = +(s.y1 - s.y0).toFixed(3),
          h = +(s.z1 - s.z0).toFixed(3);
    const key = `${s.tag}|${w}|${d}|${h}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  });

  const handled = new Set();
  groups.forEach(list => {
    if (list.length < INSTANCE_MIN) return;
    const proto = makeFurniture(THREE, list[0], MAT);
    if (!proto) return;
    proto.updateMatrixWorld(true);
    const parts = [];
    proto.traverse(o => { if (o.isMesh) parts.push(o); });
    if (!parts.length) return;

    parts.forEach(part => {
      const im = new THREE.InstancedMesh(part.geometry, part.material,
                                         list.length);
      const bulk = (list[0].x1 - list[0].x0) * (list[0].z1 - list[0].z0);
      im.castShadow = bulk > 0.25;
      im.receiveShadow = true;
      const m = new THREE.Matrix4(), t = new THREE.Matrix4();
      list.forEach((s, i) => {
        const w = s.x1 - s.x0, d = s.y1 - s.y0;
        const p = v3(s.x0 + w / 2, s.y0 + d / 2, s.z0);
        t.makeTranslation(p.x, p.y, p.z);
        m.multiplyMatrices(t, part.matrix);
        im.setMatrixAt(i, m);
      });
      im.instanceMatrix.needsUpdate = true;
      im.frustumCulled = false;   // one bounding sphere for a whole room
      building.add(im);
    });
    list.forEach(s => handled.add(s));
  });
  return handled;
}

function buildSolids() {
  const instanced = instanceFurniture();
  D.solids.forEach(s => {
    if (instanced.has(s)) return;
    const w = s.x1 - s.x0, d = s.y1 - s.y0, h = s.z1 - s.z0;
    if (w <= 0 || d <= 0 || h <= 0) return;
    // Only slabs take a finish material: a ramp with a concrete surface
    // is still a ramp and keeps its own colour.
    const mat = (s.kind === "slab" && s.surface && MAT["surf_" + s.surface])
      || MAT[s.material] || MAT.wall;
    let mesh;
    const furn = (s.kind === "furniture" || s.kind === "fixture")
      ? makeFurniture(THREE, s, MAT) : null;
    if (furn) {
      // Assembled at the solid's own dimensions, so what the camera sees
      // occupies exactly the footprint the analysis eroded around.
      furn.position.copy(v3(s.x0 + w / 2, s.y0 + d / 2, s.z0));
      if (Math.max(w, d) * h <= 0.25) {
        furn.traverse(o => { if (o.isMesh) o.castShadow = false; });
      }
      furn.userData.solid = s;
      building.add(furn);
      SOLID_MESHES.push(furn);
      return;
    }
    if (s.kind === "ramp") {
      mesh = new THREE.Mesh(rampGeometry(w, d, s.rz0, s.rz1, s.axis), mat);
      mesh.position.copy(v3(s.x0 + w / 2, s.y0 + d / 2, s.z0));
    } else {
      mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      mesh.position.copy(v3(s.x0 + w / 2, s.y0 + d / 2, s.z0 + h / 2));
      // Finish slabs are laid flush with the slab beneath, so their top
      // faces are exactly coplanar and the depth buffer cannot choose
      // between them -- the shimmer that appears the moment the camera
      // moves. polygonOffset does not help here because the slab below
      // carries a finish material too and takes the same offset.
      //
      // Lift the finish 4 mm in the scene graph only. The analysis reads
      // the solids, never these meshes, so the voxelisation and every
      // number derived from it are untouched.
      if (s.tag === "finish") mesh.position.y += 0.004;
    }
    // A chair leg casts a shadow nobody can see at demo distance and
    // costs a full pass through the shadow map. Only things big enough
    // to read cast.
    const bulk = Math.max(w, d) * h;
    mesh.castShadow = s.kind !== "slab" && bulk > 0.25;
    mesh.receiveShadow = true;
    mesh.userData.solid = s;
    building.add(mesh);
    SOLID_MESHES.push(mesh);
  });
}
buildSolids();

/* Walls are cut down during the walkthrough so the camera can see in.
   Full height for the establishing shot, knee height for everything
   after -- a doll's-house section, which is how architects present
   plans anyway. */
let wallCut = 1.0;
function setWallCut(f) {
  wallCut = f;
  SOLID_MESHES.forEach(m => {
    const s = m.userData.solid;
    if (s.kind !== "wall" || s.tag === "column") return;
    const h = s.z1 - s.z0;
    const keep = Math.max(0.06, f);
    m.scale.y = keep;
    m.position.y = s.z0 + (h * keep) / 2;
  });
}

/* ---------- reachability decal ---------- */
const GX = D.grid.nx, GY = D.grid.ny, CELL = D.grid.cell;
function unpack(b64, n) {
  const bin = atob(b64), p = new Uint8Array(bin.length), out = new Uint8Array(n);
  for (let i = 0; i < bin.length; i++) p[i] = bin.charCodeAt(i);
  for (let i = 0; i < n; i++) out[i] = (p[i >> 3] >> (7 - (i & 7))) & 1;
  return out;
}
D.profiles.forEach(p => {
  p.reach = unpack(p.reach_grid, GX * GY);
  p.afterReach = unpack(p.after_reach_grid, GX * GY);
});

const decalTex = (() => {
  const data = new Uint8Array(GX * GY * 4);
  const t = new THREE.DataTexture(data, GX, GY, THREE.RGBAFormat);
  t.needsUpdate = true;
  t.flipY = false;
  return t;
})();

function paintDecal(mode, profile, after) {
  const d = decalTex.image.data;
  const hex = c => new THREE.Color(c);
  const ramp = [TOK.bad, TOK.bad, TOK.warn, "#8C9B45", TOK.ok].map(hex);
  const pc = profile ? hex(profile.c) : hex(TOK.accent);
  for (let x = 0; x < GX; x++) {
    for (let y = 0; y < GY; y++) {
      const i = x * GY + y, o = (y * GX + x) * 4;
      let col = null, a = 0;
      if (mode === "profile" && profile) {
        const m = after ? profile.afterReach : profile.reach;
        if (m[i]) { col = pc; a = 150; }
      } else if (mode === "heat") {
        let n = 0;
        for (const p of D.profiles) n += (after ? p.afterReach : p.reach)[i];
        if (n > 0) { col = ramp[n]; a = 165; }
      }
      if (col) {
        d[o] = col.r * 255; d[o + 1] = col.g * 255; d[o + 2] = col.b * 255;
        d[o + 3] = a;
      } else { d[o + 3] = 0; }
    }
  }
  decalTex.needsUpdate = true;
}

const decalMat = new THREE.MeshBasicMaterial({
  map: decalTex, transparent: true, depthWrite: false,
  polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4
});
const decalGroup = new THREE.Group();
// Two planes: ground level, and the raised gallery, so the tint sits on
// whichever floor is actually there.
[[0.012, 0, 0, BW, BH], [0.612, 31.0, 17.2, 12.6, 12.4]].forEach(
  ([z, x0, y0, w, h], k) => {
    const g = new THREE.PlaneGeometry(w, h);
    const uv = g.attributes.uv;
    for (let i = 0; i < uv.count; i++) {
      uv.setXY(i, (x0 + uv.getX(i) * w) / BW, (y0 + uv.getY(i) * h) / BH);
    }
    uv.needsUpdate = true;
    const m = new THREE.Mesh(g, decalMat);
    m.rotation.x = -Math.PI / 2;
    m.position.copy(v3(x0 + w / 2, y0 + h / 2, z));
    m.renderOrder = 2 + k;
    decalGroup.add(m);
  });
scene.add(decalGroup);
decalGroup.visible = false;

/* ---------- room labels ---------- */
const roomLabels = new THREE.Group();
scene.add(roomLabels);
function buildRoomLabels() {
  while (roomLabels.children.length) roomLabels.children.pop();
  D.rooms.forEach(r => {
    const c = document.createElement("canvas");
    const g = c.getContext("2d");
    const fs = 40;
    g.font = `600 ${fs}px ui-monospace, Menlo, monospace`;
    c.width = Math.ceil(g.measureText(r.name.toUpperCase()).width) + 24;
    c.height = fs + 20;
    const g2 = c.getContext("2d");
    g2.font = `600 ${fs}px ui-monospace, Menlo, monospace`;
    g2.fillStyle = TOK.dark ? "rgba(228,236,241,0.62)" : "rgba(16,24,29,0.55)";
    g2.fillText(r.name.toUpperCase(), 12, fs + 4);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, transparent: true, depthTest: false, opacity: 0.9 }));
    sp.scale.set(c.width / 190, c.height / 190, 1);
    sp.position.copy(v3((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, r.z + 2.05));
    sp.renderOrder = 900;
    roomLabels.add(sp);
  });
}
buildRoomLabels();

/* ---------- route ribbon ---------- */
/* The route is drawn as a tube carrying a scrolling dash texture, so the
   line reads as direction of travel rather than as a static stripe. The
   tube follows the voxelised floor, which is why it climbs the ramp. */
const dashTex = (() => {
  const c = document.createElement("canvas");
  c.width = 64; c.height = 8;
  const g = c.getContext("2d");
  g.fillStyle = "rgba(255,255,255,0)"; g.fillRect(0, 0, 64, 8);
  g.fillStyle = "#fff"; g.fillRect(0, 0, 38, 8);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = THREE.RepeatWrapping; t.wrapT = THREE.ClampToEdgeWrapping;
  return t;
})();

const routeGroup = new THREE.Group();
scene.add(routeGroup);
let routeMat = null;

function clearRoute() {
  while (routeGroup.children.length) {
    const m = routeGroup.children.pop();
    m.geometry.dispose();
  }
  routeMat = null;
}

function drawRoute(path, color, arrived) {
  clearRoute();
  if (!path || path.length < 2) return;
  const pts = path.map(p => v3(p[0], p[1], p[2] + 0.06));
  const curve = new THREE.CatmullRomCurve3(pts, false, "centripetal", 0.4);
  const L = curve.getLength();
  const geo = new THREE.TubeGeometry(curve, Math.max(24, (L * 4) | 0), 0.05, 8, false);
  const tex = dashTex.clone();
  tex.needsUpdate = true;
  tex.repeat.set(Math.max(2, L / 0.55), 1);
  routeMat = new THREE.MeshBasicMaterial({
    color: new THREE.Color(color), map: tex, transparent: true,
    opacity: 0.92, depthWrite: false });
  const mesh = new THREE.Mesh(geo, routeMat);
  mesh.renderOrder = 5;
  routeGroup.add(mesh);

  // Where a route fails, the last metre turns red -- the eye lands on
  // the point of failure without needing the caption.
  if (!arrived && L > 1.2) {
    const tail = new THREE.CatmullRomCurve3(
      curve.getPoints(80).slice(-14), false, "centripetal", 0.4);
    const tg = new THREE.TubeGeometry(tail, 24, 0.075, 8, false);
    const tm = new THREE.MeshBasicMaterial({
      color: new THREE.Color(TOK.bad), transparent: true, opacity: 0.95,
      depthWrite: false });
    const tmesh = new THREE.Mesh(tg, tm);
    tmesh.renderOrder = 6;
    routeGroup.add(tmesh);
  }
}

/* ---------- floor material overlay ---------- */
/* ADA 302 is a material rule, so the material has to be visible. Each
   finish is painted in its own colour and named, because "deep-pile
   carpet" is a thing a client recognises and "22 mm" is not. */
const SURFDEFS = D.surfaces || [];   // NB: SURF is the texture kit
const SG = D.surface_grid;
const surfTex = (() => {
  if (!SG) return null;
  const bin = atob(SG.data), raw = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) raw[i] = bin.charCodeAt(i);
  const data = new Uint8Array(SG.nx * SG.ny * 4);
  const t = new THREE.DataTexture(data, SG.nx, SG.ny, THREE.RGBAFormat);
  t.flipY = false;
  t.raw = raw;
  return t;
})();

function paintSurfaces(alpha) {
  if (!surfTex) return;
  const d = surfTex.image.data, raw = surfTex.raw;
  const cols = SURFDEFS.map(s => new THREE.Color(s.color));
  for (let x = 0; x < SG.nx; x++) {
    for (let y = 0; y < SG.ny; y++) {
      const i = x * SG.ny + y, o = (y * SG.nx + x) * 4;
      const c = cols[raw[i]] || cols[0];
      d[o] = c.r * 255; d[o + 1] = c.g * 255; d[o + 2] = c.b * 255;
      d[o + 3] = alpha * 255;
    }
  }
  surfTex.needsUpdate = true;
}

const surfMat = surfTex ? new THREE.MeshBasicMaterial({
  map: surfTex, transparent: true, depthWrite: false,
  polygonOffset: true, polygonOffsetFactor: -5, polygonOffsetUnits: -5 }) : null;
const surfGroup = new THREE.Group();
scene.add(surfGroup);
if (surfMat) {
  [[0.016, 0, 0, BW, BH], [0.616, 31.0, 17.2, 12.6, 12.4]].forEach(
    ([z, x0, y0, w, h], k) => {
      const g = new THREE.PlaneGeometry(w, h);
      const uv = g.attributes.uv;
      for (let i = 0; i < uv.count; i++) {
        uv.setXY(i, (x0 + uv.getX(i) * w) / BW,
                 (y0 + (1 - uv.getY(i)) * h) / BH);
      }
      uv.needsUpdate = true;
      const m = new THREE.Mesh(g, surfMat);
      m.rotation.x = -Math.PI / 2;
      m.position.copy(v3(x0 + w / 2, y0 + h / 2, z));
      m.renderOrder = 4 + k;
      surfGroup.add(m);
    });
}
surfGroup.visible = false;

function surfaceLegend() {
  // Only the finishes actually present, each with who it stops.
  const present = new Set();
  if (surfTex) surfTex.raw.forEach(v => present.add(v));
  const rows = SURFDEFS.map((sf, i) => ({ sf, i }))
    .filter(r => present.has(r.i))
    .map(({ sf }) => {
      // Straight from the exported data, which the nav grid derived from
      // the same predicate. Recomputing it here is how it went wrong.
      const stops = (sf.blocks || []).map(n => (P[n] && P[n].label) || n);
      return `<span><i style="background:${sf.color}"></i>${sf.label}` +
        (stops.length ? `<b>stops ${stops.join(", ")}</b>` : "") + `</span>`;
    });
  el("roomstate").innerHTML = rows.join("");
}

/* ---------- room state overlays ---------- */
/* One translucent pad per room, recoloured live as the body widens.
   Named rooms switching off one at a time reads from the back of a
   room in a way a pixel mask never does. */
const roomPads = {};
const roomGroup = new THREE.Group();
scene.add(roomGroup);
D.rooms.forEach(r => {
  const w = r.x1 - r.x0, d = r.y1 - r.y0;
  const m = new THREE.Mesh(
    new THREE.PlaneGeometry(w, d),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true,
                                  opacity: 0.0, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  m.position.copy(v3(r.x0 + w / 2, r.y0 + d / 2, r.z + 0.03));
  m.renderOrder = 3;
  roomGroup.add(m);
  roomPads[r.name] = m;
});
roomGroup.visible = false;

const SWEEP = D.width_sweep || [];
let widthIdx = 0;
function applyWidth(i) {
  if (!SWEEP.length) return;
  widthIdx = Math.max(0, Math.min(SWEEP.length - 1, Math.round(i)));
  const row = SWEEP[widthIdx];
  const open = new THREE.Color(TOK.ok), shut = new THREE.Color(TOK.bad);
  Object.entries(row.rooms).forEach(([name, ok]) => {
    const pad = roomPads[name];
    if (!pad) return;
    pad.material.color.copy(ok ? open : shut);
    pad.material.opacity = ok ? 0.16 : 0.42;
  });
  const sl = el("widthslider");
  if (sl && Number(sl.value) !== widthIdx) sl.value = String(widthIdx);
  el("widthval").textContent = row.width_in.toFixed(0) + "\u2033";
  el("roomstate").innerHTML = Object.entries(row.rooms)
    .sort((a, b) => Number(a[1]) - Number(b[1]))
    .map(([n, ok]) => `<span class="${ok ? "on" : "off"}">` +
         `<i style="background:${ok ? "var(--ok)" : "var(--bad)"}"></i>` +
         `${n}${ok ? "" : " \u2014 closed"}</span>`).join("");
  el("statn").textContent = row.pct.toFixed(0) + "%";
  el("statl").textContent = "of the floor, at " + row.width_in.toFixed(0) +
    " inches wide";
}

/* ---------- agents ---------- */
function makeAgent(profile) {
  const g = new THREE.Group();
  const col = new THREE.Color(profile.c);
  const parts = {};

  if (profile.body === "wheelchair") {
    const chair = makeWheelchair(THREE, profile.c);
    g.add(chair.group);
    parts.wheels = chair.wheels;
    const rider = makeFigure(THREE, profile.c, { seated: true });
    rider.group.position.set(0, 0.04, 0.02);
    g.add(rider.group);
    parts.figure = rider.parts;
    parts.seated = true;
    parts.eyeH = 1.25;
  } else if (profile.body === "robot") {
    const r = makeRobot(THREE, profile.c);
    g.add(r.group);
    parts.wheels = r.wheels;
    parts.eyeH = 0.95;
  } else {
    const f = makeFigure(THREE, profile.c, {});
    g.add(f.group);
    parts.figure = f.parts;
    parts.eyeH = 1.62;
    if (profile.body === "cane") {
      const cane = new THREE.Mesh(
        new THREE.CylinderGeometry(0.013, 0.013, 1.20, 8),
        new THREE.MeshStandardMaterial({
          color: 0xf4f6f8, roughness: 0.42, metalness: 0.1 }));
      cane.geometry.translate(0, -0.60, 0);
      const pivot = new THREE.Group();
      pivot.position.set(0.20, 1.05, 0.10);
      pivot.rotation.x = -0.30;
      pivot.add(cane);
      g.add(pivot);
      parts.cane = pivot;
      // The 42-inch sweep arc is this profile's real footprint and the
      // reason it is the widest body in the population, so it is drawn at
      // exactly the radius the analysis eroded by.
      const arc = new THREE.Mesh(
        new THREE.RingGeometry(0.14, profile.width_in * 0.0254 / 2, 48, 1,
                               -0.8, 1.6),
        new THREE.MeshBasicMaterial({
          color: col, transparent: true, opacity: 0.16,
          side: THREE.DoubleSide, depthWrite: false }));
      arc.rotation.x = -Math.PI / 2;
      arc.position.y = 0.02;
      g.add(arc);
      parts.arc = arc;
    }
  }

  // Footprint ring: the body envelope the analysis actually used.
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(profile.width_in * 0.0254 / 2 - 0.025,
                           profile.width_in * 0.0254 / 2, 52),
    new THREE.MeshBasicMaterial({ color: col, transparent: true,
                                  opacity: 0.7, side: THREE.DoubleSide,
                                  depthWrite: false }));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.02;
  g.add(ring);
  parts.ring = ring;

  // Contact shadow: keeps a figure planted where the directional shadow
  // map is grazing and would otherwise leave it floating.
  const blob = new THREE.Mesh(
    new THREE.CircleGeometry(profile.width_in * 0.0254 / 2 * 0.9, 24),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true,
                                  opacity: 0.24, depthWrite: false }));
  blob.rotation.x = -Math.PI / 2;
  blob.position.y = 0.008;
  g.add(blob);

  g.userData.parts = parts;
  g.visible = false;
  scene.add(g);
  return g;
}

D.profiles.forEach(p => { p.agent = makeAgent(p); });

/* ---------- route helpers ---------- */
function pathLength(path) {
  let L = 0;
  for (let i = 1; i < path.length; i++) {
    L += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
  }
  return L;
}
function samplePath(path, s) {
  // s in metres along the path; returns {pos, dir}
  if (path.length === 0) return null;
  if (path.length === 1) return { p: path[0], dir: [1, 0] };
  let acc = 0;
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i];
    const seg = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (acc + seg >= s || i === path.length - 1) {
      const t = seg < 1e-6 ? 0 : Math.min(1, (s - acc) / seg);
      return {
        p: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t],
        dir: [(b[0] - a[0]) / (seg || 1), (b[1] - a[1]) / (seg || 1)]
      };
    }
    acc += seg;
  }
  return { p: path[path.length - 1], dir: [1, 0] };
}

const SPEED = { walker: 1.35, wheelchair: 1.05, cane: 0.85, robot: 1.0 };

/* Real walking pace across a 44 m building does not fit in a twelve
   second scene -- the agent covers a third of its route and the shot
   reads as "it barely moved". Speed is scaled so the whole journey
   completes with time to spare, and the ratio between profiles is
   preserved so the wheelchair still visibly trails the walker. */
function paceFor(profile, lengthM, dur, delay) {
  const base = SPEED[profile.body] || 1.2;
  const window = Math.max((dur - (delay || 0)) * 0.68, 1);
  const needed = lengthM / window;
  return Math.max(base, Math.min(needed, base * 5.5));
}

function placeAgent(profile, sample, t) {
  const g = profile.agent, P = g.userData.parts;
  g.visible = true;
  g.position.copy(v3(sample.p[0], sample.p[1], sample.p[2]));
  g.rotation.y = Math.atan2(sample.dir[0], sample.dir[1]);
  const moving = sample.moving !== false;

  if (P.wheels) P.wheels.forEach(w => { if (moving) w.rotation.z -= 0.20; });

  const F = P.figure;
  if (F) {
    // Contralateral gait: opposite arm and leg swing together and the
    // knee flexes on the recovery stroke. Without the knee bend a walk
    // cycle reads as a puppet skating along the floor.
    const s0 = moving ? Math.sin(t * 8.4) : 0;
    const c0 = moving ? Math.cos(t * 8.4) : 0;
    if (F.legs && !P.seated) {
      F.legs[0].upper.rotation.x = s0 * 0.62;
      F.legs[1].upper.rotation.x = -s0 * 0.62;
      F.legs[0].lower.rotation.x = Math.max(0, -c0) * 0.75;
      F.legs[1].lower.rotation.x = Math.max(0, c0) * 0.75;
      if (moving) g.position.y += Math.abs(Math.sin(t * 8.4)) * 0.015;
    }
    if (F.arms) {
      if (P.seated) {
        // Pushing the rims: both arms cycle together, forward then down.
        const push = moving ? Math.sin(t * 5.0) : 0;
        F.arms.forEach(a => {
          a.upper.rotation.x = 0.50 + push * 0.55;
          a.lower.rotation.x = -0.55 - Math.max(0, push) * 0.35;
        });
      } else {
        F.arms[0].upper.rotation.x = -s0 * 0.42;
        F.arms[1].upper.rotation.x = s0 * 0.42;
        F.arms[0].lower.rotation.x = -0.25 - Math.max(0, c0) * 0.20;
        F.arms[1].lower.rotation.x = -0.25 - Math.max(0, -c0) * 0.20;
      }
    }
    if (F.head) F.head.rotation.y = Math.sin(t * 1.3) * 0.12;
  }
  if (P.cane) {
    // Constant-contact sweep, in time with the stride.
    P.cane.rotation.z = Math.sin(t * 4.2) * 0.52;
    P.cane.rotation.x = -0.30 + Math.sin(t * 4.2 + 1.6) * 0.06;
  }
}

/* ---------- markers ---------- */
function makeLabel(text, color, sub) {
  const pad = 26, fs = 46, sfs = 32;
  const c = document.createElement("canvas");
  const g = c.getContext("2d");
  g.font = `600 ${fs}px ui-monospace, Menlo, monospace`;
  const w1 = g.measureText(text).width;
  g.font = `400 ${sfs}px -apple-system, Segoe UI, sans-serif`;
  const w2 = sub ? g.measureText(sub).width : 0;
  c.width = Math.ceil(Math.max(w1, w2) + pad * 2);
  c.height = sub ? fs + sfs + pad * 2 + 10 : fs + pad * 2;
  const g2 = c.getContext("2d");
  g2.fillStyle = TOK.dark ? "rgba(14,18,22,0.93)" : "rgba(255,255,255,0.95)";
  g2.strokeStyle = color; g2.lineWidth = 4;
  const r = 12;
  g2.beginPath();
  g2.moveTo(r, 0); g2.arcTo(c.width, 0, c.width, c.height, r);
  g2.arcTo(c.width, c.height, 0, c.height, r);
  g2.arcTo(0, c.height, 0, 0, r); g2.arcTo(0, 0, c.width, 0, r);
  g2.closePath(); g2.fill(); g2.stroke();
  g2.fillStyle = color;
  g2.font = `600 ${fs}px ui-monospace, Menlo, monospace`;
  g2.fillText(text, pad, pad + fs - 10);
  if (sub) {
    g2.fillStyle = TOK.ink;
    g2.font = `400 ${sfs}px -apple-system, Segoe UI, sans-serif`;
    g2.fillText(sub, pad, pad + fs + sfs);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, transparent: true, depthTest: false }));
  sp.scale.set(c.width / 170, c.height / 170, 1);
  sp.renderOrder = 999;
  return sp;
}

const markers = new THREE.Group();
scene.add(markers);
function clearMarkers() {
  while (markers.children.length) {
    const m = markers.children.pop();
    m.traverse(o => {
      if (o.material) {
        if (o.material.map) o.material.map.dispose();
        o.material.dispose();
      }
      if (o.geometry) o.geometry.dispose();
    });
  }
}
function addMarker(x, y, z, text, sub, color, kind) {
  const grp = new THREE.Group();
  grp.position.copy(v3(x, y, z));
  const col = new THREE.Color(color);
  const beam = new THREE.Mesh(
    new THREE.CylinderGeometry(0.05, 0.05, 2.5, 10),
    new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.32,
                                  depthWrite: false }));
  beam.position.y = 1.25; grp.add(beam);
  const disc = new THREE.Mesh(
    new THREE.RingGeometry(0.30, 0.42, 34),
    new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.9,
                                  side: THREE.DoubleSide, depthWrite: false }));
  disc.rotation.x = -Math.PI / 2; disc.position.y = 0.03; grp.add(disc);
  const lab = makeLabel(text, color, sub);
  lab.position.y = 2.75; grp.add(lab);
  grp.userData.pulse = disc;
  grp.userData.born = clock;
  markers.add(grp);
  return grp;
}

/* ---------- clickable chokepoints ---------- */
/* Every blockage the analysis found, with a verdict attached: move it,
   re-lay it, build it, or -- the case a two-way split cannot express --
   fix it together with others or not at all. */
const CP = D.chokepoints || [];
const cpGroup = new THREE.Group();
scene.add(cpGroup);
const cpHits = [];

const VERDICT_COLOR = () => ({
  move: TOK.ok, reconfigure: TOK.warn, build: TOK.bad, combined: TOK.bad
});

function buildChokepoints() {
  while (cpGroup.children.length) cpGroup.children.pop();
  cpHits.length = 0;
  const col = VERDICT_COLOR();
  CP.forEach((c, i) => {
    const g = new THREE.Group();
    g.position.copy(v3(c.pos[0], c.pos[1], 0));
    const cc = new THREE.Color(col[c.verdict] || TOK.bad);

    const disc = new THREE.Mesh(
      new THREE.RingGeometry(0.34, 0.5, 30),
      new THREE.MeshBasicMaterial({ color: cc, transparent: true,
                                    opacity: 0.92, side: THREE.DoubleSide,
                                    depthWrite: false, depthTest: false }));
    disc.rotation.x = -Math.PI / 2; disc.position.y = 0.05;
    disc.renderOrder = 20; g.add(disc);

    const post = new THREE.Mesh(
      new THREE.CylinderGeometry(0.045, 0.045, 1.7, 8),
      new THREE.MeshBasicMaterial({ color: cc, transparent: true,
                                    opacity: 0.55, depthWrite: false,
                                    depthTest: false }));
    post.position.y = 0.85; post.renderOrder = 20; g.add(post);

    const knob = new THREE.Mesh(
      new THREE.SphereGeometry(0.17, 18, 12),
      new THREE.MeshBasicMaterial({ color: cc, depthTest: false }));
    knob.position.y = 1.78; knob.renderOrder = 21; g.add(knob);

    // Generous invisible hit target: the visible knob is only a few
    // pixels across at demo distance and would be unclickable.
    const hit = new THREE.Mesh(
      new THREE.SphereGeometry(0.85, 10, 8),
      new THREE.MeshBasicMaterial({ visible: false }));
    hit.position.y = 1.4;
    hit.userData.cp = c;
    g.add(hit); cpHits.push(hit);

    g.userData.knob = knob;
    cpGroup.add(g);
  });
  cpGroup.visible = false;
}
buildChokepoints();

function cpSummary() {
  const free = CP.filter(c => c.cost === 0);
  const paid = CP.filter(c => c.cost > 0);
  const total = paid.reduce((a, c) => a + c.cost, 0);
  el("cpsum").innerHTML =
    `<b>${free.length} <i>free \u2014 move the furniture</i></b>` +
    `<b>${paid.length} <i>need building \u2014</i> $${total.toLocaleString()}</b>` +
    `<b><i>click any marker</i></b>`;
}

const ray = new THREE.Raycaster();
const ndc = new THREE.Vector2();
let cpOpen = null;

function showChokepoint(c) {
  cpOpen = c;
  const pop = el("cppop");
  pop.hidden = false;
  el("cpverdict").className = "cpv " + c.verdict;
  el("cpverdict").textContent =
    c.verdict === "move" ? "move it \u2014 free"
      : c.verdict === "reconfigure" ? "re-lay fixed furniture"
      : c.verdict === "build" ? "reconstruction"
      : "combined works needed";
  el("cptitle").textContent =
    c.verdict === "move" ? "Blocked by loose furniture"
      : c.verdict === "reconfigure" ? "Blocked by fixed furniture"
      : c.verdict === "combined" ? "One of several barriers"
      : "Blocked by the building";
  el("cpdetail").textContent = c.detail;

  const rows = [];
  rows.push(["Cost", c.cost === 0 ? "no cost" : "$" + c.cost.toLocaleString()]);
  if (c.excludes && c.excludes.length) {
    rows.push(["Excludes", c.excludes.map(n =>
      (P[n] && P[n].label) || n).join(", ")]);
  }
  if (c.area_m2) rows.push(["Returns", c.area_m2 + " m\u00b2 of floor"]);
  if (c.opens_alone && c.opens_alone.length) {
    rows.push(["Opens", c.opens_alone.map(n =>
      (P[n] && P[n].label) || n).join(", ")]);
  } else if (c.verdict === "combined") {
    rows.push(["On its own", "opens nothing"]);
  }
  if (c.chosen) rows.push(["Optimiser", "selected within budget"]);
  el("cpfacts").innerHTML = rows.map(([k, v]) =>
    `<dt>${k}</dt><dd>${v}</dd>`).join("");

  // Anchor the panel to the marker's projected position, clamped inside
  // the viewport so a marker near an edge does not push it off-screen.
  const p = v3(c.pos[0], c.pos[1], 1.9).project(camera);
  const r = stage.getBoundingClientRect();
  const x = (p.x * 0.5 + 0.5) * r.width;
  const y = (-p.y * 0.5 + 0.5) * r.height;
  // The audit panel occupies the right-hand 340px while inspecting, so
  // the usable width shrinks and a marker over there would otherwise
  // put the panel underneath it.
  const rightEdge = r.width - (inspecting ? 356 : 8) - 292;
  let left = x + 16;
  if (left > rightEdge) left = x - 308;
  pop.style.left = Math.max(8, Math.min(rightEdge, left)) + "px";
  pop.style.top = Math.max(8, Math.min(r.height - 220, y - 40)) + "px";
  pop.focus();
}

function hideChokepoint() { cpOpen = null; el("cppop").hidden = true; }

stage.addEventListener("click", e => {
  if (inspecting) {
    const r = stage.getBoundingClientRect();
    ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
    ray.setFromCamera(ndc, camera);
    const h = ray.intersectObjects(isHits, false)[0];
    if (h) selectIssue(h.object.userData.idx);
    return;
  }
  if (!cpGroup.visible) return;
  const r = stage.getBoundingClientRect();
  ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
  ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObjects(cpHits, false)[0];
  if (hit) showChokepoint(hit.object.userData.cp);
  else hideChokepoint();
});

/* ---------- camera ---------- */
let camState = { pos: new THREE.Vector3(), tgt: new THREE.Vector3() };
let camGoal = { pos: new THREE.Vector3(), tgt: new THREE.Vector3() };
let orbit = { on: false, az: 0, el: 0, dist: 0, drag: false, px: 0, py: 0 };

function lookAt(px, py, pz, tx, ty, tz, snap) {
  camGoal.pos.copy(v3(px, py, pz));
  camGoal.tgt.copy(v3(tx, ty, tz));
  if (snap) { camState.pos.copy(camGoal.pos); camState.tgt.copy(camGoal.tgt); }
}
lookAt(-14, -10, 22, BW / 2, BH / 2, 0, true);

stage.addEventListener("pointerdown", e => {
  orbit.drag = true; orbit.px = e.clientX; orbit.py = e.clientY;
  stage.setPointerCapture(e.pointerId);
});
stage.addEventListener("pointerup", e => { orbit.drag = false; });
stage.addEventListener("pointermove", e => {
  if (!orbit.drag) return;
  const dx = e.clientX - orbit.px, dy = e.clientY - orbit.py;
  orbit.px = e.clientX; orbit.py = e.clientY;
  const off = camGoal.pos.clone().sub(camGoal.tgt);
  const sph = new THREE.Spherical().setFromVector3(off);
  sph.theta -= dx * 0.005;
  sph.phi = Math.max(0.12, Math.min(1.45, sph.phi - dy * 0.004));
  off.setFromSpherical(sph);
  camGoal.pos.copy(camGoal.tgt).add(off);
  userCam = true;
});
stage.addEventListener("wheel", e => {
  e.preventDefault();
  const off = camGoal.pos.clone().sub(camGoal.tgt);
  off.multiplyScalar(1 + Math.sign(e.deltaY) * 0.08);
  if (off.length() > 6 && off.length() < 140) camGoal.pos.copy(camGoal.tgt).add(off);
  userCam = true;
}, { passive: false });
let userCam = false;

/* ---------- inspect mode ---------- */
/* The walkthrough is a story; this is the worklist. It leaves the
   guided sequence entirely: every issue at once, free camera, and a
   list you can work down. Selecting one flies the camera to it. */
const ISSUES = D.issues || [];
let inspecting = false, isFilter = "all", isSel = null;

const VCOL = () => ({ move: TOK.ok, reconfigure: TOK.warn,
                      build: TOK.bad, combined: TOK.bad });
const VLABEL = { move: "free · move it", reconfigure: "re-lay fixed",
                 build: "reconstruction", combined: "combined works" };

const isGroup = new THREE.Group();
scene.add(isGroup);
const isHits = [];

function buildIssueMarkers() {
  while (isGroup.children.length) isGroup.children.pop();
  isHits.length = 0;
  const col = VCOL();
  ISSUES.forEach((it, i) => {
    const g = new THREE.Group();
    g.position.copy(v3(it.pos[0], it.pos[1], 0));
    const cc = new THREE.Color(col[it.verdict] || TOK.bad);
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.32, 0.46, 28),
      new THREE.MeshBasicMaterial({ color: cc, transparent: true,
        opacity: 0.9, side: THREE.DoubleSide, depthWrite: false,
        depthTest: false }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.05;
    ring.renderOrder = 30; g.add(ring);
    const post = new THREE.Mesh(
      new THREE.CylinderGeometry(0.04, 0.04, 2.1, 8),
      new THREE.MeshBasicMaterial({ color: cc, transparent: true,
        opacity: 0.45, depthWrite: false, depthTest: false }));
    post.position.y = 1.05; post.renderOrder = 30; g.add(post);
    const knob = new THREE.Mesh(
      new THREE.SphereGeometry(0.16, 16, 12),
      new THREE.MeshBasicMaterial({ color: cc, depthTest: false }));
    knob.position.y = 2.15; knob.renderOrder = 31; g.add(knob);
    const hit = new THREE.Mesh(new THREE.SphereGeometry(0.9, 10, 8),
      new THREE.MeshBasicMaterial({ visible: false }));
    hit.position.y = 1.5; hit.userData.idx = i;
    g.add(hit); isHits.push(hit);
    g.userData = { knob, ring, post, idx: i };
    isGroup.add(g);
  });
  isGroup.visible = false;
}
buildIssueMarkers();

function money(n) { return n ? "$" + n.toLocaleString() : "free"; }

/* Furniture does not "exclude the walking adult" -- it costs everybody
   floor, which is a different sentence. Blockages that stop a body
   outright get the exclusion wording; the rest get the recovery
   wording. */
function who(it) {
  const names = (it.excludes || [])
    .map(n => (P[n] && P[n].label) || n);
  if (!names.length) return "no body stopped here today";
  if (it.verdict === "move" || it.verdict === "reconfigure") {
    return `returns floor to ${names.length === D.profiles.length
      ? "every body" : names.join(", ")}`;
  }
  return "excludes " + names.filter(n => n !== "Walking adult").join(", ");
}

/* Grouping the worklist by what it takes to action, not by cost.
   "Three things you can do this afternoon for nothing" is a different
   conversation from "$71k of building work", and a client hears the
   first one. */
const PHASES = [
  { key: "now", label: "Today · no cost", test: it => it.cost === 0 },
  { key: "soon", label: "Minor works · under $2,500",
    test: it => it.cost > 0 && it.cost < 2500 },
  { key: "capital", label: "Capital works", test: it => it.cost >= 2500 },
];

function renderIssueList() {
  const shown = ISSUES.map((it, i) => ({ it, i })).filter(({ it }) =>
    isFilter === "all" ? true
      : isFilter === "move" ? it.cost === 0
      : isFilter === "combined" ? it.verdict === "combined"
      : it.cost > 0 && it.verdict !== "combined");
  const paid = ISSUES.filter(i => i.cost > 0);
  const free = ISSUES.filter(i => i.cost === 0);
  el("istotal").textContent =
    "$" + paid.reduce((a, c) => a + c.cost, 0).toLocaleString();
  el("issub").textContent =
    `${ISSUES.length} issues · ${free.length} cost nothing` +
    (ISSUES[0] && ISSUES[0].minor_folded
      ? ` · ${ISSUES[0].minor_folded} minor folded` : "");
  // What the money is actually for. A percentage of a sampled
  // population is the number a client can act on; square metres are not.
  const pop = D.population;
  if (pop && el("ispop")) {
    el("ispop").innerHTML =
      `<b>${(100 - pop.pct_full_access).toFixed(0)}%</b> of a sampled ` +
      `mobility population of ${pop.n_sampled} cannot reach every ` +
      `destination in this building today.`;
  }
  const row = ({ it, i }) => `
    <li><button data-i="${i}" class="${isSel === i ? "sel" : ""}">
      <span class="r1">
        <em class="v-${it.verdict}">${VLABEL[it.verdict] || it.verdict}</em>
        <strong>${money(it.cost)}</strong>
      </span>
      <span class="r2">${it.detail}</span>
      <span class="r3">${it.room ? it.room + " · " : ""}${who(it)}</span>
    </button></li>`;
  if (!shown.length) {
    el("islist").innerHTML =
      `<li class="isempty">Nothing in this category.<br>` +
      `Try <strong>All</strong>.</li>`;
    return;
  }
  el("islist").innerHTML = PHASES.map(ph => {
    const rows = shown.filter(({ it }) => ph.test(it));
    if (!rows.length) return "";
    const sum = rows.reduce((a, { it }) => a + it.cost, 0);
    return `<li class="isphase">${ph.label}<span>${
      sum ? "$" + sum.toLocaleString() : rows.length + " items"
    }</span></li>` + rows.map(row).join("");
  }).join("");
  el("islist").querySelectorAll("button[data-i]").forEach(b =>
    b.addEventListener("click", () => selectIssue(Number(b.dataset.i))));
}

function selectIssue(i) {
  isSel = i;
  const it = ISSUES[i];
  // Fly to it: an oblique three-quarter view close enough to read the
  // room, which is more use than dropping the camera on its head.
  lookAt(it.pos[0] - 7, it.pos[1] - 7, 6.5,
         it.pos[0], it.pos[1], 0.9);
  userCam = false;
  isGroup.children.forEach(g => {
    const on = g.userData.idx === i;
    g.userData.knob.scale.setScalar(on ? 1.7 : 1);
    g.userData.ring.material.opacity = on ? 1 : 0.35;
    g.userData.post.material.opacity = on ? 0.8 : 0.18;
  });
  showChokepoint({ ...it, verdict: it.verdict });
  renderIssueList();
  syncNav();
}

function setInspect(on) {
  inspecting = on;
  playing = !on;
  el("inspect").setAttribute("aria-pressed", String(on));
  el("inspect").textContent = on ? "Back to walkthrough" : "Inspect issues";
  el("ispanel").hidden = !on;
  el("play").disabled = on;
  isGroup.visible = on;
  if (on) {
    hideAgents(); clearMarkers(); hideChokepoint();
    decalGroup.visible = false; cpGroup.visible = false;
    roomGroup.visible = false; surfGroup.visible = false;
    el("cpsum").hidden = true; el("widthcard").hidden = true;
    setWallCut(0.16);
    roomLabels.visible = true;
    isSel = null;
    buildIssueMarkers();
    isGroup.visible = true;
    renderIssueList();
    lookAt(BW / 2, -8, 36, BW / 2, BH / 2, 0);
    const paid = ISSUES.filter(i => i.cost > 0);
    // Through the same fade, which cancels any write the walkthrough
    // deferred. Writing directly let goto()'s pending crossfade land
    // afterwards and repaint a walkthrough caption under an AUDIT
    // header.
    fadeCaption(() => {
      el("kicker").textContent = "Inspect";
      el("caption").innerHTML =
        `Every issue the analysis found, with what fixes it. ` +
        `<em>Click a row or a marker.</em> ` +
        `${ISSUES.length - paid.length} cost nothing — they are furniture. ` +
        `The rest total $${paid.reduce((a, c) => a + c.cost, 0)
          .toLocaleString()} of building work.`;
    });
    el("sceneno").textContent = "AUDIT";
    el("statn").textContent = String(ISSUES.length);
    el("statl").textContent = "issues found";
    el("bar").style.width = "100%";
    el("live").textContent =
      `Inspect mode. ${ISSUES.length} issues listed.`;
    syncNav();
  } else {
    hideChokepoint();
    goto(sceneI);
  }
}

/* ---------- scene script ---------- */
const P = {};
D.profiles.forEach(p => P[p.name] = p);
const REC = D.recall, OPT = D.remediation, POP = D.population;
const BPs = D.breaking_point.community_room || Object.values(D.breaking_point)[0];
const chosen = OPT.chosen[0];
// The interesting rejection is not the dearest one, it is the one that
// scored BEST per dollar and was still turned down.
const rejected = (OPT.rejected || []).filter(r => r.harm)
  .sort((a, b) => b.pct_per_1k_usd - a.pct_per_1k_usd)[0];
const n0 = (v, d) => Number(v).toFixed(d == null ? 0 : d);

function journeyOf(pname, goal) { return P[pname].journeys[goal]; }

const SCENES = [
  {
    id: "establish", dur: 9.0, kicker: "The building",
    cap: () => {
      // Built from the data. Hard-coding the room list and the defect
      // count meant the opening line still said "eight defects" and
      // listed rooms from a building two revisions old.
      const names = (D.rooms || []).map(r => r.name)
        .filter(n => n && n !== "Corridor");
      const last = names.pop();
      return `A generated civic centre — ${names.join(", ")} and a
        ${last.toLowerCase()}. It is drawn to code.
        <em>${REC.planted} access defects are planted in it</em>, and every
        one is a condition that passes a plan check.`;
    },
    stat: () => [String(REC.planted), "planted defects"],
    enter() {
      setWallCut(1.0); decalGroup.visible = false; hideAgents();
      lookAt(-13, -11, 20, BW / 2, BH / 2 - 1, 1.2);
    },
    tick(t) {
      const a = t / this.dur;
      lookAt(BW / 2 + Math.cos(a * 1.3 - 2.2) * 30,
             BH / 2 + Math.sin(a * 1.3 - 2.2) * 30, 15 - a * 3,
             BW / 2, BH / 2, 1.0);
    }
  },
  {
    id: "walker", dur: 13.0, kicker: "Walking adult", profile: "baseline_walking",
    cap: `A walking adult reaches <em>every room in the building</em> —
          ${n0(P.baseline_walking.reach_m2, 0)} m², 100% of the floor.
          The community room, the gallery, the WC: all connected.
          This is the building as its drawings describe it.`,
    stat: () => ["100%", "of the floor reached"],
    walk: [["baseline_walking", "community_room", 0],
           ["baseline_walking", "gallery", 6.0]],
    enter() { hideAgents(); decalGroup.visible = false; },
    tick(t) {
      // Walls drop to knee height over the first two seconds, which the
      // cut-away scene used to do on its own.
      setWallCut(1.0 - 0.78 * Math.min(1, t / 2.0));
      follow("baseline_walking", t, 16, -6, 9);
    }
  },
  {
    id: "chair-room", dur: 17.0, kicker: "Wheelchair · community room",
    profile: "wheelchair",
    cap: () => {
      const b = (journeyOf("wheelchair", "community_room").barriers || [])[0];
      return `The wheelchair takes the same route and <em>stops at the door</em>.
        ${b ? `${n0(b.aperture_in)} inches clear where 32 are required` :
        "The opening is too narrow"} — and the wider entrance beside it sits on
        a ${n0((journeyOf("wheelchair", "community_room").barriers || [])
          .filter(x => x.kind === "step_height").map(x => x.step_in)[0] || 7.9, 1)}-inch
        threshold. <em>Two ways in, neither usable.</em>`;
    },
    stat: () => [n0(P.wheelchair.pct, 1) + "%", "of the floor reached"],
    walk: [["wheelchair", "community_room", 0]],
    enter() { hideAgents(); decalGroup.visible = false; setWallCut(0.22); },
    tick(t) { follow("wheelchair", t, 9, -5, 6); },
    onStop(pname, goal) {
      const j = journeyOf(pname, goal);
      (j.barriers || []).slice(0, 2).forEach((b, i) => {
        addMarker(b.pos[0], b.pos[1], b.pos[2],
          b.kind === "clearance_width" ? `${n0(b.aperture_in)}" clear`
            : b.kind === "step_height" ? `${n0(b.step_in, 1)}" step`
            : `1:${n0(1 / Math.max(b.slope, 1e-3))}`,
          b.kind === "clearance_width" ? "needs 32\" — ADA 404.2.3"
            : b.kind === "step_height" ? "needs ½\" — ADA 303.2"
            : "needs 1:12 — ADA 405.2", TOK.bad);
      });
    }
  },
  {
    id: "eye", dur: 14.0, kicker: "At eye level", profile: "wheelchair",
    cap: `The same approach, from the chair. <em>Nothing about this view is
          unusual until it stops.</em> That is the point: the failure is not
          visible from the corridor, it is not visible on the drawing, and it
          is not visible to anybody who does not have to make the turn.`,
    stat: () => ["28\u2033", "clear, where 32 are required"],
    walk: [["wheelchair", "community_room", 0]],
    enter() {
      hideAgents(); clearMarkers(); decalGroup.visible = false;
      roomGroup.visible = false;
      // Full-height walls and no floating room labels: from inside, the
      // doll's-house section and the plan annotation both break the
      // illusion that you are actually in the room.
      setWallCut(1.0);
      roomLabels.visible = false;
    },
    tick(t) { eyeLevel("wheelchair", 2.5); },
    onStop(pname, goal) {
      (journeyOf(pname, goal).barriers || []).slice(0, 1).forEach(b =>
        addMarker(b.pos[0], b.pos[1], b.pos[2],
                  `${n0(b.aperture_in)}\u2033 clear`,
                  "needs 32\u2033 — ADA 404.2.3", TOK.bad));
    }
  },
  {
    id: "width", dur: 20.0, kicker: "Where does it close?",
    cap: `Drag the slider. Every room is re-tested as the body widens, and
          they switch off one at a time. <em>At 28 inches the community room
          and the accessible WC go dark; at 32 — a standard powered
          wheelchair — the lift follows.</em> The gallery is never open at any
          width, because it was never a width problem.`,
    stat: () => ["28\u2033", "where the first rooms close"],
    slider: true,
    enter() {
      hideAgents(); clearMarkers(); decalGroup.visible = false;
      roomGroup.visible = true; setWallCut(0.16);
      el("widthcard").hidden = false;
      applyWidth(0);
      lookAt(BW / 2, -4, 34, BW / 2, BH / 2, 0);
    },
    tick(t) {
      // Sweep on its own so an unattended demo still tells the story;
      // touching the slider hands control over for the rest of the scene.
      if (!sliderTouched) {
        const k = Math.min(1, t / (this.dur * 0.72));
        applyWidth(k * (SWEEP.length - 1));
      }
      lookAt(BW / 2 + Math.sin(t * 0.22) * 6, -4, 34, BW / 2, BH / 2, 0);
    }
  },
  {
    id: "islands", dur: 13.0, kicker: "The finding",
    cap: `Those two regions are <em>geometrically flawless inside</em> — wide,
          dead flat, with turning circles to spare. They are also completely
          unreachable in a wheelchair. <em>No clearance-based audit flags a room
          for being fine.</em> You only find this by trying to arrive.`,
    stat: () => [n0(P.wheelchair.island_m2, 0) + " m²", "compliant but unreachable"],
    enter() {
      hideAgents(); clearMarkers();
      decalGroup.visible = true; paintDecal("profile", P.wheelchair, false);
      P.wheelchair.islands.forEach(i => {
        addMarker(i.pos[0], i.pos[1], i.pos[2],
          `${n0(i.area_m2, 0)} m² stranded`, i.room || "unreachable", TOK.bad);
      });
      lookAt(BW / 2 - 3, -6, 22, BW / 2, BH / 2, 0);
    },
    tick(t) {
      lookAt(BW / 2 - 3 + t * 0.7, -6 + t * 0.5, 22 + t * 0.35,
             BW / 2, BH / 2, 0);
    }
  },
  {
    id: "cane", dur: 12.0, kicker: "Cane user · WC", profile: "vision_impaired_cane",
    cap: `A cane sweeps a 42-inch arc — <em>wider than a wheelchair</em>. It
          clears the corridor, then meets a bulkhead dropped to 1 950 mm over
          the accessible WC door. <em>The WC excludes two different people for
          two entirely different reasons</em>: headroom here, and a 42-inch
          turning circle where 60 are required, inside.`,
    stat: () => ["1 950 mm", "headroom, needs 2 032"],
    walk: [["vision_impaired_cane", "restroom", 0]],
    enter() { hideAgents(); clearMarkers(); decalGroup.visible = false; setWallCut(0.22); },
    tick(t) { follow("vision_impaired_cane", t, 7, -4, 4.5); },
    onStop(pname, goal) {
      (journeyOf(pname, goal).barriers || []).slice(0, 1).forEach(b => {
        addMarker(b.pos[0], b.pos[1], b.pos[2], `1 950 mm`,
          "head clearance — ADA 307.4", TOK.bad);
      });
      const wc = REC.per_defect.find(d => d.id === "wc_turning_1300mm");
      if (wc) addMarker(wc.pos[0], wc.pos[1], 0, `42" circle`,
        "needs 60\" — ADA 304.3.1", TOK.warn);
    }
  },
  {
    id: "robot", dur: 11.0, kicker: "Delivery robot",
    profile: "sidewalk_delivery_robot",
    cap: `A 26-inch delivery robot goes <em>straight through the door that
          excluded the wheelchair</em>. It is narrow enough. The same building
          admits a machine and turns away a person — and the same analysis
          serves robotics deployment and accessibility, because both are only
          ever a body envelope.`,
    stat: () => [n0(P.sidewalk_delivery_robot.pct, 1) + "%", "reached by the robot"],
    walk: [["sidewalk_delivery_robot", "community_room", 0]],
    enter() { hideAgents(); clearMarkers(); decalGroup.visible = false; setWallCut(0.22); },
    tick(t) { follow("sidewalk_delivery_robot", t, 9, -5, 6); }
  },
  {
    id: "materials", dur: 15.0, kicker: "What the floor is made of",
    cap: `Geometry is not the only rule. <em>ADA 302 governs the floor
          itself</em>, and pile over 13 mm fails it. The auditorium is
          carpeted at 22 mm: level, wide, generous, compliant on every
          dimension a tape measure reaches — and <em>it stops a wheelchair
          and nothing else</em>. The cane user walks across it. The
          delivery robot rides over it on bigger wheels. Only the
          100 mm front castors of a manual chair dig in and stop.`,
    stat: () => ["22 mm", "pile, where ADA 302.2 allows 13"],
    materials: true,
    enter() {
      hideAgents(); clearMarkers(); decalGroup.visible = false;
      cpGroup.visible = false; roomGroup.visible = false;
      paintSurfaces(0.85); surfGroup.visible = true;
      el("widthcard").hidden = false;
      el("widthcard").querySelector("h3").textContent = "Floor materials";
      el("widthcard").querySelector(".wrow").hidden = true;
      surfaceLegend();
      setWallCut(0.16);
      lookAt(BW / 2, -4, 36, BW / 2, BH / 2, 0);
    },
    tick(t) {
      lookAt(BW / 2 + Math.sin(t * 0.24) * 9, -4, 36, BW / 2, BH / 2, 0);
    }
  },
  {
    id: "choke", dur: 24.0, kicker: "Every blockage, priced",
    cap: `<em>Click any marker.</em> Each blockage carries a verdict: move
          the furniture and it costs nothing; re-lay fixed seating or widen
          an opening and it costs money; or — the case a two-way split
          cannot express — <em>fixing it alone opens nothing</em>, because it
          is one of several barriers on the same route.`,
    stat: () => {
      const free = CP.filter(c => c.cost === 0).length;
      const paid = CP.filter(c => c.cost > 0);
      return [String(free) + " free",
              "and " + paid.length + " needing $" +
              paid.reduce((a, c) => a + c.cost, 0).toLocaleString()];
    },
    enter() {
      hideAgents(); clearMarkers(); decalGroup.visible = false;
      buildChokepoints();
      cpGroup.visible = true; setWallCut(0.16);
      el("cpsum").hidden = false; cpSummary();
      lookAt(BW / 2, -6, 32, BW / 2, BH / 2, 0);
    },
    tick(t) {
      // Markers rise in sequence so the eye finds them, then the camera
      // drifts gently. Clicking is available throughout.
      cpGroup.children.forEach((g, i) => {
        const a = Math.max(0, Math.min(1, (t - 0.25 - i * 0.16) / 0.45));
        g.scale.setScalar(a);
        g.visible = a > 0.01;
        if (g.userData.knob) {
          g.userData.knob.position.y = 1.78 + Math.sin(clock * 2.2 + i) * 0.06;
        }
      });
      lookAt(BW / 2 + Math.sin(t * 0.18) * 9, -6 + Math.sin(t * 0.11) * 2,
             32, BW / 2, BH / 2, 0);
    }
  },
  {
    id: "fix", dur: 13.0, kicker: "Cheapest repair",
    cap: chosen ? `Every candidate repair is scored by <em>rebuilding the
          building and re-running the whole population through it</em>. With
          $${OPT.budget_usd.toLocaleString()} the optimum is
          <em>$${chosen.cost.toLocaleString()}</em> — ${chosen.detail} —
          returning the community room to the wheelchair
          (<em>${P.wheelchair.pct}% → ${P.wheelchair.after_pct}%</em> of the
          floor) and the cane user
          (${P.vision_impaired_cane.pct}% → ${P.vision_impaired_cane.after_pct}%).`
          + (rejected ? ` A cheaper repair scored
          <em>${n0(rejected.pct_per_1k_usd, 1)} points per $1k against
          ${n0(chosen.pct_per_1k_usd, 1)}</em> and was still rejected:
          rebuilt that way, ${rejected.harm}.` : "")
      : "No single repair improved measured population coverage.",
    stat: () => chosen
      ? ["+" + n0(P.wheelchair.after_pct - P.wheelchair.pct, 1) + " pts",
         "floor returned to the wheelchair, for $" + OPT.spent_usd.toLocaleString()]
      : ["—", ""],
    enter() {
      hideAgents(); clearMarkers();
      decalGroup.visible = true; paintDecal("heat", null, false);
      OPT.chosen.forEach(f => addMarker(f.pos[0], f.pos[1], 0,
        "$" + f.cost.toLocaleString(), f.detail, TOK.ok));
      (OPT.rejected || []).filter(f => f.harm).slice(0, 2).forEach(f =>
        addMarker(f.pos[0], f.pos[1], 0, "$" + f.cost.toLocaleString(),
                  "rejected — " + f.harm, TOK.bad));
      lookAt(BW / 2, -8, 30, BW / 2, BH / 2, 0);
    },
    tick(t) {
      // Halfway through, apply the fixes and show the floor change.
      paintDecal("heat", null, t > this.dur * 0.55);
    }
  },
  {
    id: "truth", dur: 11.0, kicker: "Scored against truth",
    cap: `Because the building is generated, an answer key exists.
          <em>${REC.planted} defects planted, ${REC.detected} recovered</em> by
          an analysis that was never told where to look — it found them by
          walking bodies through the building and noticing where they stopped.
          Point this at a scanned real building and nothing changes.`,
    stat: () => [n0(REC.recall * 100) + "%", "recall against planted truth"],
    enter() {
      hideAgents(); clearMarkers();
      decalGroup.visible = false; setWallCut(0.16);
      REC.per_defect.forEach(d => addMarker(
        d.pos[0], d.pos[1], 0, (d.detected ? "✓ " : "· ") + d.id,
        d.type.replace(/_/g, " "), d.detected ? TOK.ok : TOK.warn));
      lookAt(BW / 2, -10, 32, BW / 2, BH / 2, 0);
    },
    tick(t) {
      lookAt(BW / 2 + Math.sin(t * 0.3) * 10, -10, 32 - t * 0.4,
             BW / 2, BH / 2, 0);
    }
  }
];

function hideAgents() { D.profiles.forEach(p => p.agent.visible = false); }

/* Eye level. Camera at the body's own head height, just behind it,
   looking where it is going -- so the doorway that stops the chair
   arrives at the viewer the way it arrives at the person. */
function eyeLevel(pname, back) {
  const p = P[pname], st = p._active;
  if (!st || !st.sample) return;
  const s = st.sample;
  const eye = (p.agent.userData.parts.eyeH || 1.5);
  const dx = s.dir[0], dy = s.dir[1];
  const b = back || 2.4;
  // Just above and behind the head rather than inside it: close enough
  // to be their view, far enough that the body reads as a body.
  lookAt(s.p[0] - dx * b, s.p[1] - dy * b, s.p[2] + eye + 0.42,
         s.p[0] + dx * 9, s.p[1] + dy * 9, s.p[2] + eye * 0.80);
}

/* Follow the agent that is currently walking, from behind and above. */
function follow(pname, t, back, side, up) {
  back *= 0.62; side *= 0.62; up *= 0.72;
  const p = P[pname];
  const st = p._active;
  if (!st || !st.sample) return;
  const s = st.sample;
  const dx = s.dir[0], dy = s.dir[1];
  lookAt(s.p[0] - dx * back + dy * side, s.p[1] - dy * back - dx * side,
         s.p[2] + up, s.p[0] + dx * 2, s.p[1] + dy * 2, s.p[2] + 0.9);
}

/* ---------- walking engine ---------- */
function resetWalks(sc) {
  // Keyed by goal, not one slot per profile. A scene that sends the same
  // body to two destinations used to overwrite the first journey with
  // the second, so the agent stood still until the second one's delay
  // elapsed and then completed part of one route.
  D.profiles.forEach(p => { p._walks = {}; p._active = null; });
  clearRoute();
  if (!sc.walk) return;
  sc.walk.forEach(([pname, goal, delay]) => {
    const p = P[pname], j = p.journeys[goal];
    p._walks[goal] = {
      goal, delay: delay || 0, j, len: pathLength(j.path), s: 0,
      done: false, drawn: false, sample: null
    };
  });
}

function stepWalks(sc, t, dt) {
  if (!sc.walk) return;
  sc.walk.forEach(([pname, goal, delay]) => {
    const p = P[pname], st = p._walks && p._walks[goal];
    if (!st) return;
    if (t < st.delay) { if (!p._active) p.agent.visible = false; return; }
    if (!st.drawn) { st.drawn = true; drawRoute(st.j.path, p.c, st.j.arrived); }
    const sp = paceFor(p, st.len, SCENES[sceneI].dur, st.delay);
    if (!st.done) st.s += dt * sp;
    if (st.s >= st.len) {
      st.s = st.len;
      if (!st.done) {
        st.done = true;
        if (!st.j.arrived && sc.onStop) sc.onStop(pname, goal);
      }
    }
    const sample = samplePath(st.j.path, st.s);
    if (!sample) return;
    // A blocked body does not simply stop dead: it arrives, hesitates,
    // and eases back. That readable beat is what tells the room the
    // route failed rather than ended.
    if (st.done && !st.j.arrived) {
      const k = Math.sin((t - delay) * 2.2) * 0.5 + 0.5;
      sample.p = sample.p.slice();
      sample.p[0] -= sample.dir[0] * 0.22 * k;
      sample.p[1] -= sample.dir[1] * 0.22 * k;
      sample.moving = false;
    } else if (st.done) {
      sample.moving = false;
    }
    st.sample = sample;
    p._active = st;
    placeAgent(p, sample, t);
  });
}

/* ---------- HUD ---------- */
const el = id => document.getElementById(id);
let capFadeT = null;
function fadeCaption(write) {
  // A hard text swap mid-shot reads as a glitch; a short crossfade reads
  // as a cut. Respect reduced motion by just writing.
  const k = el("kicker"), c = el("caption");
  if (REDUCED || !k || !c) { write(); return; }
  k.style.opacity = c.style.opacity = "0";
  clearTimeout(capFadeT);
  capFadeT = setTimeout(() => {
    write();
    k.style.opacity = c.style.opacity = "1";
  }, 180);
}

function applyScene(i) {
  if (inspecting) return;    // inspect owns the HUD while it is open
  const s = SCENES[i];
  window.__AT3 = Object.assign(window.__AT3 || {},
    { SCENES, P, sceneI: i, D });
  fadeCaption(() => {
    el("kicker").textContent = s.kicker;
    el("caption").innerHTML = typeof s.cap === "function" ? s.cap() : s.cap;
  });
  el("sceneno").textContent =
    String(i + 1).padStart(2, "0") + " / " + String(SCENES.length).padStart(2, "0");
  const st = s.stat ? s.stat() : ["", ""];
  el("statn").textContent = st[0];
  el("statl").textContent = st[1];
  // Announce the scene to assistive tech. Without this the whole piece
  // is a silent canvas.
  const liveEl = el("live");
  if (liveEl) {
    const plain = (typeof s.cap === "function" ? s.cap() : s.cap)
      .replace(/<[^>]+>/g, "");
    liveEl.textContent = `Scene ${i + 1} of ${SCENES.length}. ` +
      `${s.kicker}. ${plain}`;
  }
  el("chips").innerHTML = D.profiles.map(p => {
    const on = s.profile === p.name;
    return `<span class="chip${on ? " on" : ""}">
      <i style="background:${p.c}"></i>${p.label}
      <b>${(s.id === "fix" ? p.after_pct : p.pct)}%</b></span>`;
  }).join("");
  clearMarkers();
  resetWalks(s);
  userCam = false;
  sliderTouched = false;
  roomLabels.visible = true;
  if (!s.materials) {
    surfGroup.visible = false;
    const wc = el("widthcard");
    wc.querySelector("h3").textContent = "Body width";
    wc.querySelector(".wrow").hidden = false;
  }
  if (s.id !== "choke") {
    cpGroup.visible = false;
    el("cpsum").hidden = true;
    hideChokepoint();
  }
  if (!s.slider) {
    el("widthcard").hidden = true;
    roomGroup.visible = false;
  }
  if (s.enter) s.enter();
  syncNav();
}

/* ---------- loop ---------- */
let sceneI = 0, sceneT = 0, playing = true, clock = 0, last = 0;
let sliderTouched = false;
/* Honour a stated preference for reduced motion: the camera stops
   drifting and the markers stop pulsing. The walkthrough still plays,
   because the content IS the motion -- what goes is the decoration. */
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const TOTAL = SCENES.reduce((a, s) => a + s.dur, 0);

function goto(i) {
  sceneI = (i + SCENES.length) % SCENES.length;
  sceneT = 0;
  applyScene(sceneI);
}

function resize() {
  const w = stage.clientWidth, h = stage.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

let slowFrames = 0;

function frame(ts) {
  requestAnimationFrame(frame);
  if (!last) last = ts;
  const raw = (ts - last) / 1000;
  const dt = Math.min(0.05, raw);
  last = ts; clock += dt;

  // Sustained slow frames: shed pixels rather than drop the walkthrough
  // to a slideshow. Once only -- oscillating between two resolutions
  // looks worse than either.
  if (raw > 0.045 && pixelCap > 1) {
    if (++slowFrames > 90) {
      pixelCap = 1;
      renderer.setPixelRatio(1);
      resize();
      slowFrames = 0;
    }
  } else if (slowFrames > 0) { slowFrames--; }

  const s = SCENES[sceneI];
  if (playing && !inspecting) {
    sceneT += dt;
    // A throw inside a scene tick used to strand the whole walkthrough on
    // one scene: rAF was already re-armed, so the loop survived but never
    // reached the advance below. Failures are now contained per-scene and
    // reported once instead of silently freezing the demo.
    try {
      if (s.tick && !userCam && !REDUCED) s.tick(sceneT);
      else if (s.tick && !userCam && REDUCED && sceneT < 0.1) s.tick(0);
      stepWalks(s, sceneT, dt);
    } catch (err) {
      if (!s._warned) { s._warned = 1; console.error("scene", s.id, err); }
    }
    if (sceneT >= s.dur) goto(sceneI + 1);
  }

  // camera easing
  const k = 1 - Math.pow(0.0016, dt);
  camState.pos.lerp(camGoal.pos, k);
  camState.tgt.lerp(camGoal.tgt, k);
  camera.position.copy(camState.pos);
  camera.lookAt(camState.tgt);

  if (routeMat && routeMat.map) routeMat.map.offset.x -= dt * 0.42;

  if (inspecting && !REDUCED) {
    isGroup.children.forEach(g => {
      if (g.userData.idx === isSel) {
        g.userData.knob.position.y = 2.15 + Math.sin(clock * 3.2) * 0.09;
      }
    });
  }

  markers.children.forEach(m => {
    const age = clock - m.userData.born;
    const p = m.userData.pulse;
    if (p && !REDUCED) { const q = 1 + Math.sin(clock * 3) * 0.12; p.scale.set(q, q, 1); }
    m.children.forEach(c => {
      if (c.isSprite) c.material.opacity = Math.min(1, age * 2.5);
    });
  });

  // progress bar
  let acc = 0;
  for (let i = 0; i < sceneI; i++) acc += SCENES[i].dur;
  el("bar").style.width = ((acc + sceneT) / TOTAL * 100).toFixed(2) + "%";

  renderer.render(scene, camera);
}

/* ---------- controls ---------- */
el("play").addEventListener("click", () => {
  playing = !playing;
  el("play").textContent = playing ? "Pause" : "Play";
});
el("restart").addEventListener("click", () => goto(0));
el("inspect").addEventListener("click", () => setInspect(!inspecting));

/* The chevrons do whatever "next" means where you are: the next scene
   in the walkthrough, the next issue in the audit. */
function step(dir) {
  if (inspecting) {
    const vis = [...el("islist").querySelectorAll("button[data-i]")]
      .map(b => Number(b.dataset.i));
    if (!vis.length) return;
    const at = vis.indexOf(isSel);
    selectIssue(dir > 0
      ? vis[(at + 1) % vis.length]
      : vis[(at <= 0 ? vis.length : at) - 1]);
  } else {
    goto(sceneI + dir);
  }
  syncNav();
}
function syncNav() {
  const hint = el("navhint");
  if (!hint) return;
  if (inspecting) {
    const n = ISSUES.length;
    const at = isSel === null ? 0 : isSel + 1;
    hint.textContent = `next issue · ${at}/${n}`;
  } else {
    hint.textContent = `next · ${sceneI + 2 > SCENES.length ? 1 : sceneI + 2}` +
      `/${SCENES.length}`;
  }
}
el("navnext").addEventListener("click", () => step(1));
el("navprev").addEventListener("click", () => step(-1));
el("iscopy").addEventListener("click", async () => {
  // A worklist you cannot get out of the page is a demo, not a tool.
  const esc = v => `"${String(v).replace(/"/g, '""')}"`;
  const csv = [["verdict", "room", "issue", "cost_usd", "excludes",
                "position_x_m", "position_y_m"].join(",")]
    .concat(ISSUES.map(it => [
      it.verdict, it.room || "", it.detail, it.cost,
      (it.excludes || []).map(n => (P[n] && P[n].label) || n).join("; "),
      it.pos[0], it.pos[1]].map(esc).join(",")))
    .join("\n");
  try {
    await navigator.clipboard.writeText(csv);
    el("iscopy").textContent = "Copied";
  } catch (err) {
    el("iscopy").textContent = "Press ⌘C";
    const ta = document.createElement("textarea");
    ta.value = csv; document.body.appendChild(ta); ta.select();
  }
  setTimeout(() => { el("iscopy").textContent = "Copy"; }, 1800);
});
el("ispanel").querySelectorAll(".isfilters button").forEach(b =>
  b.addEventListener("click", () => {
    if (!b.dataset.f) return;
    isFilter = b.dataset.f;
    el("ispanel").querySelectorAll(".isfilters button")
      .forEach(x => x.classList.toggle("on", x === b));
    renderIssueList();
  }));
el("cpclose").addEventListener("click", hideChokepoint);
el("widthslider").addEventListener("input", e => {
  sliderTouched = true;
  applyWidth(Number(e.target.value));
});
el("prev").addEventListener("click", () => goto(sceneI - 1));
el("next").addEventListener("click", () => goto(sceneI + 1));
addEventListener("keydown", e => {
  if (e.key === " ") { e.preventDefault(); goto(0); }
  if (e.key === "ArrowRight") { e.preventDefault(); goto(sceneI + 1); }
  if (e.key === "ArrowLeft") { e.preventDefault(); goto(sceneI - 1); }
  if (e.key.toLowerCase() === "p") { el("play").click(); }
  if (e.key === "Escape") { hideChokepoint(); if (inspecting) setInspect(false); }
  if (e.key.toLowerCase() === "i") { e.preventDefault(); setInspect(!inspecting); }
  if (inspecting) {
    // Step the worklist from the keyboard: useful when presenting, and
    // the only way to reach the issues without a mouse.
    const vis = [...el("islist").querySelectorAll("button[data-i]")]
      .map(b => Number(b.dataset.i));
    if (!vis.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      e.preventDefault();
      const at = vis.indexOf(isSel);
      selectIssue(vis[(at + 1) % vis.length]);
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      e.preventDefault();
      const at = vis.indexOf(isSel);
      selectIssue(vis[(at <= 0 ? vis.length : at) - 1]);
    }
    return;
  }
  // Number keys jump straight to a scene. Three minutes is longer than
  // most demo slots, and hunting with the arrow keys on stage is worse
  // than not showing the scene at all.
  if (/^[1-9]$/.test(e.key)) {
    e.preventDefault();
    goto(Number(e.key) - 1);
  }
  if (e.key === "0") { e.preventDefault(); goto(9); }
});
addEventListener("resize", resize);

/* requestAnimationFrame is suspended entirely in a background tab, so a
   presenter who alt-tabs away comes back to a walkthrough frozen
   mid-scene. Restart the clock on return rather than letting one
   enormous delta jump the scene. */
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    last = 0;
    camState.pos.copy(camGoal.pos);
    camState.tgt.copy(camGoal.tgt);
  }
});
const mo = () => { tokens(); buildMaterials(); applyEnv();
  buildRoomLabels(); applyScene(sceneI); };
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", mo);
new MutationObserver(mo).observe(document.documentElement,
  { attributes: true, attributeFilter: ["data-theme"] });

/* Manual driver. requestAnimationFrame is suspended in a background
   tab, so automated capture cannot rely on the render loop. This
   advances the walkthrough by an explicit timestep and forces a draw,
   which is also how the still frames for the write-up are produced. */
window.__AT3 = Object.assign(window.__AT3 || {}, {
  showCP: showChokepoint,
  camera: camera,
  renderer: renderer,
  scene: scene,
  seek(index, seconds, dt) {
    goto(index);   // NB: not named `scene` -- that shadows the THREE.Scene
    const h = dt || 1 / 60;
    for (let t = 0; t < seconds; t += h) {
      clock += h;
      sceneT += h;
      try {
        if (SCENES[sceneI].tick) SCENES[sceneI].tick(sceneT);
        stepWalks(SCENES[sceneI], sceneT, h);
      } catch (err) { console.error("seek", err); }
    }
    camState.pos.copy(camGoal.pos);
    camState.tgt.copy(camGoal.tgt);
    camera.position.copy(camState.pos);
    camera.lookAt(camState.tgt);
    renderer.render(scene, camera);
    return SCENES[sceneI].kicker;
  }
});

/* A text equivalent of every finding, so the piece is usable without
   seeing or operating the 3D view at all. */
(function transcript() {
  const t = el("txbody");
  if (!t) return;
  const esc = x => String(x).replace(/[&<>]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const cov = D.profiles.map(p =>
    `<li>${esc(p.label)}: reaches ${p.pct}% of the floor, ` +
    `${Object.values(p.journeys).filter(j => j.arrived).length} of ` +
    `${Object.keys(p.journeys).length} destinations` +
    (p.island_m2 ? `, ${p.island_m2} m² stranded` : "") + `</li>`).join("");
  const cps = (D.chokepoints || []).map(c =>
    `<li>${esc(c.detail)} — ${c.verdict === "move" ? "no cost, relocate contents"
      : "$" + c.cost.toLocaleString()}` +
    (c.excludes && c.excludes.length
      ? `; excludes ${esc(c.excludes.map(n => (P[n] && P[n].label) || n)
        .join(", "))}` : "") + `</li>`).join("");
  const rec = D.recall || {};
  t.innerHTML =
    `<h5>Who reaches what</h5><ul>${cov}</ul>` +
    `<h5>Detection</h5><ul><li>${rec.detected} of ${rec.planted} planted ` +
    `defects recovered by an analysis never told where to look</li></ul>` +
    `<h5>Blockages and what they cost</h5><ul>${cps}</ul>` +
    `<p style="margin-top:10px;color:var(--ink-3);font-size:11.5px">` +
    `Costs are illustrative order-of-magnitude figures, not quotes.</p>`;
})();

el("meta").textContent =
  `seed ${D.seed} · ${BW}×${BH} m · ${(D.grid.cell * 100).toFixed(0)} cm voxels · ` +
  `${D.solids.length} solids`;

resize();
goto(0);
// Open on the worklist, not the film. The walkthrough answers "how do
// you know"; the audit is the thing somebody came for, and a judge who
// only looks for ten seconds should land on findings rather than on an
// establishing shot.
// #walkthrough opens the film instead of the audit, so either view can
// be shared as a link.
const wantsWalk = location.hash.toLowerCase().indexOf("walk") >= 0;
setInspect(!wantsWalk);
if (wantsWalk) playing = true;
// One synchronous draw before the spinner goes, so the first thing the
// viewer sees is the building rather than a flash of empty stage.
renderer.render(scene, camera);
if (el0("boot")) el0("boot").hidden = true;

/* A first-time viewer lands on a panel of numbers with no idea what
   building this is or why it is being audited. One card, two doors. */
(function intro() {
  const box = el0("intro");
  if (!box || wantsWalk) return;
  box.hidden = false;
  playing = false;
  const close = walk => {
    box.hidden = true;
    if (walk) { setInspect(false); playing = true; goto(0); }
    else { playing = false; }
  };
  el0("introaudit").addEventListener("click", () => close(false));
  el0("introwalk").addEventListener("click", () => close(true));
  box.addEventListener("click", e => { if (e.target === box) close(false); });
  addEventListener("keydown", function esc(e) {
    if (e.key === "Escape" && !box.hidden) { close(false); }
  });
  el0("introaudit").focus();
})();
requestAnimationFrame(frame);
