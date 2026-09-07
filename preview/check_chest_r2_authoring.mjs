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
console.log("R2 chest authoring passed (base immutable, cage/keyform resolved, physics untouched)");
