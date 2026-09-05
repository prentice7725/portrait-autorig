import { calibratePhysicalResponse, createUpperTorsoSecondaryDriver } from "./physics.mjs";
import { makeCompiledTopwearFixture, makeChestMotion } from "./qa_compiled_topwear.mjs";

const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, addEventListener() {}, createElement: control };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});
const Runtime = await import(new URL("runtime.mjs", import.meta.url));

Runtime.state.manifest = { anchors: {}, motion: {}, physics: {} };
Runtime.state.canvasW = 768; Runtime.state.canvasH = 768;
Runtime.state.frameOperations = [{ id: "chest", kind: "local_soft_field", phase: "secondary" }];
Runtime.state.motionQA = { asymmetry: 1, settleMultiplier: 1 };

for (const requested of [1, 2, 4]) {
  const driver = createUpperTorsoSecondaryDriver({ model: "inertial_relative_v2",
    breathDisplacementPx: 0, poseBiasGain: 0 });
  Runtime.state.physicsDrivers = { torso: driver };
  Runtime.resetPhysics();
  Runtime.state.physicsOutputs.torso = driver.setRelativeDisplacement(requested);
  const part = makeCompiledTopwearFixture();
  const probes = Runtime.selectChestProbes(part);
  if (!probes || probes.leftPrimary == null || probes.rightPrimary == null || probes.lock == null)
    throw new Error("compiled topwear probes were not selected");
  Runtime.deform(part, 0, makeChestMotion(Runtime.state.physicsOutputs.torso));
  const measuredL = Runtime.measureProbeDisplacement(part, probes.leftPrimary);
  const measuredR = Runtime.measureProbeDisplacement(part, probes.rightPrimary);
  const lock = Runtime.measureProbeDisplacement(part, probes.lock);
  if (Math.abs(measuredL - requested) > requested * 0.15
      || Math.abs(measuredR - requested) > requested * 0.15)
    throw new Error(`${requested}px compiled topwear probe measured L/R ${measuredL}/${measuredR}px`);
  if (lock > 0.05) throw new Error(`lock probe moved ${lock}px at ${requested}px`);
  console.log(`Chest ${requested}px → compiled probes L ${measuredL.toFixed(2)}px, R ${measuredR.toFixed(2)}px`);
}

const calibration = calibratePhysicalResponse({ desiredPeakPx: 4, desiredSettleS: 0.6,
  desiredOvershootRatio: 0.1 });
if (!(calibration.natural_frequency_hz > 0 && calibration.damping_ratio > 0
    && calibration.calibrated_impulse_px_s > 0))
  throw new Error("physical response calibration returned invalid parameters");

const clamped = createUpperTorsoSecondaryDriver({ model: "inertial_relative_v2",
  maxDisplacementPx: 4, breathDisplacementPx: 0, poseBiasGain: 0 });
Runtime.state.physicsDrivers = { torso: clamped };
Runtime.resetPhysics();
Runtime.state.physicsOutputs.torso = clamped.setRelativeDisplacement(12);
const clampedPart = makeCompiledTopwearFixture();
const clampedProbes = Runtime.selectChestProbes(clampedPart);
Runtime.deform(clampedPart, 0, makeChestMotion(Runtime.state.physicsOutputs.torso));
const clampedMeasured = Runtime.measureProbeDisplacement(clampedPart, clampedProbes.leftPrimary);
if (Math.abs(clampedMeasured - 4) > 0.6)
  throw new Error(`compiled geometry clamp measured ${clampedMeasured}px`);

console.log("physical response checks passed");
