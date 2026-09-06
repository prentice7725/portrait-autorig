// P3-B real chain: Body Kick Y -> bodyPulse -> fixed derivatives -> torso
// spring -> ParamBustY -> P3 keyform/cage -> final topwear probes.
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
const { makeCompiledTopwearFixture, makeChestMotion } = await import(new URL("qa_compiled_topwear.mjs", import.meta.url));
const { makeP3Fixture } = await import(new URL("qa_chest_p3.mjs", import.meta.url));

const part = makeCompiledTopwearFixture();
part.chestParametric = makeP3Fixture(part);
Runtime.state.manifest = { anchors: {}, parameters: [
  { id: "ParamBustX", min: -1, max: 1, default: 0 },
  { id: "ParamBustY", min: -1, max: 1, default: 0 },
], physics: { config: { update_hz: 60 }, upper_torso_driver: {
  model: "inertial_relative_v2", breath_displacement_px: 0.8, pose_bias_px: 0.15,
} }, motion: { body_sway: { enabled: false } } };
Runtime.state.frameOperations = [
  { id: "body", kind: "body_sway", phase: "primary" },
  { id: "p3", kind: "chest_parametric_deformer", phase: "secondary", config: part.chestParametric },
];
Runtime.state.motionQA = { inertia: true, inertiaOnly: false, asymmetry: 1,
  inertiaMultiplier: 1, settleMultiplier: 1, chestImpulseX: 0, chestImpulseY: 0, p3Pose: null };
Runtime.state.physicsDrivers = { torso: createUpperTorsoSecondaryDriver({ model: "inertial_relative_v2",
  breathGain: 0, poseBiasGain: 0, inertiaCouplingY: 3, dragCouplingY: 0, profile: "springy" }) };
Runtime.state.bodySwayEnabled = false;
Runtime.resetPhysics();
Runtime.state.bodyPulse.vy = 48;
const probes = Runtime.selectChestProbes(part);
const centre = [], lower = [], upper = [], rootVelocity = [];
for (let tick = 1; tick <= 240; tick++) {
  Runtime.advancePhysics(tick * 1000 / 60, { breath: 0, angleY: 0, strandTarget: 0 });
  const motion = makeChestMotion(Runtime.state.physicsOutputs.torso, { physicsDistribution: { version: 2 } });
  motion.bodySwayPosition = [Runtime.state.bodyMotion.x, Runtime.state.bodyMotion.y];
  Runtime.deform(part, tick * 1000 / 60, motion);
  const relative = (index) => {
    const o = index * 2;
    return Math.hypot(part.mesh.live[o] - part.mesh.rest[o] - Runtime.state.bodyMotion.x,
      part.mesh.live[o + 1] - part.mesh.rest[o + 1] - Runtime.state.bodyMotion.y);
  };
  centre.push(relative(probes.leftPrimary)); lower.push(relative(probes.leftLower));
  upper.push(relative(10));
  rootVelocity.push(Math.abs(Runtime.state.bodyMotion.vy));
}
const stop = rootVelocity.findIndex((v, i) => i > 20
  && rootVelocity.slice(i, i + 8).every((value) => value < 2));
if (stop < 0) throw new Error("P3 Body Kick never reached a stopped-body interval");
const centreAtStop = centre[stop], lowerFollow = Math.max(...lower.slice(stop, stop + 20));
if (centreAtStop < 0.05) throw new Error(`P3 centre did not follow root: ${centreAtStop}px`);
if (Math.max(...lower) < Math.max(...centre)) throw new Error("P3 lower mass peak was weaker than centre");
if (Math.max(...upper) >= Math.max(...centre)) throw new Error("P3 upper attachment moved as much as centre");
if (lowerFollow < centreAtStop * 0.5) throw new Error("P3 lower mass did not follow centre");
if (centre.at(-1) > 0.05) throw new Error(`P3 kick did not settle: ${centre.at(-1)}px`);
console.log(`P3 real Body Kick passed (stop ${stop}, centre ${centreAtStop.toFixed(3)}px, lower ${lowerFollow.toFixed(3)}px)`);
