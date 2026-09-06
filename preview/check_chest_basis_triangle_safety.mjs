// P2.5 directive #42/#65 (see the plan's scope note for #42-43: the JS
// runtime carries no per-part triangle/index buffer today, so this is a
// regression gate on the real compiled-fixture topology rather than a
// general "any mesh, any topology" solver). Reconstructs the fixture's own
// uniform-grid triangulation (two triangles per cell, from its known
// `xs x ys` layout in qa_compiled_topwear.mjs) and asserts the P2.5 basis's
// magnitude clamps (max_follow_px/max_shear_px) keep every triangle's signed
// area from flipping sign under the directive's stress cases.
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { deform, state } = Runtime;
const { makeCompiledTopwearFixture, makeChestMotion, attachChestBasis } = await import(
  new URL("qa_compiled_topwear.mjs", import.meta.url));

// Mirrors qa_compiled_topwear.mjs's own grid exactly (7 columns x 5 rows).
const XS_COUNT = 7, YS_COUNT = 5;
function gridTriangles() {
  const tris = [];
  for (let r = 0; r < YS_COUNT - 1; r++) {
    for (let c = 0; c < XS_COUNT - 1; c++) {
      const a = r * XS_COUNT + c, b = a + 1, d = a + XS_COUNT, e = d + 1;
      tris.push([a, b, d], [b, e, d]);
    }
  }
  return tris;
}
const signedArea = (live, [a, b, c]) => {
  const ax = live[a * 2], ay = live[a * 2 + 1];
  const bx = live[b * 2], by = live[b * 2 + 1];
  const cx = live[c * 2], cy = live[c * 2 + 1];
  return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
};

state.manifest = { anchors: {} };
state.canvasW = 256; state.canvasH = 256;
state.frameOperations = [{ id: "chest", kind: "local_soft_field", phase: "secondary" }];
state.motionQA = { asymmetry: 1, settleMultiplier: 1, side: "both", shapeGain: null, poseActive: false };

const tris = gridTriangles();
const springyDistribution = {
  version: 3, volume_gain: 0.60, sag_gain: 0.95, follow_gain_s: 0.035,
  shear_gain_x_s: 0.018, shear_gain_y_s: 0.012, compression_gain: 0.20,
  upper_anchor_start: -0.75, upper_anchor_end: -0.15,
  lower_start: 0.0, lower_power: 1.7, tangent_ratio: 0.15,
  max_follow_px: 3.0, max_shear_px: 2.0,
};

const stressCases = [
  { name: "q=+6", q: 6, v: 0, bodyVx: 0, bodyVy: 0 },
  { name: "q=-6", q: -6, v: 0, bodyVx: 0, bodyVy: 0 },
  { name: "v=+24", q: 0, v: 24, bodyVx: 0, bodyVy: 0 },
  { name: "v=-24", q: 0, v: -24, bodyVx: 0, bodyVy: 0 },
  { name: "max shear", q: 3, v: 12, bodyVx: 400, bodyVy: 400 },
  { name: "combined", q: 6, v: 24, bodyVx: 400, bodyVy: -400 },
];

let restAreas = null;
for (const stress of stressCases) {
  const part = attachChestBasis(Runtime, makeCompiledTopwearFixture(), springyDistribution);
  if (!restAreas) restAreas = tris.map((tri) => signedArea(part.mesh.rest, tri));

  const torso = { model: "inertial_relative_v2",
    left: { value: stress.q, velocity: stress.v }, right: { value: stress.q, velocity: stress.v },
    settleTimeScaleS: 0.03 };
  const motion = makeChestMotion(torso, { physicsDistribution: springyDistribution });
  motion.bodyVelocityX = stress.bodyVx;
  motion.bodyVelocityY = stress.bodyVy;
  deform(part, 0, motion);

  const liveAreas = tris.map((tri) => signedArea(part.mesh.live, tri));
  for (let t = 0; t < tris.length; t++) {
    if (Math.abs(restAreas[t]) < 1e-6) continue; // degenerate rest triangle, not this test's concern
    if (Math.sign(restAreas[t]) !== Math.sign(liveAreas[t]))
      throw new Error(`triangle ${t} inverted under stress "${stress.name}": `
        + `rest area ${restAreas[t].toFixed(3)}, live area ${liveAreas[t].toFixed(3)}`);
  }
  console.log(`"${stress.name}": no triangle inversion (${tris.length} triangles checked)`);
}

console.log("chest basis triangle safety checks passed");
