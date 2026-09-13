// P7 QA isolation regression: QA calibration is a transient runtime overlay,
// never an implicit mutation of the authored or generated manifest.
import assert from "node:assert/strict";
import { applyR3QaOverrides, createQaState, hasR3QaOverrides } from "./qa-state.mjs";

const generated = {
  physics: { upper_torso_driver: {
    model: "inertial_relative_v2", profile: "soft", natural_frequency_hz: 1.8,
    damping_ratio: 0.75, lag_seconds_y: 1.4, max_displacement_px: 16,
  } },
  motion: { upper_torso_parametric_deformer: { target_instance: "torso-1",
    ranges_px: { x: 6, y: 6 } } },
  deformers: [{ kind: "chest_parametric_deformer", config: {
    target_instance: "torso-1", ranges_px: { x: 6, y: 6 },
  } }],
};
const generatedBefore = JSON.stringify(generated);
const authored = { version: 1, physics: {}, deformers: {} };
const authoredBefore = JSON.stringify(authored);

const qa = createQaState();
qa.r3.physics.natural_frequency_hz = 3.2;
qa.r3.physics.damping_ratio = 0.35;
qa.r3.ranges.y = 11;
assert.equal(hasR3QaOverrides(qa), true);

const runtime = applyR3QaOverrides(generated, qa);
assert.equal(runtime.physics.upper_torso_driver.natural_frequency_hz, 3.2);
assert.equal(runtime.physics.upper_torso_driver.damping_ratio, 0.35);
assert.deepEqual(runtime.motion.upper_torso_parametric_deformer.ranges_px, { x: 6, y: 11 });
assert.deepEqual(runtime.deformers[0].config.ranges_px, { x: 6, y: 11 });
assert.equal(JSON.stringify(generated), generatedBefore, "generated base must remain immutable");
assert.equal(JSON.stringify(authored), authoredBefore, "QA must not mutate authored state");

assert.equal(hasR3QaOverrides(createQaState()), false);
assert.deepEqual(applyR3QaOverrides(generated, createQaState()), generated,
  "empty QA state must preserve the generated runtime exactly");
console.log("P7 QA isolation checks passed");
