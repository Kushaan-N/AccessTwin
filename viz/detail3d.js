/* ============================================================
   Access-Twin — surface detail, furnishing and figures.

   Everything here is procedural. No texture downloads, no asset
   packs: the page has to stay a single self-contained file that
   runs under a strict CSP, so every map is painted into a canvas
   at load and every object is assembled from primitives.

   Three things are doing the heavy lifting for realism:
     1. image-based lighting from a PMREM-filtered room, so
        surfaces pick up directional bounce instead of flat ambient
     2. albedo + matching normal maps, so flat planes stop reading
        as flat planes
     3. furniture with legs, thickness and gaps, because a table
        rendered as a solid cube is the single strongest "this is
        programmer art" signal in the scene
   ============================================================ */

/* ---------------- procedural texture kit ---------------- */

function noiseCanvas(size, fn) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const img = g.createImageData(size, size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const o = (y * size + x) * 4;
      const v = fn(x, y);
      img.data[o] = img.data[o + 1] = img.data[o + 2] = v;
      img.data[o + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  return c;
}

/* Deterministic value noise -- a seeded hash rather than Math.random,
   so the build is byte-identical every time it is generated. */
function hash2(x, y, s) {
  let h = x * 374761393 + y * 668265263 + s * 1442695040;
  h = (h ^ (h >> 13)) * 1274126177;
  return ((h ^ (h >> 16)) >>> 0) / 4294967295;
}
function smoothNoise(x, y, scale, s) {
  const xi = Math.floor(x / scale), yi = Math.floor(y / scale);
  const tx = (x / scale) - xi, ty = (y / scale) - yi;
  const f = t => t * t * (3 - 2 * t);
  const a = hash2(xi, yi, s), b = hash2(xi + 1, yi, s);
  const c = hash2(xi, yi + 1, s), d = hash2(xi + 1, yi + 1, s);
  return (a + (b - a) * f(tx)) * (1 - f(ty)) + (c + (d - c) * f(tx)) * f(ty);
}
function fbm(x, y, s, octaves) {
  let v = 0, amp = 0.5, sc = 32;
  for (let i = 0; i < (octaves || 4); i++) {
    v += smoothNoise(x, y, sc, s + i) * amp;
    sc /= 2; amp /= 2;
  }
  return v;
}

/* Turn a height canvas into a tangent-space normal map by finite
   differences. Cheaper and more controllable than shipping one. */
function normalFromHeight(heightCanvas, strength) {
  const size = heightCanvas.width;
  const src = heightCanvas.getContext("2d")
    .getImageData(0, 0, size, size).data;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const img = g.createImageData(size, size);
  const at = (x, y) => src[(((y + size) % size) * size +
    ((x + size) % size)) * 4] / 255;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (at(x - 1, y) - at(x + 1, y)) * strength;
      const dy = (at(x, y - 1) - at(x, y + 1)) * strength;
      const len = Math.hypot(dx, dy, 1);
      const o = (y * size + x) * 4;
      img.data[o] = ((dx / len) * 0.5 + 0.5) * 255;
      img.data[o + 1] = ((dy / len) * 0.5 + 0.5) * 255;
      img.data[o + 2] = ((1 / len) * 0.5 + 0.5) * 255;
      img.data[o + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  return c;
}

function makeSurface(THREE, kind, repeat) {
  const S = 256;
  let height;
  if (kind === "wood") {
    // Grain: stretched noise banded along one axis, plus fine fibre.
    height = noiseCanvas(S, (x, y) => {
      const grain = Math.sin((x * 0.35 + fbm(x, y * 6, 11, 3) * 26)) * 0.5 + 0.5;
      return 150 + grain * 60 + fbm(x * 3, y, 5, 2) * 24;
    });
  } else if (kind === "concrete") {
    height = noiseCanvas(S, (x, y) => {
      const n = fbm(x, y, 3, 5);
      const pit = hash2(x, y, 9) > 0.995 ? -40 : 0;
      return 150 + n * 70 + pit;
    });
  } else if (kind === "plaster") {
    height = noiseCanvas(S, (x, y) => 175 + fbm(x, y, 21, 4) * 34);
  } else if (kind === "fabric") {
    // Weave: alternating warp and weft.
    height = noiseCanvas(S, (x, y) => {
      const w = (Math.sin(x * 1.6) * Math.sin(y * 1.6)) * 0.5 + 0.5;
      return 140 + w * 70 + fbm(x, y, 7, 2) * 20;
    });
  } else if (kind === "tile") {
    // Large-format floor tile: flat fields separated by grout lines.
    height = noiseCanvas(S, (x, y) => {
      const gx = (x % 128) < 3 || (y % 128) < 3;
      return gx ? 70 : 180 + fbm(x, y, 13, 3) * 26;
    });
  } else {
    height = noiseCanvas(S, (x, y) => 170 + fbm(x, y, 17, 3) * 30);
  }

  const albedo = new THREE.CanvasTexture(height);
  const normal = new THREE.CanvasTexture(
    normalFromHeight(height, kind === "tile" ? 3.5 : 1.6));
  [albedo, normal].forEach(t => {
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(repeat || 4, repeat || 4);
    t.anisotropy = 8;
  });
  albedo.colorSpace = THREE.SRGBColorSpace;
  return { map: albedo, normalMap: normal };
}

/* ---------------- image-based lighting ---------------- */

function makeEnvironment(THREE, renderer, dark) {
  /* A miniature room of emissive panels, PMREM-filtered into an
     environment map. This is what gives surfaces a sense of being
     lit BY somewhere rather than uniformly tinted -- the single
     biggest difference between a massing model and a render. */
  const s = new THREE.Scene();
  const box = new THREE.BoxGeometry();
  box.deleteAttribute("uv");
  const mk = (col, int) => new THREE.MeshStandardMaterial({
    color: new THREE.Color(col), side: THREE.BackSide,
    emissive: new THREE.Color(col),
    emissiveIntensity: int === undefined ? 1 : int });

  const shell = new THREE.Mesh(box, mk(dark ? 0x1b232b : 0xd8e2e8, 0.6));
  shell.scale.set(24, 14, 24);
  s.add(shell);

  const panel = (col, int, pos, scale) => {
    const m = new THREE.Mesh(box, new THREE.MeshStandardMaterial({
      color: new THREE.Color(col), emissive: new THREE.Color(col),
      emissiveIntensity: int }));
    m.position.set(...pos); m.scale.set(...scale); s.add(m);
  };
  // ceiling strips + a warm and a cool side, so reflections have
  // somewhere to come from and metals read as metal
  panel(0xffffff, dark ? 3.2 : 5.0, [0, 6.6, 0], [16, 0.2, 5]);
  panel(0xffffff, dark ? 2.4 : 4.0, [0, 6.6, -7], [16, 0.2, 4]);
  panel(0xfff0dc, dark ? 1.6 : 2.6, [-9, 2.4, 0], [0.2, 5, 16]);
  panel(0xdfeaff, dark ? 1.4 : 2.2, [9, 2.0, 2], [0.2, 5, 16]);

  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = pmrem.fromScene(s, 0.04).texture;
  pmrem.dispose();
  s.traverse(o => { if (o.isMesh) o.material.dispose(); });
  box.dispose();
  return env;
}

/* ---------------- furniture ---------------- */

function box(THREE, mat, w, h, d, x, y, z, g) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y, z);
  m.castShadow = m.receiveShadow = true;
  g.add(m);
  return m;
}
function cyl(THREE, mat, rt, rb, h, x, y, z, g, seg) {
  const m = new THREE.Mesh(
    new THREE.CylinderGeometry(rt, rb, h, seg || 18), mat);
  m.position.set(x, y, z);
  m.castShadow = m.receiveShadow = true;
  g.add(m);
  return m;
}

