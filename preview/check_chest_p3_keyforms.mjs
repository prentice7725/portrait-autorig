// P3-A: direct keyform, rest-invariance, continuity, and runtime/reference
// parity checks. Physics is deliberately bypassed; this is the acceptance
// gate that keeps deformer shape separate from driver tuning.
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
const { deformReference } = await import(new URL("reference-runtime.mjs", import.meta.url));
const { makeCompiledTopwearFixture } = await import(new URL("qa_compiled_topwear.mjs", import.meta.url));
const { makeP3Fixture } = await import(new URL("qa_chest_p3.mjs", import.meta.url));

state.canvasW = 256; state.canvasH = 256;
state.manifest = { anchors: {}, parameters: [
  { id: "ParamBustX", min: -1, max: 1, default: 0 },
  { id: "ParamBustY", min: -1, max: 1, default: 0 },
] };
state.motionQA = { p3Pose: { x: 0, y: 0 }, side: "both" };
const operations = [{ id: "p3", kind: "chest_parametric_deformer", phase: "secondary" }];
state.frameOperations = operations;
const base = makeCompiledTopwearFixture();
const p3 = makeP3Fixture(base);
base.chestParametric = p3;
base.spec.tag = "topwear";

const rest = new Float32Array(base.mesh.rest);
const run = (x, y) => {
  state.motionQA.p3Pose = { x, y };
  const motion = { now: 0, turnX: 0, turnY: 0, tiltRad: 0,
    blink: { l: 0, r: 0 }, squash: { l: 0, r: 0 }, mouthOpen: 0,
    gazeX: 0, gazeY: 0, overrides: { ghost: false, neck: "normal", collar: null },
    parameters: { ParamBustX: x, ParamBustY: y } };
  Runtime.deform(base, 0, motion);
  return new Float32Array(base.mesh.live);
};

const neutral = run(0, 0);
for (let i = 0; i < neutral.length; i++) if (Math.abs(neutral[i] - rest[i]) > 1e-6)
  throw new Error(`P3 rest invariance failed at ${i}: ${neutral[i]} != ${rest[i]}`);
const plus = run(0, 1), minus = run(0, -1);
const displacement = (a, i) => Math.hypot(a[i * 2] - rest[i * 2], a[i * 2 + 1] - rest[i * 2 + 1]);
const centre = 17; // fixture's central lower-middle vertex
if (!(displacement(plus, centre) > 0.5 && displacement(minus, centre) > 0.5))
  throw new Error("BustY keyforms did not move the mass centre");
const sweep = [];
for (let step = -10; step <= 10; step++) sweep.push(run(0, step / 10));
for (let s = 1; s < sweep.length; s++) {
  let jump = 0;
  for (let i = 0; i < rest.length; i++) jump = Math.max(jump, Math.abs(sweep[s][i] - sweep[s - 1][i]));
  if (jump > 1.0) throw new Error(`P3 keyform sweep jumped ${jump}px`);
}

const referencePart = { mesh: { rest }, spec: base.spec, tag: "topwear", group: "body",
  weight: base.weight, chestParametric: p3 };
const motion = { canvasWidth: 256, canvasHeight: 256, parameters: { ParamBustX: 0.7, ParamBustY: -0.65 },
  turnX: 0, turnY: 0, tiltRad: 0, blink: { l: 0, r: 0 }, squash: { l: 0, r: 0 },
  mouthOpen: 0, gazeX: 0, gazeY: 0, overrides: { ghost: false, neck: "normal", collar: null } };
state.motionQA.p3Pose = null;
base.mesh.live = new Float32Array(rest);
Runtime.deform(base, 0, motion);
const expected = deformReference(referencePart, motion, operations);
let worst = 0;
for (let i = 0; i < expected.length; i++) worst = Math.max(worst, Math.abs(expected[i] - base.mesh.live[i]));
if (worst > 1e-4) throw new Error(`P3 reference parity failed: ${worst}px`);
console.log(`P3 keyforms passed (centre +${displacement(plus, centre).toFixed(2)}px, parity ${worst.toExponential(2)}px)`);
