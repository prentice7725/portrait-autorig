// P2.5 directive #61, #67: compare the optimized runtime.mjs v3 basis path
// (precomputed Float32Arrays, `applyChestBasis`) against reference-runtime
// .mjs's independently-written on-the-fly basis (`chestBasisFieldsAt`/
// `applyChestBasisFields`) for q-only, v-only, shear-only, and combined
// stress. Tolerance <= 1e-4px per directive #67.
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
const { makeCompiledTopwearFixture, makeChestMotion, attachChestBasis, BASIS_V3_DISTRIBUTION } = await import(
  new URL("qa_compiled_topwear.mjs", import.meta.url));

state.manifest = { anchors: {} };
state.canvasW = 256; state.canvasH = 256;
const operations = [{ id: "chest", kind: "local_soft_field", phase: "secondary" }];
state.frameOperations = operations;
state.motionQA = { asymmetry: 1, settleMultiplier: 1, side: "both", shapeGain: null, poseActive: false };

const cases = [
  { name: "q-only", q: 5, v: 0, bodyVx: 0, bodyVy: 0 },
  { name: "v-only", q: 0, v: 30, bodyVx: 0, bodyVy: 0 },
  { name: "shear-only", q: 0, v: 0, bodyVx: 250, bodyVy: -180 },
  { name: "combined", q: -3.5, v: -18, bodyVx: 150, bodyVy: 300 },
];

let worst = 0;
for (const stress of cases) {
  const part = attachChestBasis(Runtime, makeCompiledTopwearFixture(), BASIS_V3_DISTRIBUTION);
  const torso = { model: "inertial_relative_v2",
    left: { value: stress.q, velocity: stress.v }, right: { value: stress.q * 0.8, velocity: stress.v * 0.8 },
    settleTimeScaleS: 0.03 };
  const motion = makeChestMotion(torso, { physicsDistribution: BASIS_V3_DISTRIBUTION });
  motion.bodyVelocityX = stress.bodyVx;
  motion.bodyVelocityY = stress.bodyVy;
  deform(part, 0, motion);

  const referencePart = { mesh: { rest: part.mesh.rest }, depth: part.spec.depth, group: part.spec.group,
    tag: part.spec.tag, weight: part.weight, softMorph: part.softMorph };
  const referenceMotion = { ...motion, canvasWidth: 256, canvasHeight: 256 };
  const expected = deformReference(referencePart, referenceMotion, operations);

  let maxError = 0;
  for (let i = 0; i < expected.length; i++)
    maxError = Math.max(maxError, Math.abs(expected[i] - part.mesh.live[i]));
  console.log(`${stress.name}: max error ${maxError.toExponential(2)}px`);
  worst = Math.max(worst, maxError);
  if (maxError > 1e-4) throw new Error(`${stress.name} reference parity failed: ${maxError}px`);
}

console.log(`chest basis reference parity passed (worst case ${worst.toExponential(2)}px)`);