/* Build a real object for a solid, or return null to fall back to a
   box. Dimensions come from the solid, so the analysis and the render
   never disagree about how much room a chair takes up. */
function makeFurniture(THREE, s, M) {
  const w = s.x1 - s.x0, d = s.y1 - s.y0, h = s.z1 - s.z0;
  const g = new THREE.Group();
  const T = M.timber, F = M.fabric, S = M.steel, P = M.porcelain;

  switch (s.tag) {
    case "cafe_table": {
      const r = Math.min(w, d) / 2;
      cyl(THREE, T, r, r, 0.04, 0, h - 0.02, 0, g, 28);      // top
      cyl(THREE, S, 0.035, 0.035, h - 0.06, 0, (h - 0.06) / 2, 0, g);
      cyl(THREE, S, r * 0.55, r * 0.6, 0.03, 0, 0.015, 0, g, 24); // base
      return g;
    }
    case "cafe_chair": {
      const sh = 0.45;                                        // seat height
      box(THREE, T, w, 0.05, d, 0, sh, 0, g);                 // seat
      box(THREE, T, w, h - sh - 0.05, 0.05, 0, sh + (h - sh) / 2,
          -d / 2 + 0.03, g);                                  // back
      const lx = w / 2 - 0.04, lz = d / 2 - 0.04;
      [[-lx, -lz], [lx, -lz], [-lx, lz], [lx, lz]].forEach(([a, b]) =>
        cyl(THREE, S, 0.017, 0.017, sh, a, sh / 2, b, g, 10));
      return g;
    }
    case "bench": {
      box(THREE, T, w, 0.07, d, 0, h - 0.035, 0, g);          // slab
      const px = w / 2 - 0.25;
      [-px, px].forEach(a =>
        box(THREE, S, 0.06, h - 0.07, d * 0.7, a, (h - 0.07) / 2, 0, g));
      return g;
    }
    case "lobby_seat": {                                      // armchair
      const sh = 0.42;
      box(THREE, F, w, 0.16, d, 0, sh, 0, g);                 // cushion
      box(THREE, F, w, h - sh - 0.08, 0.12, 0, sh + (h - sh) / 2,
          -d / 2 + 0.06, g);                                  // back
      [-(w / 2 - 0.06), w / 2 - 0.06].forEach(a =>
        box(THREE, F, 0.12, 0.22, d * 0.8, a, sh + 0.06, 0.02, g));
      const lx = w / 2 - 0.07, lz = d / 2 - 0.07;
      [[-lx, -lz], [lx, -lz], [-lx, lz], [lx, lz]].forEach(([a, b]) =>
        cyl(THREE, M.timber, 0.022, 0.018, sh - 0.08, a, (sh - 0.08) / 2, b, g, 8));
      return g;
    }
    case "reception": {
      box(THREE, T, w, h - 0.06, d * 0.82, 0, (h - 0.06) / 2, -d * 0.06, g);
      box(THREE, M.concrete, w + 0.1, 0.05, d, 0, h - 0.025, 0, g); // counter
      return g;
    }
    case "wc_pan": {
      cyl(THREE, P, w * 0.42, w * 0.34, h * 0.72, 0, h * 0.36, 0.02, g, 20);
      box(THREE, P, w * 0.9, 0.05, d * 0.8, 0, h * 0.74, 0.02, g);  // seat
      box(THREE, P, w * 0.9, 0.55, 0.16, 0, 0.28, -d / 2 + 0.08, g); // cistern
      return g;
    }
    case "wc_basin": {
      cyl(THREE, P, w * 0.48, w * 0.34, 0.16, 0, h - 0.08, 0, g, 22);
      cyl(THREE, P, 0.05, 0.05, h - 0.16, 0, (h - 0.16) / 2, -0.02, g, 12);
      cyl(THREE, S, 0.018, 0.018, 0.16, 0, h + 0.06, -d / 2 + 0.07, g, 10);
      return g;
    }
    default:
      return null;
  }
}

