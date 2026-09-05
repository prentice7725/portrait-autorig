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
const { makeCompiledTopwearFixture, makeChestMotion } = await import(
  new URL("qa_compiled_topwear.mjs", import.meta.url));
Runtime.state.manifest = { anchors: {}, physics: { config: { update_hz: 60 },
  upper_torso_driver: { model: "inertial_relative_v2" } }, motion: { body_sway: { enabled: false } } };
Runtime.state.frameOperations = [
  { id: "body", kind: "body_sway", phase: "primary" },
  { id: "chest", kind: "local_soft_field", phase: "secondary" },
];
Runtime.state.motionQA = { inertia: true, inertiaOnly: false, asymmetry: 1,
  inertiaMultiplier: 1, settleMultiplier: 1, chestImpulseX: 0, chestImpulseY: 0 };
Runtime.state.physicsDrivers = { torso: createUpperTorsoSecondaryDriver({ model: "inertial_relative_v2",
  breathGain: 0, poseBiasGain: 0, inertiaCouplingY: 3, dragCouplingY: 0,
  profile: "springy" }) };
Runtime.state.bodySwayEnabled = false;
Runtime.resetPhysics();
Runtime.state.bodyPulse.vy = 48;
const part = makeCompiledTopwearFixture();
const probes = Runtime.selectChestProbes(part);
if (!probes || probes.leftPrimary == null || probes.lock == null)
  throw new Error("compiled topwear probes were not selected");
const bodyPositions = [], bodyVelocities = [], chestValues = [], lockValues = [];
for (let tick = 1; tick <= 240; tick++) {
  Runtime.advancePhysics(tick * 1000 / 60, { breath: 0, angleY: 0, strandTarget: 0 });
  bodyPositions.push(Runtime.state.bodyMotion.y);
  bodyVelocities.push(Runtime.state.bodyMotion.vy);
  const motion = makeChestMotion(Runtime.state.physicsOutputs.torso);
  motion.bodySwayPosition = [Runtime.state.bodyMotion.x, Runtime.state.bodyMotion.y];
  Runtime.deform(part, tick * 1000 / 60, motion);
  const chestOffset = probes.leftPrimary * 2;
  const chestDx = part.mesh.live[chestOffset] - part.mesh.rest[chestOffset] - Runtime.state.bodyMotion.x;
  const chestDy = part.mesh.live[chestOffset + 1] - part.mesh.rest[chestOffset + 1] - Runtime.state.bodyMotion.y;
  chestValues.push(Math.hypot(chestDx, chestDy));
  const lockOffset = probes.lock * 2;
  const lockDx = part.mesh.live[lockOffset] - part.mesh.rest[lockOffset] - Runtime.state.bodyMotion.x;
  const lockDy = part.mesh.live[lockOffset + 1] - part.mesh.rest[lockOffset + 1] - Runtime.state.bodyMotion.y;
  lockValues.push(Math.hypot(lockDx, lockDy));
}
const bodyStart = bodyPositions.findIndex((value) => Math.abs(value) > 0.01);
// The pulse starts at 48 px/s; <2 px/s for eight fixed ticks is the
// deterministic "body has effectively stopped" interval used by this gate.
const bodyStopVelocityPxS = 2;
const bodyStop = bodyVelocities.findIndex((value, index) => index > 20
  && bodyVelocities.slice(index, index + 8).every((v) => Math.abs(v) < bodyStopVelocityPxS));
const chestPeak = chestValues.reduce((best, value, index) =>
  value > best.value ? { value, index } : best, { value: 0, index: 0 });
if (!(bodyStart >= 0 && chestPeak.index > bodyStart && chestValues[bodyStart] > 0))
  throw new Error("body kick did not reach chest through the runtime pipeline");
if (bodyStop < 0) throw new Error("body kick never reached a stopped-body interval");
if (!(chestValues[bodyStop] >= 0.15))
  throw new Error(`chest at body stop was only ${chestValues[bodyStop].toFixed(3)}px`);
const followThroughPeak = Math.max(...chestValues.slice(bodyStop, bodyStop + 20));
if (followThroughPeak < 0.15)
  throw new Error("chest did not retain follow-through after body motion stopped");
if (chestValues.at(-1) > 0.05)
  throw new Error("body kick chest response did not settle");
if (Math.max(...lockValues) > 0.05) throw new Error("chest lock moved during body kick");
console.log(`body kick pipeline passed (body start ${bodyStart}, body stop ${bodyStop}, chest peak ${chestPeak.index})`);
