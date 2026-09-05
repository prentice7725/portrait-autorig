// A fixed-tick runtime must produce the same final *compiled topwear geometry*
// regardless of render FPS. This exercises bodyPulse -> derivatives -> torso
// spring -> local_soft_field -> deform(), not a driver-only surrogate.
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

function run(fps) {
  Runtime.state.manifest = { anchors: {}, physics: { config: { update_hz: 60 },
    upper_torso_driver: { model: "inertial_relative_v2" } },
    motion: { body_sway: { enabled: false } } };
  Runtime.state.frameOperations = [
    { id: "body", kind: "body_sway", phase: "primary" },
    { id: "chest", kind: "local_soft_field", phase: "secondary" },
  ];
  Runtime.state.motionQA = { inertia: true, inertiaOnly: false, asymmetry: 1,
    inertiaMultiplier: 1, settleMultiplier: 1, chestImpulseX: 0, chestImpulseY: 0 };
  Runtime.state.physicsDrivers = { torso: createUpperTorsoSecondaryDriver({
    model: "inertial_relative_v2", breathDisplacementPx: 0,
    poseBiasGain: 0, inertiaCouplingY: 0.5, dragCouplingY: 0, profile: "springy",
  }) };
  Runtime.state.bodySwayEnabled = false;
  Runtime.resetPhysics();
  Runtime.state.bodyPulse.vy = 48;
  const part = makeCompiledTopwearFixture();
  const probes = Runtime.selectChestProbes(part);
  let now = 0;
  for (let frame = 0; frame <= fps; frame++) {
    now = frame * 1000 / fps;
    Runtime.advancePhysics(now, { breath: 0, angleY: 0, strandTarget: 0 });
    const motion = makeChestMotion(Runtime.state.physicsOutputs.torso);
    motion.bodySwayPosition = [Runtime.state.bodyMotion.x, Runtime.state.bodyMotion.y];
    Runtime.deform(part, now, motion);
  }
  const read = (index) => [part.mesh.live[index * 2], part.mesh.live[index * 2 + 1]];
  return { left: read(probes.leftPrimary), right: read(probes.rightPrimary),
    lower: read(probes.leftLower), lock: read(probes.lock), body: [Runtime.state.bodyMotion.x,
      Runtime.state.bodyMotion.y] };
}

const reference = run(60);
for (const fps of [30, 120]) {
  const sample = run(fps);
  for (const key of ["left", "right", "lower", "lock", "body"]) {
    const delta = Math.hypot(sample[key][0] - reference[key][0], sample[key][1] - reference[key][1]);
    if (delta > 0.02) throw new Error(`runtime geometry parity failed at ${fps} FPS (${key}: ${delta}px)`);
  }
}
console.log("runtime geometry framerate parity passed (30/60/120 FPS)");
