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
  { id: "tilt", kind: "weighted_rotation", phase: "primary" },
  { id: "breath", kind: "continuous_field", phase: "primary" },
];
const rest = new Float32Array([100, 100, 140, 100, 100, 180, 140, 180]);
const runtimePart = {
  spec: { name: "topwear", tag: "topwear", group: "body", depth: 0.4 },
  mesh: { rest, live: new Float32Array(rest), weight: new Float32Array([1, 1, 0, 0]) },
  eyeSide: null, isEye: false, isLid: false, shell: null,
  weight: { mode: "gradient_y", top: 1, bottom: 0, y_top: 100, y_bottom: 180 },
  softMorph: null,
};
const motion = {
  turnX: 0.35, turnY: -0.2, tiltRad: 0.06, breath: 0.5, breathAmp: 3,
  chestX: 0.004, chestCx: 120, breathTop: 100, breathBottom: 220,
  overrides: { ghost: false, neck: "normal", collar: null },
  squash: { l: 0, r: 0 }, blink: { l: 0, r: 0 }, lidRatio: 0.85,
  lidThickness: 0.18, softMorph: { enabled: false },
};
state.manifest = { anchors: { neck_pivot: [120, 100] } };
state.canvasW = 256; state.canvasH = 256; state.frameOperations = operations;
state.chestCx = motion.chestCx; state.breathTop = motion.breathTop; state.breathBottom = motion.breathBottom;
deform(runtimePart, 0, motion);
const reference = deformReference({
  mesh: { rest }, depth: runtimePart.spec.depth, group: "body", weight: runtimePart.weight,
}, { ...motion, canvasWidth: 256, canvasHeight: 256, neckPivot: [120, 100] }, operations);
let maxError = 0;
for (let i = 0; i < reference.length; i++) maxError = Math.max(maxError, Math.abs(reference[i] - runtimePart.mesh.live[i]));
if (maxError > 1e-4) throw new Error(`reference parity failed: max error ${maxError}`);

const seamParts = [
  { name: "head", mesh: { live: new Float32Array([0, 0]) } },
  { name: "neck", mesh: { live: new Float32Array([10, 0]) } },
  { name: "topwear", mesh: { live: new Float32Array([0, 10]) } },
];
const constraint = { kind: "boundary_stitch", tolerance_px: 0, groups: [{ members: [
  { part: "head", vertex: 0, weight: 2 }, { part: "neck", vertex: 0, weight: 1 },
  { part: "topwear", vertex: 0, weight: 1 },
]}] };
Runtime.applyBoundaryStitches(seamParts.map((part) => ({ spec: { name: part.name }, mesh: part.mesh })), [constraint]);
applyBoundaryStitchesReference(seamParts, [constraint]);
for (let i = 0; i < seamParts.length; i++) {
  if (seamParts[i].mesh.live[0] !== 2.5 || seamParts[i].mesh.live[1] !== 2.5)
    throw new Error("boundary stitch parity failed");
}
console.log(`reference parity passed (max geometry error ${maxError.toExponential(2)})`);
