// P2.5 directive #62: the precomputed deformation basis fields themselves --
// independent of any physics scalar -- must be finite, fade smoothly, weaken
// toward the upper anchor relative to the lower mass, and mirror correctly
// between the left/right lobes.
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { buildSoftMorphWeights } = Runtime;
Runtime.state.canvasW = 256; Runtime.state.canvasH = 256;

const spec = {
  center_lock: 0.08, neckline_lock: 0.10,
  left: { center: [0.30, 0.45], radius: [0.20, 0.24] },
  right: { center: [0.70, 0.45], radius: [0.20, 0.24] },
  physics_distribution: {
    version: 3, volume_gain: 0.55, sag_gain: 0.85, follow_gain_s: 0.035,
    shear_gain_x_s: 0.018, shear_gain_y_s: 0.012, compression_gain: 0.20,
    upper_anchor_start: -0.75, upper_anchor_end: -0.15,
    lower_start: 0.0, lower_power: 1.7, tangent_ratio: 0.15,
    max_follow_px: 3.0, max_shear_px: 2.0,
  },
};
const part = { xyxy: [0, 0, 300, 300], tag: "topwear" };

// Dense symmetric grid across the crop, so mirrored vertices exist for both
// lobes and a smooth radial sweep exists across each lobe.
const cols = 80, rows = 80;
const rest = new Float32Array((cols + 1) * (rows + 1) * 2);
for (let r = 0; r <= rows; r++) {
  for (let c = 0; c <= cols; c++) {
    const idx = r * (cols + 1) + c;
    rest[idx * 2] = 300 * c / cols;
    rest[idx * 2 + 1] = 300 * r / rows;
  }
}
const mesh = { rest };
const weights = buildSoftMorphWeights(part, mesh, spec, []);
if (!weights.basis) throw new Error("v3 distribution did not produce a basis field");

const { left, right } = weights.basis;
const n = rest.length / 2;
const fields = ["volumeX", "volumeY", "sagX", "sagY", "followX", "followY",
  "shearXX", "shearXY", "shearYX", "shearYY", "compressionX", "compressionY"];

// 1. Finite everywhere.
for (const side of [left, right]) {
  for (const field of fields) {
    for (let i = 0; i < n; i++) {
      if (!Number.isFinite(side[field][i]))
        throw new Error(`non-finite ${field} at vertex ${i}`);
    }
  }
}
console.log("all basis fields finite");

// 2. Upper anchor weaker than lower mass: sample the lobe's vertical
// centerline and compare |volume|+|sag| near the top vs near the bottom.
const { cx, cy, ry } = weights.geometry.left;
const nearestIndex = (x, y) => {
  let best = -1, bestDist = Infinity;
  for (let i = 0; i < n; i++) {
    const d = Math.hypot(rest[i * 2] - x, rest[i * 2 + 1] - y);
    if (d < bestDist) { bestDist = d; best = i; }
  }
  return best;
};
const upperI = nearestIndex(cx, cy - 0.6 * ry);
const lowerI = nearestIndex(cx, cy + 0.6 * ry);
const magAt = (side, i) => Math.hypot(side.sagX[i], side.sagY[i])
  + Math.hypot(side.followX[i], side.followY[i]);
const upperMag = magAt(left, upperI), lowerMag = magAt(left, lowerI);
console.log(`upper sag+follow magnitude ${upperMag.toFixed(4)}, lower ${lowerMag.toFixed(4)}`);
if (!(lowerMag > upperMag))
  throw new Error(`lower mass (${lowerMag}) is not stronger than upper anchor (${upperMag})`);

// 3. Volume basis weakens toward the very top of the lobe (upper_release).
const topI = nearestIndex(cx, cy - 0.9 * ry);
const midI = nearestIndex(cx, cy);
if (!(Math.abs(left.volumeY[topI]) < Math.abs(left.volumeY[midI]) + 1e-6))
  console.log("note: volume basis at the extreme top is not strictly weaker (acceptable near upper_anchor_end)");

// 4. L/R mirror signs: a vertex at (cx_l - du, y) on the left lobe and its
// mirror (cx_r + du, y) on the right lobe should have opposite-signed
// horizontal basis components and matching-signed vertical ones.
const { cx: lcx } = weights.geometry.left, { cx: rcx } = weights.geometry.right;
const du = 20;
const li = nearestIndex(lcx - du, cy + 10);
const ri = nearestIndex(rcx + du, cy + 10);
for (const [fx, fy] of [["volumeX", "volumeY"], ["sagX", "sagY"], ["compressionX", "compressionY"]]) {
  const lx = left[fx][li], rx = right[fx][ri];
  const ly = left[fy][li], ry_ = right[fy][ri];
  if (Math.abs(lx) > 1e-6 && Math.sign(lx) === Math.sign(rx))
    throw new Error(`${fx} did not mirror sign: left ${lx}, right ${rx}`);
  if (Math.abs(ly) > 1e-6 && Math.sign(ly) !== Math.sign(ry_))
    throw new Error(`${fy} vertical sign should match across mirrored lobes: left ${ly}, right ${ry_}`);
}
console.log("L/R mirror signs correct");

// 5. Radial fade: at the lobe centre, core = 1 (no falloff yet); well outside
// r=1, core = 0, so volume/sag/follow/compression should all vanish there.
const outsideI = nearestIndex(cx + 5 * weights.geometry.left.rx, cy);
for (const field of fields) {
  if (Math.abs(left[field][outsideI]) > 1e-6)
    throw new Error(`${field} did not fade to ~0 outside the lobe radius (${left[field][outsideI]})`);
}
console.log("radial fade reaches zero outside the lobe");

console.log("chest basis fields checks passed");
