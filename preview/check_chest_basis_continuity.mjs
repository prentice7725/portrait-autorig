// P2.5 directive #64: sweeping q through zero must not produce a
// discontinuous vertex jump -- every basis mask is built from smoothstep/
// power/radial terms (directive #53), never a hard threshold, so the final
// per-vertex displacement should vary smoothly with q.
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
const { makeCompiledTopwearFixture, makeChestMotion, attachChestBasis, BASIS_V3_DISTRIBUTION } = await import(
  new URL("qa_compiled_topwear.mjs", import.meta.url));

state.manifest = { anchors: {} };
state.canvasW = 256; state.canvasH = 256;
state.frameOperations = [{ id: "chest", kind: "local_soft_field", phase: "secondary" }];
state.motionQA = { asymmetry: 1, settleMultiplier: 1, side: "both", shapeGain: null, poseActive: false };

const qs = [-4, -2, 0, 2, 4];
const positions = qs.map((q) => {
  const part = attachChestBasis(Runtime, makeCompiledTopwearFixture());
  const torso = { model: "inertial_relative_v2",
    left: { value: q, velocity: 0 }, right: { value: q, velocity: 0 },
    settleTimeScaleS: 0.03 };
  const motion = makeChestMotion(torso, { physicsDistribution: BASIS_V3_DISTRIBUTION });
  deform(part, 0, motion);
  return part.mesh.live.slice();
});

// Per-step displacement of every vertex, and the largest single jump anywhere
// in the sweep. A discontinuity would show up as an outlier step much larger
// than its neighbors, not merely "large" (q=+-4 legitimately moves several
// px) -- so check jump ratios between consecutive steps rather than an
// absolute cap.
let maxStep = 0;
const stepMagnitudes = [];
for (let s = 1; s < positions.length; s++) {
  let stepMax = 0;
  for (let i = 0; i < positions[s].length; i += 2) {
    const dx = positions[s][i] - positions[s - 1][i];
    const dy = positions[s][i + 1] - positions[s - 1][i + 1];
    stepMax = Math.max(stepMax, Math.hypot(dx, dy));
  }
  stepMagnitudes.push(stepMax);
  maxStep = Math.max(maxStep, stepMax);
}
console.log("per-step max displacement:", stepMagnitudes.map((v) => v.toFixed(3)).join(", "));

// No step should be more than 3x any other step (a real discontinuity would
// dwarf its neighbors; smooth interpolation keeps consecutive steps close
// since q increments are uniform).
const smallestStep = Math.min(...stepMagnitudes);
for (const step of stepMagnitudes) {
  if (smallestStep > 1e-6 && step / smallestStep > 3)
    throw new Error(`discontinuous jump detected: step ${step}px vs smallest ${smallestStep}px`);
}

// Finite everywhere, always.
for (const snapshot of positions) {
  for (const value of snapshot) {
    if (!Number.isFinite(value)) throw new Error("non-finite vertex position during q sweep");
  }
}

console.log("chest basis continuity checks passed");