/* ---------------- figures ---------------- */

/* An articulated figure: separate head, neck, shoulders, upper and
   lower limbs. Capsules alone read as a snowman; joints are what make
   a walk cycle legible at demo distance. */
function makeFigure(THREE, colour, opts) {
  const o = opts || {};
  const g = new THREE.Group();
  const c = new THREE.Color(colour);
  const cloth = new THREE.MeshStandardMaterial({
    color: c, roughness: 0.82, metalness: 0.0 });
  const dark = new THREE.MeshStandardMaterial({
    color: c.clone().multiplyScalar(0.55), roughness: 0.85 });
  const skin = new THREE.MeshStandardMaterial({
    color: new THREE.Color(0xd8b49a), roughness: 0.7 });

  const seated = !!o.seated;
  const hipY = seated ? 0.52 : 0.90;
  const P = {};

  // torso: tapered, with shoulders
  const torso = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.15, 0.34, 6, 16), cloth);
  torso.position.set(0, hipY + 0.28, seated ? -0.02 : 0);
  g.add(torso);
  const shoulders = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.085, 0.30, 4, 12), cloth);
  shoulders.rotation.z = Math.PI / 2;
  shoulders.position.set(0, hipY + 0.48, seated ? -0.02 : 0);
  g.add(shoulders);

  const neck = new THREE.Mesh(
    new THREE.CylinderGeometry(0.045, 0.05, 0.08, 10), skin);
  neck.position.set(0, hipY + 0.55, seated ? -0.02 : 0);
  g.add(neck);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.105, 22, 16), skin);
  head.scale.set(0.92, 1.12, 1.0);
  head.position.set(0, hipY + 0.66, seated ? -0.02 : 0);
  g.add(head);
  P.head = head;

  // limbs, pivoting from the joint rather than the centre
  const limb = (len, r, mat, px, py, pz) => {
    const grp = new THREE.Group();
    grp.position.set(px, py, pz);
    const m = new THREE.Mesh(
      new THREE.CapsuleGeometry(r, len, 4, 12), mat);
    m.position.y = -len / 2 - r * 0.4;
    grp.add(m);
    g.add(grp);
    return grp;
  };

  P.arms = [-1, 1].map(sx => {
    const upper = limb(0.26, 0.048, cloth, sx * 0.20, hipY + 0.47, 0);
    const lower = limb(0.24, 0.042, skin, 0, -0.30, 0);
    upper.remove(lower); upper.add(lower);
    lower.position.set(0, -0.30, 0);
    return { upper, lower };
  });

  P.legs = [-1, 1].map(sx => {
    const upper = limb(0.32, 0.062, dark, sx * 0.095, hipY, 0);
    const lower = limb(0.30, 0.052, dark, 0, -0.36, 0);
    upper.remove(lower); upper.add(lower);
    lower.position.set(0, -0.36, 0);
    const foot = new THREE.Mesh(
      new THREE.BoxGeometry(0.09, 0.05, 0.20), dark);
    foot.position.set(0, -0.34, 0.05);
    lower.add(foot);
    return { upper, lower, foot };
  });

  if (seated) {
    // Hips flexed, knees forward: a seated posture, not a standing
    // figure lowered onto a chair.
    P.legs.forEach(l => {
      l.upper.rotation.x = -1.45;
      l.lower.rotation.x = 1.30;
    });
    P.arms.forEach(a => { a.upper.rotation.x = 0.55; a.lower.rotation.x = -0.5; });
  }

  g.traverse(m => { if (m.isMesh) { m.castShadow = true; m.receiveShadow = true; } });
  return { group: g, parts: P, materials: { cloth, dark, skin } };
}

