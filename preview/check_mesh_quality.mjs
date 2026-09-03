// Mesh quality gate: triangle inversion, local area ratio, edge stretch, and
// UV (texture) distortion, for both the grid and contour mesh backends.
//
//   node preview/check_mesh_quality.mjs                    -- synthetic checks
//   node preview/check_mesh_quality.mjs <run directory>     -- real-fixture report
//
// PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1 #9, #18 (P1-B): these are
// the numbers P1-A's `contour_tags` A/B comparison is decided against --
// "looks a bit off" becomes a compile-time regression instead of something
// only noticed by eye. Imports runtime.mjs directly, same as
// check_deformation.mjs and measure_disocclusion.mjs (P0-C).
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { inflateSync } from "node:zlib";

const control = () => ({
  checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {},
  classList: { add() {}, remove() {} }, click() {},
});
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { buildMesh, deform, state, fitShells, EYE_TAGS, LID_TAGS, HAIR_SHELL_TAGS } = Runtime;

/* ---------- metrics ---------- */

function signedArea2(pts, ia, ib, ic) {
  const ax = pts[ia * 2], ay = pts[ia * 2 + 1];
  const bx = pts[ib * 2], by = pts[ib * 2 + 1];
  const cx = pts[ic * 2], cy = pts[ic * 2 + 1];
  return (bx - ax) * (cy - ay) - (cx - ax) * (by - ay);
}

/** How many triangles flip winding between rest and live -- a vertex has
 *  crossed over the opposite edge of its own triangle, which reads as the
 *  texture folding onto itself. Zero is the target (absorption plan #9); a
 *  triangle degenerate (near-zero area) in either pose has no orientation to
 *  compare and is skipped rather than counted either way. */
export function countInvertedTriangles(mesh, eps = 1e-6) {
  let inverted = 0;
  for (let i = 0; i < mesh.index.length; i += 3) {
    const [a, b, c] = [mesh.index[i], mesh.index[i + 1], mesh.index[i + 2]];
    const restArea = signedArea2(mesh.rest, a, b, c);
    const liveArea = signedArea2(mesh.live, a, b, c);
    if (Math.abs(restArea) < eps || Math.abs(liveArea) < eps) continue;
    if (Math.sign(restArea) !== Math.sign(liveArea)) inverted++;
  }
  return inverted;
}

/** `|live area| / |rest area|` per triangle: 1 is no change, >1 growing,
 *  <1 shrinking. A degenerate rest triangle (already zero area) contributes
 *  no ratio -- there is nothing to compare it against. */
export function localAreaRatios(mesh, eps = 1e-9) {
  const ratios = [];
  for (let i = 0; i < mesh.index.length; i += 3) {
    const [a, b, c] = [mesh.index[i], mesh.index[i + 1], mesh.index[i + 2]];
    const restArea = Math.abs(signedArea2(mesh.rest, a, b, c));
    if (restArea < eps) continue;
    ratios.push(Math.abs(signedArea2(mesh.live, a, b, c)) / restArea);
  }
  return ratios;
}

function triangleEdges(index) {
  const seen = new Set();
  const edges = [];
  for (let i = 0; i < index.length; i += 3) {
    const [a, b, c] = [index[i], index[i + 1], index[i + 2]];
    for (const [p, q] of [[a, b], [b, c], [c, a]]) {
      const key = p < q ? `${p}_${q}` : `${q}_${p}`;
      if (seen.has(key)) continue;
      seen.add(key);
      edges.push([p, q]);
    }
  }
  return edges;
}

function edgeLength(pts, a, b) {
  return Math.hypot(pts[a * 2] - pts[b * 2], pts[a * 2 + 1] - pts[b * 2 + 1]);
}

/** `live length / rest length` per mesh edge (each shared edge counted
 *  once). This is what a seam actually feels: a triangle can keep its area
 *  while one edge on the seam lengthens and the perpendicular one shrinks. */
export function edgeStretchRatios(mesh, eps = 1e-9) {
  const ratios = [];
  for (const [a, b] of triangleEdges(mesh.index)) {
    const restLen = edgeLength(mesh.rest, a, b);
    if (restLen < eps) continue;
    ratios.push(edgeLength(mesh.live, a, b) / restLen);
  }
  return ratios;
}

/** The 2x2 linear map from a triangle's rest shape to its live shape (its
 *  own local origin at vertex `a`), i.e. exactly how that patch of texture
 *  is being stretched -- UV was assigned proportionally to rest geometry
 *  (`buildMesh`), so this *is* UV distortion up to the part's own constant
 *  width/height aspect ratio, without needing raw UV coordinates at all. */
