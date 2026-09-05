import { calibratePhysicalResponse, createUpperTorsoSecondaryDriver } from "./physics.mjs";

for (const requested of [1, 2, 4]) {
  const driver = createUpperTorsoSecondaryDriver({ model: "inertial_relative_v2" });
  driver.setRelativeDisplacement(requested);
  const measured = driver.stepPhysicsFixed(0).left.value;
  if (Math.abs(measured - requested) > requested * 0.15)
    throw new Error(`${requested}px QA response measured ${measured}px`);
}

const calibration = calibratePhysicalResponse({ desiredPeakPx: 4, desiredSettleS: 0.6,
  desiredOvershootRatio: 0.1 });
if (!(calibration.natural_frequency_hz > 0 && calibration.damping_ratio > 0
    && calibration.calibrated_impulse_px_s > 0))
  throw new Error("physical response calibration returned invalid parameters");

const clamped = createUpperTorsoSecondaryDriver({ model: "inertial_relative_v2",
  maxDisplacementPx: 4 });
clamped.setRelativeDisplacement(12);
if (clamped.stepPhysicsFixed(0).left.value !== 4)
  throw new Error("physical displacement clamp was not reported in px");

console.log("physical response checks passed");
