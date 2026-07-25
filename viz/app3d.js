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
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
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
const hemi = new THREE.HemisphereLight(0xffffff, 0x404852, 1.5);
scene.add(hemi);
const key = new THREE.DirectionalLight(0xffffff, 2.1);
key.position.set(18, 26, -6);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.near = 1;
key.shadow.camera.far = 90;
const SH = 26;
Object.assign(key.shadow.camera, { left: -SH, right: SH, top: SH, bottom: -SH });
key.shadow.bias = -0.0009;
key.shadow.normalBias = 0.02;
key.target.position.copy(CTR);
scene.add(key, key.target);
const fill = new THREE.DirectionalLight(0xbcd0e0, 0.45);
fill.position.set(-14, 12, 20);
scene.add(fill);

/* ---------- materials ---------- */
const MAT = {};
function buildMaterials() {
  const mk = (col, rough, metal, extra) => new THREE.MeshStandardMaterial(
    Object.assign({ color: new THREE.Color(col), roughness: rough,
                    metalness: metal || 0 }, extra || {}));
  MAT.wall = mk(TOK.wall, 0.94, 0);
  MAT.floor = mk(TOK.floor, 0.96, 0);
  MAT.gallery = mk(TOK.gallery, 0.9, 0);
  MAT.ramp = mk(TOK.ramp, 0.85, 0);
  MAT.concrete = mk(TOK.concrete, 0.92, 0);
  MAT.timber = mk(TOK.timber, 0.7, 0);
  MAT.fabric = mk(TOK.fabric, 1.0, 0);
  MAT.porcelain = mk(TOK.porcelain, 0.25, 0);
  MAT.steel = mk(TOK.steel, 0.3, 0.85);
  MAT.soffit = mk(TOK.soffit, 0.9, 0);
  MAT.parapet = mk(TOK.parapet, 0.9, 0);
  MAT.header = mk(TOK.wall, 0.94, 0);
  MAT.glass = mk(TOK.glass, 0.12, 0, {
    transparent: true, opacity: 0.22, side: THREE.DoubleSide });
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
function buildSolids() {
  D.solids.forEach(s => {
    const w = s.x1 - s.x0, d = s.y1 - s.y0, h = s.z1 - s.z0;
    if (w <= 0 || d <= 0 || h <= 0) return;
    const mat = MAT[s.material] || MAT.wall;
    let mesh;
    if (s.kind === "ramp") {
      mesh = new THREE.Mesh(rampGeometry(w, d, s.rz0, s.rz1, s.axis), mat);
      mesh.position.copy(v3(s.x0 + w / 2, s.y0 + d / 2, s.z0));
    } else {
      mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      mesh.position.copy(v3(s.x0 + w / 2, s.y0 + d / 2, s.z0 + h / 2));
    }
    mesh.castShadow = s.kind !== "slab";
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
[[0.012, 0, 0, BW, BH], [0.612, 19.0, 13.2, 12.8, 8.6]].forEach(
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

/* ---------- agents ---------- */
function makeAgent(profile) {
  const g = new THREE.Group();
  const col = new THREE.Color(profile.c);
  const skin = new THREE.MeshStandardMaterial({ color: col, roughness: 0.55 });
  const dark = new THREE.MeshStandardMaterial({
    color: col.clone().multiplyScalar(0.55), roughness: 0.7 });
  const metal = new THREE.MeshStandardMaterial({
    color: 0xb9c3cb, roughness: 0.35, metalness: 0.8 });
  const parts = {};

  const torso = (h, r) => new THREE.Mesh(
    new THREE.CapsuleGeometry(r, h, 4, 12), skin);

  if (profile.body === "wheelchair") {
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.52, 0.1, 0.5), dark);
    seat.position.y = 0.50; g.add(seat);
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.52, 0.5, 0.08), dark);
    back.position.set(0, 0.75, -0.21); g.add(back);
    const t = torso(0.42, 0.17); t.position.set(0, 0.80, 0.02); g.add(t);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.115, 20, 14), skin);
    head.position.set(0, 1.11, 0.02); g.add(head);
    const wheelG = new THREE.TorusGeometry(0.30, 0.035, 10, 26);
    parts.wheels = [];
    [-0.30, 0.30].forEach(sx => {
      const wm = new THREE.Mesh(wheelG, metal);
      wm.position.set(sx, 0.30, -0.04);
      wm.rotation.y = Math.PI / 2;
      g.add(wm); parts.wheels.push(wm);
    });
    [-0.22, 0.22].forEach(sx => {
      const c = new THREE.Mesh(new THREE.TorusGeometry(0.09, 0.025, 8, 16), metal);
      c.position.set(sx, 0.09, 0.30); c.rotation.y = Math.PI / 2; g.add(c);
      parts.wheels.push(c);
    });
    parts.eyeH = 1.15;
  } else if (profile.body === "robot") {
    const b = new THREE.Mesh(new THREE.BoxGeometry(0.60, 0.55, 0.78), skin);
    b.position.y = 0.42; g.add(b);
    const lid = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.07, 0.80), dark);
    lid.position.y = 0.73; g.add(lid);
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.34), metal);
    mast.position.set(0, 0.9, -0.28); g.add(mast);
    const flag = new THREE.Mesh(new THREE.SphereGeometry(0.05, 12, 10), dark);
    flag.position.set(0, 1.08, -0.28); g.add(flag);
    parts.wheels = [];
    [[-0.31, 0.26], [0.31, 0.26], [-0.31, -0.26], [0.31, -0.26]].forEach(
      ([sx, sz]) => {
        const wm = new THREE.Mesh(
          new THREE.CylinderGeometry(0.15, 0.15, 0.07, 16), metal);
        wm.position.set(sx, 0.15, sz); wm.rotation.z = Math.PI / 2;
        g.add(wm); parts.wheels.push(wm);
      });
    parts.eyeH = 0.95;
  } else {
    const t = torso(0.52, 0.16); t.position.y = 1.06; g.add(t);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.12, 20, 14), skin);
    head.position.y = 1.51; g.add(head);
    parts.legs = [];
    [-0.11, 0.11].forEach(sx => {
      const l = new THREE.Mesh(new THREE.CapsuleGeometry(0.065, 0.52, 4, 10), dark);
      l.position.set(sx, 0.42, 0);
      l.geometry.translate(0, -0.26, 0);
      l.position.y = 0.72;
      g.add(l); parts.legs.push(l);
    });
    parts.arms = [];
    [-0.24, 0.24].forEach(sx => {
      const a = new THREE.Mesh(new THREE.CapsuleGeometry(0.05, 0.40, 4, 10), skin);
      a.geometry.translate(0, -0.20, 0);
      a.position.set(sx, 1.30, 0);
      g.add(a); parts.arms.push(a);
    });
    if (profile.body === "cane") {
      const cane = new THREE.Mesh(
        new THREE.CylinderGeometry(0.014, 0.014, 1.15, 8),
        new THREE.MeshStandardMaterial({ color: 0xf2f4f6, roughness: 0.5 }));
      cane.geometry.translate(0, -0.575, 0);
      cane.position.set(0.24, 1.10, 0.05);
      cane.rotation.x = -0.28;
      g.add(cane); parts.cane = cane;
      // The 42-inch sweep arc: this profile's real footprint, and the
      // reason it is the widest body in the population.
      const arc = new THREE.Mesh(
        new THREE.RingGeometry(0.12, profile.width_in * 0.0254 / 2, 40, 1,
                               -0.75, 1.5),
        new THREE.MeshBasicMaterial({
          color: col, transparent: true, opacity: 0.20,
          side: THREE.DoubleSide, depthWrite: false }));
      arc.rotation.x = -Math.PI / 2;
      arc.position.y = 0.02;
      g.add(arc); parts.arc = arc;
    }
    parts.eyeH = 1.55;
  }

  // Footprint ring: the body envelope the analysis actually used.
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(profile.width_in * 0.0254 / 2 - 0.03,
                           profile.width_in * 0.0254 / 2, 44),
    new THREE.MeshBasicMaterial({ color: col, transparent: true,
                                  opacity: 0.75, side: THREE.DoubleSide,
                                  depthWrite: false }));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.015;
  g.add(ring);
  parts.ring = ring;

  g.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
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