/* A wheelchair with a spoked drive wheel, castors, footplate and
   push rim -- the silhouette people actually recognise. */
function makeWheelchair(THREE, colour) {
  const g = new THREE.Group();
  const c = new THREE.Color(colour);
  const frame = new THREE.MeshStandardMaterial({
    color: c, roughness: 0.4, metalness: 0.55 });
  const rubber = new THREE.MeshStandardMaterial({
    color: 0x1c2126, roughness: 0.85 });
  const chrome = new THREE.MeshStandardMaterial({
    color: 0xc7d0d6, roughness: 0.22, metalness: 0.9 });
  const seat = new THREE.MeshStandardMaterial({
    color: c.clone().multiplyScalar(0.5), roughness: 0.9 });

  box(THREE, seat, 0.44, 0.06, 0.42, 0, 0.50, 0.0, g);          // seat pad
  box(THREE, seat, 0.44, 0.46, 0.05, 0, 0.75, -0.20, g);        // backrest
  box(THREE, frame, 0.05, 0.05, 0.46, -0.22, 0.47, 0, g);       // side rails
  box(THREE, frame, 0.05, 0.05, 0.46, 0.22, 0.47, 0, g);
  box(THREE, frame, 0.38, 0.03, 0.16, 0, 0.13, 0.30, g);        // footplate
  [-0.15, 0.15].forEach(sx =>
    cyl(THREE, frame, 0.022, 0.022, 0.40, sx, 0.30, 0.26, g, 10));
  [-0.24, 0.24].forEach(sx => {                                  // push handles
    cyl(THREE, frame, 0.02, 0.02, 0.24, sx, 1.02, -0.22, g, 10);
    cyl(THREE, rubber, 0.026, 0.026, 0.10, sx, 1.15, -0.22, g, 10);
  });

  const wheels = [];
  [-1, 1].forEach(sx => {
    const wg = new THREE.Group();
    wg.position.set(sx * 0.29, 0.31, -0.05);
    wg.rotation.y = Math.PI / 2;
    const tyre = new THREE.Mesh(
      new THREE.TorusGeometry(0.30, 0.028, 12, 30), rubber);
    wg.add(tyre);
    const rim = new THREE.Mesh(
      new THREE.TorusGeometry(0.255, 0.012, 8, 26), chrome);
    wg.add(rim);
    const hub = new THREE.Mesh(
      new THREE.CylinderGeometry(0.035, 0.035, 0.05, 12), chrome);
    hub.rotation.x = Math.PI / 2; wg.add(hub);
    for (let i = 0; i < 8; i++) {                                // spokes
      const sp = new THREE.Mesh(
        new THREE.CylinderGeometry(0.006, 0.006, 0.56, 6), chrome);
      sp.rotation.z = (i / 8) * Math.PI;
      wg.add(sp);
    }
    g.add(wg); wheels.push(wg);
  });
  [-1, 1].forEach(sx => {                                        // castors
    const cg = new THREE.Group();
    cg.position.set(sx * 0.20, 0.09, 0.30);
    cg.rotation.y = Math.PI / 2;
    const t = new THREE.Mesh(
      new THREE.TorusGeometry(0.075, 0.024, 10, 20), rubber);
    cg.add(t);
    g.add(cg); wheels.push(cg);
  });

  g.traverse(m => { if (m.isMesh) { m.castShadow = true; m.receiveShadow = true; } });
  return { group: g, wheels };
}

