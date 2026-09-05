// Exercise the real runtime body-pulse -> fixed derivative -> torso -> field
// path. This intentionally does not call the torso driver directly.
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { createUpperTorsoSecondaryDriver } = await import(new URL("physics.mjs", import.meta.url));
Runtime.state.manifest = { physics: { config: { update_hz: 60 },
  upper_torso_driver: { model: "inertial_relative_v2" } }, motion: { body_sway: { enabled: false } } };
Runtime.state.physicsDrivers = { torso: createUpperTorsoSecondaryDriver({ model: "inertial_relative_v2",
  breathGain: 0, poseBiasGain: 0, inertiaCouplingY: 0.5, dragCouplingY: 0,
  profile: "springy" }) };
Runtime.state.bodySwayEnabled = false;
Runtime.resetPhysics();
Runtime.state.bodyPulse.vy = 48;
const bodyPositions = [], bodyVelocities = [], chestValues = [];
for (let tick = 1; tick <= 240; tick++) {
  Runtime.advancePhysics(tick * 1000 / 60, { breath: 0, angleY: 0, strandTarget: 0 });
  bodyPositions.push(Runtime.state.bodyMotion.y);
  bodyVelocities.push(Runtime.state.bodyMotion.vy);
  chestValues.push(Runtime.state.physicsOutputs.torso.left.value);
}
const bodyStart = bodyPositions.findIndex((value) => Math.abs(value) > 0.01);
const bodyStop = bodyVelocities.findIndex((value, index) => index > 20
  && bodyVelocities.slice(index, index + 8).every((v) => Math.abs(v) < 0.2));
const chestPeak = chestValues.reduce((best, value, index) =>
  Math.abs(value) > Math.abs(best.value) ? { value, index } : best, { value: 0, index: 0 });
if (!(bodyStart >= 0 && chestPeak.index > bodyStart && Math.abs(chestValues[bodyStart]) > 0))
  throw new Error("body kick did not reach chest through the runtime pipeline");
if (!(bodyStop < 0 || chestPeak.index >= bodyStart + 1))
  throw new Error("chest peaked before body motion");
if (Math.abs(chestValues.at(-1)) > 0.05)
  throw new Error("body kick chest response did not settle");
console.log(`body kick pipeline passed (body start ${bodyStart}, chest peak ${chestPeak.index})`);
