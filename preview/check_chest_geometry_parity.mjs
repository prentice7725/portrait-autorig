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
const { makeCompiledTopwearFixture, makeChestMotion } = await import(
  new URL("qa_compiled_topwear.mjs", import.meta.url));
const compiled = makeCompiledTopwearFixture();
const { rest } = compiled.mesh;
const { softMorph } = compiled;
const operations = [{ id: "chest", kind: "local_soft_field", phase: "secondary" }];
const part = compiled;
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
  const probe = makeCompiledTopwearFixture();
  const probes = Runtime.selectChestProbes(probe);
  const torso = { model: "inertial_relative_v2",
    left: { value: requested, velocity: 0 }, right: { value: 0, velocity: 0 },
    settleTimeScaleS: 0.03 };
  const probeMotion = makeChestMotion(torso);
  deform(probe, 0, probeMotion);
  const measured = Runtime.measureProbeDisplacement(probe, probes.leftPrimary);
  const lock = Runtime.measureProbeDisplacement(probe, probes.lock);
  if (Math.abs(measured - requested) > requested * 0.15)
    throw new Error(`${requested}px compiled geometry response measured ${measured}px`);
  if (lock > 0.05) throw new Error(`${requested}px lock probe moved ${lock}px`);
}
console.log("chest geometry parity passed");