/* A delivery robot: rounded shell, lid, castors, mast flag. */
function makeRobot(THREE, colour) {
  const g = new THREE.Group();
  const c = new THREE.Color(colour);
  const shell = new THREE.MeshStandardMaterial({
    color: c, roughness: 0.35, metalness: 0.15 });
  const dark = new THREE.MeshStandardMaterial({
    color: c.clone().multiplyScalar(0.45), roughness: 0.6 });
  const rubber = new THREE.MeshStandardMaterial({
    color: 0x1c2126, roughness: 0.85 });
  const glass = new THREE.MeshStandardMaterial({
    color: 0x101418, roughness: 0.1, metalness: 0.6 });

  const body = new THREE.Mesh(
    new THREE.BoxGeometry(0.58, 0.50, 0.76), shell);
  body.position.y = 0.44; g.add(body);
  box(THREE, dark, 0.60, 0.06, 0.78, 0, 0.72, 0, g);            // lid
  box(THREE, glass, 0.40, 0.10, 0.02, 0, 0.56, 0.385, g);       // sensor strip
  cyl(THREE, dark, 0.02, 0.02, 0.36, 0, 0.92, -0.30, g, 10);    // mast
  const flag = new THREE.Mesh(new THREE.SphereGeometry(0.05, 14, 10), shell);
  flag.position.set(0, 1.12, -0.30); g.add(flag);

  const wheels = [];
  [[-0.30, 0.24], [0.30, 0.24], [-0.30, -0.24], [0.30, -0.24]].forEach(
    ([sx, sz]) => {
      const w = new THREE.Mesh(
        new THREE.CylinderGeometry(0.145, 0.145, 0.07, 18), rubber);
      w.position.set(sx, 0.145, sz);
      w.rotation.z = Math.PI / 2;
      g.add(w); wheels.push(w);
    });

  g.traverse(m => { if (m.isMesh) { m.castShadow = true; m.receiveShadow = true; } });
  return { group: g, wheels };
}
