// Dedicated chest geometry oracle gate. The broader reference parity test also
// covers this path; this script keeps the P2.3 physical-unit contract obvious.
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
const rest = new Float32Array([100, 110, 120, 110, 100, 160, 120, 160]);
const softMorph = { left: new Float32Array([0.9, 0.5, 0.2, 0]),
  right: new Float32Array([0, 0.4, 0.8, 0.2]), lowerBias: new Float32Array([0, 0.2, 0.8, 1]) };
const operations = [{ id: "chest", kind: "local_soft_field", phase: "secondary" }];
const part = { spec: { name: "topwear", tag: "topwear", group: "body", depth: 0.4 },
  mesh: { rest, live: new Float32Array(rest), weight: new Float32Array([1, 1, 1, 1]) }, eyeSide: null, isEye: false,
  isLid: false, shell: null, weight: { mode: "constant", value: 1 }, softMorph };
const motion = { turnX: 0, turnY: 0, tiltRad: 0, shell: 0, squash: { l: 0, r: 0 }, blink: { l: 0, r: 0 },
  overrides: { ghost: false, neck: "normal", collar: null }, softMorph: { enabled: true, morph: 0, strength: 0,
  horizontalPx: 0, verticalPx: 0 }, bodySwayPosition: [0, 0],
  physics: { torso: { model: "inertial_relative_v2", value: -3,
    left: { value: -3, velocity: 5 }, right: { value: -2.5, velocity: 5.5 },
    settleTimeScaleS: 0.03 } } };
state.manifest = { anchors: {} }; state.canvasW = 256; state.canvasH = 256;
state.frameOperations = operations; state.motionQA = { asymmetry: 1, settleMultiplier: 1 };
deform(part, 0, motion);
const expected = deformReference({ mesh: { rest }, depth: 0.4, group: "body", tag: "topwear",
  weight: part.weight, softMorph }, { ...motion, canvasWidth: 256, canvasHeight: 256 }, operations);
let maxError = 0;
for (let i = 0; i < expected.length; i++) maxError = Math.max(maxError, Math.abs(expected[i] - part.mesh.live[i]));
if (maxError > 1e-4) throw new Error(`chest geometry parity failed: ${maxError}`);

for (const requested of [1, 2, 4]) {
  const probe = { spec: { name: "topwear", tag: "topwear", group: "body", depth: 0.4 },
    mesh: { rest: new Float32Array([100, 160]), live: new Float32Array([100, 160]),
      weight: new Float32Array([1]) }, eyeSide: null, isEye: false, isLid: false, shell: null,
    weight: { mode: "constant", value: 1 },
    softMorph: { left: new Float32Array([1]), right: new Float32Array([0]), lowerBias: new Float32Array([1]) } };
  const probeMotion = { ...motion, physics: { torso: { model: "inertial_relative_v2",
    left: { value: requested, velocity: 0 }, right: { value: 0, velocity: 0 },
    settleTimeScaleS: 0.03 } } };
  deform(probe, 0, probeMotion);
  const measured = Math.abs(probe.mesh.live[1] - probe.mesh.rest[1]);
  if (Math.abs(measured - requested) > requested * 0.15)
    throw new Error(`${requested}px geometry response measured ${measured}px`);
}
console.log("chest geometry parity passed");