function triangleJacobian(rest, live, a, b, c) {
  const r0x = rest[a * 2], r0y = rest[a * 2 + 1];
  const r1x = rest[b * 2] - r0x, r1y = rest[b * 2 + 1] - r0y;
  const r2x = rest[c * 2] - r0x, r2y = rest[c * 2 + 1] - r0y;
  const det = r1x * r2y - r2x * r1y;
  if (Math.abs(det) < 1e-9) return null;
  const invR00 = r2y / det, invR01 = -r2x / det;
  const invR10 = -r1y / det, invR11 = r1x / det;
  const l0x = live[a * 2], l0y = live[a * 2 + 1];
  const l1x = live[b * 2] - l0x, l1y = live[b * 2 + 1] - l0y;
  const l2x = live[c * 2] - l0x, l2y = live[c * 2 + 1] - l0y;
  return [
    l1x * invR00 + l2x * invR10, l1x * invR01 + l2x * invR11,
    l1y * invR00 + l2y * invR10, l1y * invR01 + l2y * invR11,
  ];
}

/** Closed-form singular values of a 2x2 matrix [a b; c d], largest first. */
function singularValues2x2([a, b, c, d]) {
  const E = (a + d) / 2, F = (a - d) / 2, G = (c + b) / 2, H = (c - b) / 2;
  const Q = Math.hypot(E, H), R = Math.hypot(F, G);
  return [Q + R, Math.abs(Q - R)];
}

/** Anisotropy (sigma1/sigma2) of the rest->live map per triangle: 1 means
 *  the texture stretches equally in every direction (just bigger or
 *  smaller, which `localAreaRatios` already covers); growing past that
 *  means the texture is smearing along one axis while barely moving along
 *  the other -- what actually reads as "distorted" on a small eye or mouth
 *  part rather than merely resized. Infinity marks a triangle collapsed to
 *  a line (sigma2 == 0). */
export function uvDistortion(mesh) {
  const out = [];
  for (let i = 0; i < mesh.index.length; i += 3) {
    const [a, b, c] = [mesh.index[i], mesh.index[i + 1], mesh.index[i + 2]];
    const jac = triangleJacobian(mesh.rest, mesh.live, a, b, c);
    if (!jac) continue;
    const [s1, s2] = singularValues2x2(jac);
    out.push(s2 < 1e-9 ? Infinity : s1 / s2);
  }
  return out;
}

function percentile(values, p) {
  if (!values.length) return NaN;
  const sorted = values.filter(Number.isFinite).slice().sort((x, y) => x - y);
  if (!sorted.length) return Infinity;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.round(p * (sorted.length - 1))));
  return sorted[idx];
}

/** One report object for a built-and-deformed mesh: everything a QA gate or
 *  an A/B comparison (grid vs contour, P1-A) needs from one pose. */
export function meshQualityReport(mesh) {
  const areaRatios = localAreaRatios(mesh);
  const edgeRatios = edgeStretchRatios(mesh);
  const distortion = uvDistortion(mesh);
  return {
    triangleCount: mesh.index.length / 3,
    invertedTriangleCount: countInvertedTriangles(mesh),
    areaRatio: { min: percentile(areaRatios, 0), p50: percentile(areaRatios, 0.5), max: percentile(areaRatios, 1) },
    edgeStretch: { min: percentile(edgeRatios, 0), p50: percentile(edgeRatios, 0.5), max: percentile(edgeRatios, 1) },
    uvDistortion: { p50: percentile(distortion, 0.5), p95: percentile(distortion, 0.95), max: percentile(distortion, 1) },
  };
}

/* ---------- synthetic checks ---------- */