function placeAgent(profile, sample, t) {
  const g = profile.agent, P = g.userData.parts;
  g.visible = true;
  g.position.copy(v3(sample.p[0], sample.p[1], sample.p[2]));
  const yaw = Math.atan2(sample.dir[0], sample.dir[1]);
  g.rotation.y = yaw;
  const moving = sample.moving !== false;
  if (P.wheels) P.wheels.forEach(w => { if (moving) w.rotation.x -= 0.16; });
  if (P.legs) {
    const s = moving ? Math.sin(t * 9) : 0;
    P.legs[0].rotation.x = s * 0.55;
    P.legs[1].rotation.x = -s * 0.55;
    if (P.arms) { P.arms[0].rotation.x = -s * 0.4; P.arms[1].rotation.x = s * 0.4; }
  }
  if (P.cane) P.cane.rotation.z = Math.sin(t * 4.2) * 0.5;
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

/* ---------- scene script ---------- */
const P = {};
D.profiles.forEach(p => P[p.name] = p);
const REC = D.recall, OPT = D.remediation, POP = D.population;
const BPs = D.breaking_point.community_room || Object.values(D.breaking_point)[0];
const chosen = OPT.chosen[0];
const rejected = (OPT.rejected || []).filter(r => chosen && r.cost > chosen.cost)
  .sort((a, b) => b.cost - a.cost)[0];
const n0 = (v, d) => Number(v).toFixed(d == null ? 0 : d);

function journeyOf(pname, goal) { return P[pname].journeys[goal]; }

const SCENES = [
  {
    id: "establish", dur: 8.0, kicker: "The building",
    cap: `A generated civic centre — lobby, café, spine corridor, community
          room, accessible WC and a raised gallery. It is drawn to code.
          <em>Eight access defects are planted in it</em>, and every one of them
          is a condition that passes a plan check.`,
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
    id: "cutaway", dur: 6.0, kicker: "Section",
    cap: `Same building, walls cut down to knee height so we can watch what
          happens inside. Four bodies are about to walk it: a walking adult,
          a wheelchair user, a cane user, and a delivery robot.
          <em>Only their dimensions differ.</em>`,
    stat: () => ["4", "body envelopes tested"],
    enter() { hideAgents(); decalGroup.visible = false; },
    tick(t) {
      setWallCut(1.0 - 0.78 * Math.min(1, t / 2.2));
      lookAt(BW / 2 - 4, -14, 26 - t * 1.2, BW / 2, BH / 2, 0.8);
    }
  },
  {
    id: "walker", dur: 12.0, kicker: "Walking adult", profile: "baseline_walking",
    cap: `A walking adult reaches <em>every room in the building</em> —
          ${n0(P.baseline_walking.reach_m2, 0)} m², 100% of the floor.
          The community room, the gallery, the WC: all connected.
          This is the building as its drawings describe it.`,
    stat: () => ["100%", "of the floor reached"],
    walk: [["baseline_walking", "community_room", 0], ["baseline_walking", "gallery", 5.2]],
    enter() { hideAgents(); decalGroup.visible = false; setWallCut(0.22); },
    tick(t) { follow("baseline_walking", t, 16, -6, 9); }
  },
  {
    id: "chair-room", dur: 12.5, kicker: "Wheelchair · community room",
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
    id: "chair-gallery", dur: 12.0, kicker: "Wheelchair · gallery",
    profile: "wheelchair",
    cap: `The gallery has a ramp, so it looks solved. The ramp is built at
          <em>1:6.7</em> where the code allows 1:12, and the only other way up
          is a four-riser stair. The wheelchair gets to the bottom of the ramp
          and <em>that is as far as the building lets it go</em>.`,
    stat: () => [n0(P.wheelchair.island_m2, 0) + " m²", "stranded from this body"],
    walk: [["wheelchair", "gallery", 0]],
    enter() { hideAgents(); decalGroup.visible = false; setWallCut(0.22); },
    tick(t) { follow("wheelchair", t, 10, 6, 7); },
    onStop(pname, goal) {
      (journeyOf(pname, goal).barriers || []).slice(0, 2).forEach(b => {
        addMarker(b.pos[0], b.pos[1], b.pos[2],
          b.kind === "slope_gradient" ? `1:${n0(1 / Math.max(b.slope, 1e-3))}`
            : `${n0(b.step_in, 1)}" step`,
          b.kind === "slope_gradient" ? "needs 1:12 — ADA 405.2"
            : "needs ½\" — ADA 303.2", TOK.bad);
      });
    }
  },
  {
    id: "islands", dur: 10.0, kicker: "The finding",
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
    id: "cane", dur: 11.0, kicker: "Cane user · WC", profile: "vision_impaired_cane",
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
    id: "robot", dur: 10.0, kicker: "Delivery robot",
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
    id: "heat", dur: 9.0, kicker: "Exclusion map",
    cap: `All four bodies at once — every square metre coloured by
          <em>how many of them can stand on it</em>. Teal is universal, red is
          walking-adult only. The building is not accessible or inaccessible;
          it is accessible to a shrinking subset as bodies get wider.`,
    stat: () => [n0(100 - POP.pct_full_access, 0) + "%",
                 "of a mobility population excluded"],
    enter() {
      hideAgents(); clearMarkers();
      decalGroup.visible = true; paintDecal("heat", null, false);
      setWallCut(0.16);
      lookAt(BW / 2, -6, 34, BW / 2, BH / 2, 0);
    },
    tick(t) {
      lookAt(BW / 2 + Math.sin(t * 0.28) * 8, -6 + t * 0.3, 34,
             BW / 2, BH / 2, 0);
    }
  },
  {
    id: "fix", dur: 12.0, kicker: "Cheapest repair",
    cap: chosen ? `Every candidate repair is scored by <em>rebuilding the
          building and re-running the whole population through it</em>. With
          $${OPT.budget_usd.toLocaleString()}, the optimum is
          <em>$${chosen.cost.toLocaleString()}</em> — ${chosen.detail} —
          taking population access from ${OPT.before.pct_full_access}% to
          <em>${OPT.after.pct_full_access}%</em>.${rejected ?
          ` The obvious fix at $${rejected.cost.toLocaleString()} was measured
          and rejected.` : ""}`
      : "No single repair improved measured population coverage.",
    stat: () => chosen
      ? ["+" + n0(OPT.coverage_gain_pct, 1) + " pts", "for $" + OPT.spent_usd.toLocaleString()]
      : ["—", ""],
    enter() {
      hideAgents(); clearMarkers();
      decalGroup.visible = true; paintDecal("heat", null, false);
      OPT.chosen.forEach(f => addMarker(f.pos[0], f.pos[1], 0,
        "$" + f.cost.toLocaleString(), f.detail, TOK.ok));
      (OPT.rejected || []).slice(0, 3).forEach(f => addMarker(
        f.pos[0], f.pos[1], 0, "$" + f.cost.toLocaleString(),
        "rejected — " + n0(f.pct_per_1k_usd, 1) + " pts/$1k", TOK.warn));
      lookAt(BW / 2, -8, 30, BW / 2, BH / 2, 0);
    },
    tick(t) {
      // Halfway through, apply the fixes and show the floor change.
      paintDecal("heat", null, t > this.dur * 0.55);
    }
  },
  {
    id: "truth", dur: 10.0, kicker: "Scored against truth",
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

/* Follow the agent that is currently walking, from behind and above. */
function follow(pname, t, back, side, up) {
  back *= 0.62; side *= 0.62; up *= 0.72;
  const p = P[pname];
  const st = p._walkState;
  if (!st || !st.sample) return;
  const s = st.sample;
  const dx = s.dir[0], dy = s.dir[1];
  lookAt(s.p[0] - dx * back + dy * side, s.p[1] - dy * back - dx * side,
         s.p[2] + up, s.p[0] + dx * 2, s.p[1] + dy * 2, s.p[2] + 0.9);
}

/* ---------- walking engine ---------- */
function resetWalks(sc) {
  D.profiles.forEach(p => { p._walkState = null; });
  clearRoute();
  if (!sc.walk) return;
  sc.walk.forEach(([pname, goal, delay]) => {
    const p = P[pname], j = p.journeys[goal];
    p._walkState = {
      goal, delay, j, len: pathLength(j.path), s: 0,
      done: false, stopped: false, sample: null
    };
  });
}

function stepWalks(sc, t, dt) {
  if (!sc.walk) return;
  sc.walk.forEach(([pname, goal, delay]) => {
    const p = P[pname], st = p._walkState;
    if (!st || st.goal !== goal) return;
    if (t < delay) { p.agent.visible = false; return; }
    if (!st.drawn) { st.drawn = true; drawRoute(st.j.path, p.c, st.j.arrived); }
    const sp = SPEED[p.body] || 1.2;
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
    placeAgent(p, sample, t);
  });
}

/* ---------- HUD ---------- */
const el = id => document.getElementById(id);
function applyScene(i) {
  const s = SCENES[i];
  el("kicker").textContent = s.kicker;
  el("caption").innerHTML = typeof s.cap === "function" ? s.cap() : s.cap;
  el("sceneno").textContent =
    String(i + 1).padStart(2, "0") + " / " + String(SCENES.length).padStart(2, "0");
  const st = s.stat ? s.stat() : ["", ""];
  el("statn").textContent = st[0];
  el("statl").textContent = st[1];
  el("chips").innerHTML = D.profiles.map(p => {
    const on = s.profile === p.name;
    return `<span class="chip${on ? " on" : ""}">
      <i style="background:${p.c}"></i>${p.label}
      <b>${(s.id === "fix" ? p.after_pct : p.pct)}%</b></span>`;
  }).join("");
  clearMarkers();
  resetWalks(s);
  userCam = false;
  if (s.enter) s.enter();
}

/* ---------- loop ---------- */
let sceneI = 0, sceneT = 0, playing = true, clock = 0, last = 0;
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

function frame(ts) {
  requestAnimationFrame(frame);
  if (!last) last = ts;
  const dt = Math.min(0.05, (ts - last) / 1000);
  last = ts; clock += dt;

  const s = SCENES[sceneI];
  if (playing) {
    sceneT += dt;
    if (s.tick && !userCam) s.tick(sceneT);
    stepWalks(s, sceneT, dt);
    if (sceneT >= s.dur) goto(sceneI + 1);
  }

  // camera easing
  const k = 1 - Math.pow(0.0016, dt);
  camState.pos.lerp(camGoal.pos, k);
  camState.tgt.lerp(camGoal.tgt, k);
  camera.position.copy(camState.pos);
  camera.lookAt(camState.tgt);

  if (routeMat && routeMat.map) routeMat.map.offset.x -= dt * 0.42;

  markers.children.forEach(m => {
    const age = clock - m.userData.born;
    const p = m.userData.pulse;
    if (p) { const q = 1 + Math.sin(clock * 3) * 0.12; p.scale.set(q, q, 1); }
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
el("prev").addEventListener("click", () => goto(sceneI - 1));
el("next").addEventListener("click", () => goto(sceneI + 1));
addEventListener("keydown", e => {
  if (e.key === " ") { e.preventDefault(); goto(0); }
  if (e.key === "ArrowRight") { e.preventDefault(); goto(sceneI + 1); }
  if (e.key === "ArrowLeft") { e.preventDefault(); goto(sceneI - 1); }
  if (e.key.toLowerCase() === "p") { el("play").click(); }
});
addEventListener("resize", resize);
const mo = () => { tokens(); buildMaterials(); applyEnv();
  buildRoomLabels(); applyScene(sceneI); };
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", mo);
new MutationObserver(mo).observe(document.documentElement,
  { attributes: true, attributeFilter: ["data-theme"] });

el("meta").textContent =
  `seed ${D.seed} · ${BW}×${BH} m · ${(D.grid.cell * 100).toFixed(0)} cm voxels · ` +
  `${D.solids.length} solids`;

resize();
goto(0);
requestAnimationFrame(frame);
