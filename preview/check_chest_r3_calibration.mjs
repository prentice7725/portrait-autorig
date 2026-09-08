// R3 contract check: separated physics authoring resolves into the existing
// runtime driver and range override without changing the generated base.
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { createUpperTorsoSecondaryDriver } = await import(new URL("physics.mjs", import.meta.url));

const base = {
  physics: { upper_torso_driver: {
    model: "inertial_relative_v2", profile: "soft", natural_frequency_hz: 1.8,
    damping_ratio: 0.75, lag_seconds_x: 0, lag_seconds_y: 1.4,
    max_displacement_px: 16,
  } },
  motion: { upper_torso_parametric_deformer: { ranges_px: { x: 6, y: 6 } } },
};
const authored = { physics: { upper_torso: {
  profile: "springy", input_mode: "translation", enabled: true,
  natural_frequency_hz: 2.7, damping_ratio: 0.42, lag_seconds_y: 0.8,
  max_displacement_px: 9.5,
} }, deformers: { upper_torso: { range_override: { x: 7, y: 11 } } } };
const resolved = Runtime.applyPhysicsAuthoring(
  Runtime.applyChestAuthoring(base, authored), authored);
if (base.physics.upper_torso_driver.damping_ratio !== 0.75)
  throw new Error("generated physics base was mutated");
if (resolved.physics.upper_torso_driver.natural_frequency_hz !== 2.7
    || resolved.physics.upper_torso_driver.damping_ratio !== 0.42
    || resolved.physics.upper_torso_driver.lag_seconds_y !== 0.8
    || resolved.physics.upper_torso_driver.max_displacement_px !== 9.5)
  throw new Error("R3 physics authoring did not resolve into the runtime driver");
const ranges = resolved.motion.upper_torso_parametric_deformer.ranges_px;
if (ranges.x !== 7 || ranges.y !== 11) throw new Error("R3 range correction did not resolve");
const driverSpec = resolved.physics.upper_torso_driver;
createUpperTorsoSecondaryDriver({
  model: driverSpec.model, profile: driverSpec.profile, inputMode: driverSpec.input_mode,
  naturalFrequencyHz: driverSpec.natural_frequency_hz, dampingRatio: driverSpec.damping_ratio,
  lagSecondsX: driverSpec.lag_seconds_x, lagSecondsY: driverSpec.lag_seconds_y,
  maxDisplacementPx: driverSpec.max_displacement_px,
});

const make = (frequency, damping, max) => createUpperTorsoSecondaryDriver({
  model: "inertial_relative_v2", naturalFrequencyHz: frequency, dampingRatio: damping,
  maxDisplacementPx: max, breathDisplacementPx: 0, poseBiasPx: 0,
  inertiaCouplingY: 3, dragCouplingY: 0, profile: "soft",
});
const response = (driver) => Math.abs(driver.setRelativeDisplacement(10).value);
const capped = response(make(2.7, 0.42, 0.5));
const uncapped = response(make(2.7, 0.42, 9.5));
if (!(capped <= 0.500001 && uncapped > capped)) throw new Error("R3 max displacement is not live");
console.log("R3 chest calibration checks passed");