if (process.argv.length <= 2) {
  let failures = 0;
  function check(name, cond, detail = "") {
    if (cond) console.log(`  ok   ${name}`);
    else { console.log(`  FAIL ${name} ${detail}`); failures++; }
  }
  const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;

  function meshOf(rest, index) {
    return { rest: new Float32Array(rest), live: new Float32Array(rest), index: new Uint16Array(index) };
  }

  console.log("triangle inversion");
  {
    // One triangle, then flip vertex c across the opposite edge.
    const rest = [0, 0, 10, 0, 0, 10];
    const mesh = meshOf(rest, [0, 1, 2]);
    check("an unmoved triangle is never inverted", countInvertedTriangles(mesh) === 0);
    mesh.live = new Float32Array([0, 0, 10, 0, 0, -10]); // c reflected through the a-b edge
    check("a reflected triangle counts as inverted", countInvertedTriangles(mesh) === 1);
    mesh.live = new Float32Array([0, 0, 10, 0, 5, 5]); // moved but not crossed
    check("a triangle that only shrinks is not inverted", countInvertedTriangles(mesh) === 0);
  }

  console.log("\nlocal area ratio");
  {
    const rest = [0, 0, 10, 0, 0, 10]; // area 50
    const mesh = meshOf(rest, [0, 1, 2]);
    mesh.live = new Float32Array([0, 0, 20, 0, 0, 20]); // uniform 2x scale -> area 200
    const ratios = localAreaRatios(mesh);
    check("a uniform 2x scale is an area ratio of 4", near(ratios[0], 4));
    mesh.live = new Float32Array(rest);
    check("an unmoved triangle has an area ratio of 1", near(localAreaRatios(mesh)[0], 1));
    const degenerate = meshOf([0, 0, 10, 0, 20, 0], [0, 1, 2]); // collinear: zero rest area
    check("a degenerate rest triangle contributes no ratio", localAreaRatios(degenerate).length === 0);
  }

  console.log("\nedge stretch");
  {
    const rest = [0, 0, 10, 0, 0, 10];
    const mesh = meshOf(rest, [0, 1, 2]);
    mesh.live = new Float32Array([0, 0, 20, 0, 0, 10]); // only the a-b edge doubles
    const ratios = edgeStretchRatios(mesh);
    check("the a-b edge doubling shows up as a ratio of 2", ratios.some((r) => near(r, 2)));
    check("the untouched a-c edge stays a ratio of 1", ratios.some((r) => near(r, 1)));
    check("a triangle's three edges are each counted once, not per-triangle",
          ratios.length === 3);
  }

  console.log("\nUV distortion (anisotropy)");
  {
    const rest = [0, 0, 10, 0, 0, 10];
    const mesh = meshOf(rest, [0, 1, 2]);
    mesh.live = new Float32Array([0, 0, 20, 0, 0, 20]); // uniform 2x: same shape, just bigger
    check("a uniform scale has no anisotropy", near(uvDistortion(mesh)[0], 1, 1e-4));
    mesh.live = new Float32Array([0, 0, 30, 0, 0, 10]); // 3x on one axis, unchanged on the other
    check("stretching only one axis reads as that axis's ratio",
          near(uvDistortion(mesh)[0], 3, 1e-4));
    const collapsed = meshOf(rest, [0, 1, 2]);
    collapsed.live = new Float32Array([0, 0, 10, 0, 5, 0]); // c collapsed onto the a-b line
    check("a triangle collapsed to a line has infinite anisotropy",
          uvDistortion(collapsed)[0] === Infinity);
  }

  console.log("\nend-to-end: grid vs contour on the same weight/motion");
  {
    // Same part box and weight spec, one grid one contour, deformed by the
    // same pose -- a sanity check that meshQualityReport runs cleanly for
    // both backends and returns finite numbers for an ordinary turn.
    const weight = { mode: "constant", value: 1.0 };
    const gridPart = { xyxy: [0, 0, 100, 100], depth: 0.5, weight, mesh: { kind: "grid", cell: 20 } };
    const contourPart = {
      xyxy: [0, 0, 100, 100], depth: 0.5, weight,
      mesh: {
        kind: "contour",
        vertices: [[10, 10], [90, 10], [90, 90], [10, 90], [50, 50]],
        triangles: [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
      },
    };
    state.manifest = { anchors: {} };
    state.breathTop = 0; state.breathBottom = 100; state.chestCx = 50;
    const pose = { turnX: 0.3, turnY: 0.1, tiltRad: 0, blink: { l: 0, r: 0 }, breath: 0,
                   breathAmp: 3, chestX: 0.004, lidRatio: 0.85, lidThickness: 0.18,
                   overrides: { ghost: false, neck: "gradient", collar: null } };
    for (const [label, spec] of [["grid", gridPart], ["contour", contourPart]]) {
      const mesh = buildMesh(spec);
      deform({ spec, mesh, isEye: false, eyeSide: null, eyeCenterY: 50 }, 0, pose);
      const report = meshQualityReport(mesh);
      check(`${label} mesh: no inverted triangles at a modest turn`,
            report.invertedTriangleCount === 0, JSON.stringify(report));
      check(`${label} mesh: area ratio stays finite`, Number.isFinite(report.areaRatio.max));
    }
  }

  console.log(failures ? `\n${failures} FAILED` : "\nall checks passed");
  process.exit(failures ? 1 : 0);
}

/* ---------- real-fixture report ---------- */

function decodePNG(buf) {
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error("not a PNG");
  let pos = 8, width = 0, height = 0;
  const idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos);
    const type = buf.toString("latin1", pos + 4, pos + 8);
    const body = buf.subarray(pos + 8, pos + 8 + len);
    if (type === "IHDR") {
      width = body.readUInt32BE(0); height = body.readUInt32BE(4);
      if (body[8] !== 8 || body[9] !== 6 || body[12] !== 0)
        throw new Error("expected 8-bit RGBA, non-interlaced");
    } else if (type === "IDAT") idat.push(body);
    else if (type === "IEND") break;
    pos += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idat));
  const bpp = 4, stride = width * bpp;
  const out = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    const cur = out.subarray(y * stride, (y + 1) * stride);
    const prev = y ? out.subarray((y - 1) * stride, y * stride) : null;
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? cur[i - bpp] : 0;
      const b = prev ? prev[i] : 0;
      const c = prev && i >= bpp ? prev[i - bpp] : 0;
      let v = line[i];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) {
        const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      } else if (filter !== 0) throw new Error("bad PNG filter " + filter);
      cur[i] = v & 0xff;
    }
  }
  const alpha = new Uint8Array(width * height);
  for (let i = 0; i < alpha.length; i++) alpha[i] = out[i * 4 + 3];
  return { width, height, alpha };
}

