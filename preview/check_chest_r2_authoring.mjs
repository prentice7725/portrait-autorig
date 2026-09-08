// R2 authoring contract check: explicit cage/keyform overrides are applied to
// a generated P3 manifest without mutating the generated base or physics.
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: {
    add() {}, remove() {}, toggle() {},
  } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { makeCompiledTopwearFixture } = await import(new URL("qa_compiled_topwear.mjs", import.meta.url));
const { makeP3Fixture } = await import(new URL("qa_chest_p3.mjs", import.meta.url));

const points = (offset) => Array.from({ length: 24 }, (_, index) => [
  index + offset, index * 2 + offset,
]);
const base = {
  version: "0.2",
  parts: [{ name: "topwear", tag: "topwear", source_instance_id: "topwear_instance" }],
  motion: {
    upper_torso_parametric_deformer: {
      enabled: true, version: 1,
      target_instance: "topwear_instance", target_part: "topwear", target_tag: "topwear",
      cage: { cols: 6, rows: 4, bounds: [1, 1, 7, 7], rest_points: points(0) },
      keyforms: { neutral: points(0).map(() => [0, 0]) },
    },
  },
  deformers: [{ kind: "chest_parametric_deformer", config: {
    target_instance: "topwear_instance", target_part: "topwear", target_tag: "topwear",
    cage: { cols: 6, rows: 4, bounds: [1, 1, 7, 7], rest_points: points(0) },
    keyforms: { neutral: points(0).map(() => [0, 0]) },
  } }],
  physics: { upper_torso_driver: { damping: 0.5 } },
};
const generatedSnapshot = JSON.stringify(base);
const authoring = {
  version: 1,
  source_revision: "assembly-revision",
  deformers: {
    upper_torso: {
      source_instance_id: "topwear_instance",
      cage_override: { bounds: [0, 0, 8, 8], rest_points: points(10) },
      keyform_overrides: { bust_y_pos: points(20).map(([x, y]) => [x, y]) },
    },
  },
};

const resolved = Runtime.applyChestAuthoring(base, authoring);
const spec = resolved.motion.upper_torso_parametric_deformer;
if (JSON.stringify(base) !== generatedSnapshot) throw new Error("generated base was mutated");
if (JSON.stringify(spec.cage.bounds) !== JSON.stringify([0, 0, 8, 8]))
  throw new Error("R2 cage bounds override was not resolved");
if (spec.cage.rest_points[0][0] !== 10) throw new Error("R2 cage point override was not resolved");
if (spec.keyforms.bust_y_pos[23][0] !== 43) throw new Error("R2 keyform override was not resolved");
if (resolved.deformers[0].config.cage.bounds[2] !== 8)
  throw new Error("P3 deformer config lost the R2 cage override");
if (resolved.physics.upper_torso_driver.damping !== 0.5)
  throw new Error("R2 authoring touched physics");

const staleBinding = Runtime.applyChestAuthoring(base, {
  deformers: { upper_torso: {
    source_instance_id: "a-different-instance", target_tag: "topwear",
    cage_override: { bounds: [0, 0, 8, 8] },
  } },
});
if (staleBinding.motion.upper_torso_parametric_deformer.cage.bounds[0] !== 1)
  throw new Error("R2 ignored stable binding priority");

const edited = Runtime.applyChestAuthoring(base, authoring);
edited.motion.upper_torso_parametric_deformer.cage.bounds = [2, 2, 10, 10];
const saved = Runtime.captureChestAuthoring(edited, authoring);
if (saved.deformers.upper_torso.source_instance_id !== "topwear_instance")
  throw new Error("stable R2 source binding was not preserved");
if (saved.deformers.upper_torso.cage_override.bounds[0] !== 2)
  throw new Error("R2 Save did not capture the current resolved cage");
if (Object.hasOwn(saved.deformers.upper_torso.keyform_overrides, "neutral"))
  throw new Error("R2 Save persisted an editable neutral keyform");

const autoPart = makeCompiledTopwearFixture();
const autoSpec = makeP3Fixture(autoPart);
autoPart.chestParametric = autoSpec;
const shiftedPoints = autoSpec.cage.rest_points.map(([x, y], index) =>
  index === 14 ? [x + 12, y] : [x, y]);
const correctedManifest = Runtime.applyChestAuthoring({
  motion: { upper_torso_parametric_deformer: autoSpec }, deformers: [],
}, { deformers: { upper_torso: {
  target_tag: "topwear", cage_override: { rest_points: shiftedPoints },
} } });
const correctedPart = makeCompiledTopwearFixture();
correctedPart.chestParametric = correctedManifest.motion.upper_torso_parametric_deformer;
Runtime.state.canvasW = 256; Runtime.state.canvasH = 256;
Runtime.state.manifest = { anchors: {}, parameters: [], motion: {}, evaluation: { phases: ["secondary"] } };
Runtime.state.frameOperations = [{ kind: "chest_parametric_deformer", phase: "secondary", config: correctedPart.chestParametric }];
Runtime.state.motionQA = { p3Pose: { x: 0, y: 1 }, side: "both" };
const motion = { now: 0, turnX: 0, turnY: 0, tiltRad: 0, shell: 0, yaw: 0, pitch: 0,
  blink: { l: 0, r: 0 }, squash: { l: 0, r: 0 }, mouthOpen: 0, gazeX: 0, gazeY: 0,
  breath: 0, breathAmp: 0, chestX: 0, bodySwayPosition: [0, 0],
  overrides: { ghost: false, neck: "normal", collar: null }, physics: {} };
const autoRest = new Float32Array(autoPart.mesh.rest);
Runtime.deform(autoPart, 0, motion);
Runtime.deform(correctedPart, 0, motion);
let cageDifference = 0;
for (let index = 0; index < autoRest.length; index++)
  cageDifference = Math.max(cageDifference, Math.abs(correctedPart.mesh.live[index] - autoPart.mesh.live[index]));
if (!(cageDifference > 1e-5)) throw new Error("R2 cage point did not affect runtime geometry");

Runtime.state.motionQA.p3Pose = { x: 0, y: 0 };
Runtime.deform(correctedPart, 0, motion);
for (let index = 0; index < autoRest.length; index++)
if (Math.abs(correctedPart.mesh.live[index] - autoRest[index]) > 1e-6)
    throw new Error("R2 neutral pose is not exact rest");
const cleared = Runtime.clearChestAuthoring({ ...saved,
  physics: { upper_torso: { natural_frequency_hz: 2.7 } },
});
if (Object.hasOwn(cleared.deformers, "upper_torso"))
  throw new Error("R2 reset left a chest override behind");
if (cleared.physics.upper_torso.natural_frequency_hz !== 2.7)
  throw new Error("R2 reset deleted R3 physics authoring");
console.log(`R2 chest authoring passed (cage delta ${cageDifference.toFixed(3)}px, neutral exact rest)`);
