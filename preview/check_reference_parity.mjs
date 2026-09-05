// Compare the optimized geometry backend with the independent CPU oracle.
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
const { deformReference, applyBoundaryStitchesReference } = await import(new URL("reference-runtime.mjs", import.meta.url));

const operations = [
  { id: "turn", kind: "parallax_turn", phase: "primary" },
  { id: "sway", kind: "body_sway", phase: "primary" },
  { id: "tilt", kind: "weighted_rotation", phase: "primary" },
  { id: "breath", kind: "continuous_field", phase: "primary" },
  { id: "chest", kind: "local_soft_field", phase: "secondary" },
];
const rest = new Float32Array([100, 100, 140, 100, 100, 180, 140, 180]);
const runtimePart = {
  spec: { name: "topwear", tag: "topwear", group: "body", depth: 0.4 },
  mesh: { rest, live: new Float32Array(rest), weight: new Float32Array([1, 1, 0, 0]) },
  eyeSide: null, isEye: false, isLid: false, shell: null,
  weight: { mode: "gradient_y", top: 1, bottom: 0, y_top: 100, y_bottom: 180 },
  softMorph: { left: new Float32Array([0.8, 0.4, 0.2, 0]),
    right: new Float32Array([0, 0.3, 0.7, 0.2]),
    lowerBias: new Float32Array([0, 0.2, 0.8, 1]) },
};
const motion = {
  turnX: 0.35, turnY: -0.2, tiltRad: 0.06, breath: 0.5, breathAmp: 3,
  chestX: 0.004, chestCx: 120, breathTop: 100, breathBottom: 220,
  overrides: { ghost: false, neck: "normal", collar: null },
  squash: { l: 0, r: 0 }, blink: { l: 0, r: 0 }, lidRatio: 0.85,
  lidThickness: 0.18,
  softMorph: { enabled: true, morph: 0.5, strength: 0.4, horizontalPx: 2, verticalPx: 1,
    physicsDistribution: { version: 2, horizontal_gain: 0.45, vertical_gain: 1.0, vertical_floor: 0.35 } },
  bodySwayPosition: [1.25, -0.5],
  physics: { torso: { model: "inertial_relative_v2",
    left: { value: 0.1, velocity: 0.05 }, right: { value: 0.2, velocity: 0.1 },
    settleGain: 0.08, settleTimeScaleS: 0.03 } },
};
state.manifest = { anchors: { neck_pivot: [120, 100] } };
state.canvasW = 256; state.canvasH = 256; state.frameOperations = operations;
state.chestCx = motion.chestCx; state.breathTop = motion.breathTop; state.breathBottom = motion.breathBottom;
deform(runtimePart, 0, motion);
const reference = deformReference({
  mesh: { rest }, depth: runtimePart.spec.depth, group: "body", tag: "topwear",
  softMorph: runtimePart.softMorph, weight: runtimePart.weight,
}, { ...motion, canvasWidth: 256, canvasHeight: 256, neckPivot: [120, 100] }, operations);
let maxError = 0;
for (let i = 0; i < reference.length; i++) maxError = Math.max(maxError, Math.abs(reference[i] - runtimePart.mesh.live[i]));
if (maxError > 1e-4) throw new Error(`reference parity failed: max error ${maxError}`);

const makeSeamParts = () => [
  { name: "head", mesh: { live: new Float32Array([0, 0]) } },
  { name: "neck", mesh: { live: new Float32Array([10, 0]) } },
  { name: "topwear", mesh: { live: new Float32Array([0, 10]) } },
];
const constraint = { kind: "boundary_stitch", tolerance_px: 0, groups: [{ members: [
  { part: "head", vertex: 0, weight: 2 }, { part: "neck", vertex: 0, weight: 1 },
  { part: "topwear", vertex: 0, weight: 1 },
]}] };
const optimizedSeamParts = makeSeamParts();
const referenceSeamParts = makeSeamParts();
Runtime.applyBoundaryStitches(
  optimizedSeamParts.map((part) => ({ spec: { name: part.name }, mesh: part.mesh })),
  [constraint],
);
applyBoundaryStitchesReference(referenceSeamParts, [constraint]);
for (let i = 0; i < optimizedSeamParts.length; i++) {
  const optimized = optimizedSeamParts[i].mesh.live;
  const reference = referenceSeamParts[i].mesh.live;
  if (optimized[0] !== reference[0] || optimized[1] !== reference[1]
      || optimized[0] !== 2.5 || optimized[1] !== 2.5) {
    throw new Error("boundary stitch parity failed");
  }
}
console.log(`reference parity passed (max geometry error ${maxError.toExponential(2)})`);