const runDir = process.argv[2];
const manifestName = readdirSync(runDir).find((f) => /_rig_manifest\.json$/.test(f));
if (!manifestName) {
  console.error("no *_rig_manifest.json in " + runDir);
  process.exit(2);
}
const manifest = JSON.parse(readFileSync(join(runDir, manifestName), "utf8"));
const turnXs = process.argv.slice(3).map(Number);
const sweep = turnXs.length ? turnXs : [0.2, 0.5, 0.8];

state.manifest = manifest;
state.canvasW = manifest.canvas.width; state.canvasH = manifest.canvas.height;
state.breathTop = 0; state.breathBottom = manifest.canvas.height; state.chestCx = manifest.canvas.width / 2;
state.shells = fitShells(manifest.parts);

const parts = manifest.parts.map((spec) => ({
  spec, mesh: buildMesh(spec),
  isEye: EYE_TAGS.has(spec.tag), eyeSide: null,
  eyeCenterY: (spec.xyxy[1] + spec.xyxy[3]) / 2,
  isLid: LID_TAGS.has(spec.tag),
  shell: !state.shells || spec.group === "body" ? null
       : HAIR_SHELL_TAGS.has(spec.tag) ? state.shells.hair : state.shells.head,
}));
void decodePNG; // available for a caller that wants to cross-check against real pixels

console.log(`mesh quality  ${manifest.canvas.width}x${manifest.canvas.height}, ${parts.length} parts`);
console.log(`${"tag".padEnd(20)}${"kind".padEnd(9)}${"tri".padStart(6)}  ` +
           sweep.map((t) => `turnX=${t}`.padStart(28)).join(""));
console.log(" ".repeat(35) + sweep.map(() => "inv  area[min,max]  edge[max]  uv[p95]".padStart(28)).join(""));

for (const part of parts) {
  const row = [part.spec.tag.padEnd(20), (part.spec.mesh.kind || "grid").padEnd(9),
              String(part.mesh.index.length / 3).padStart(6)];
  for (const turnX of sweep) {
    const pose = { turnX, turnY: turnX * 0.3, tiltRad: 0, blink: { l: 0, r: 0 }, breath: 0,
                   breathAmp: 3, chestX: 0.004, lidRatio: 0.85, lidThickness: 0.18,
                   overrides: { ghost: false, neck: "gradient", collar: null } };
    deform(part, 0, pose);
    const r = meshQualityReport(part.mesh);
    const uv95 = Number.isFinite(r.uvDistortion.p95) ? r.uvDistortion.p95.toFixed(2) : "inf";
    row.push(`  ${String(r.invertedTriangleCount).padStart(3)} ` +
             `[${r.areaRatio.min.toFixed(2)},${r.areaRatio.max.toFixed(2)}]  ` +
             `${r.edgeStretch.max.toFixed(2)}  ${uv95}`.padStart(24));
  }
  console.log(row.join(""));
}
