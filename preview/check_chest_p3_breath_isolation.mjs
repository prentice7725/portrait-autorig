// P3 breath isolation: breathing belongs to ParamBreath/global volume, not
// the inertial ParamBustY spring when a P3 deformer is active.
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { createUpperTorsoSecondaryDriver } = await import(new URL("physics.mjs", import.meta.url));

Runtime.state.manifest = {
  motion: { upper_torso_parametric_deformer: { enabled: true, version: 1 } },
  physics: { config: { update_hz: 60 }, upper_torso_driver: {
    model: "inertial_relative_v2", breath_displacement_px: 0.8, pose_bias_px: 0,
  } },
};
Runtime.state.p3SeparateBreath = true;
Runtime.state.physicsDrivers = { torso: createUpperTorsoSecondaryDriver({
  model: "inertial_relative_v2", profile: "springy", separateBreath: true,
  breathDisplacementPx: 0.8, poseBiasPx: 0,
}) };
Runtime.state.physicsAccumulator = 0;
Runtime.state.physicsLastNow = null;
Runtime.state.physicsSimTime = 0;
Runtime.state.bodySwayEnabled = false;
Runtime.state.bodyPulse = { x: 0, y: 0, vx: 0, vy: 0 };
Runtime.state.bodyMotion = { x: 0, y: 0, prevX: 0, prevY: 0, vx: 0, vy: 0,
  prevVx: 0, prevVy: 0, ax: 0, ay: 0 };
Runtime.state.motionQA = { inertia: true, inertiaOnly: false, asymmetry: 1,
  inertiaMultiplier: 1, settleMultiplier: 1, chestImpulseX: 0, chestImpulseY: 0 };
Runtime.state.physicsDrivers.torso.resetPhysics();

let maxBust = 0;
for (let tick = 0; tick <= 240; tick++) {
  const now = tick * 1000 / 60;
  Runtime.advancePhysics(now, { breath: Math.sin(tick * 0.09), angleY: 0, strandTarget: 0 });
  maxBust = Math.max(maxBust, Math.abs(Number(Runtime.state.physicsOutputs.torso?.value || 0)));
}
if (maxBust > 1e-8) throw new Error(`P3 breath leaked into Bust spring: ${maxBust}px`);
console.log(`P3 breath isolation passed (max ParamBustY source ${maxBust.toExponential(2)}px)`);
