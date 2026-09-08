// R3 end-to-end calibration regression.  This intentionally drives the same
// runtime path as the preview: Body Kick Y -> root derivatives -> torso
// driver -> ParamBustY source -> P3 deformation -> compiled mesh probes.
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { createUpperTorsoSecondaryDriver } = await import(new URL("physics.mjs", import.meta.url));
const { makeCompiledTopwearFixture, makeChestMotion } = await import(new URL("qa_compiled_topwear.mjs", import.meta.url));
const { makeP3Fixture } = await import(new URL("qa_chest_p3.mjs", import.meta.url));

function run(calibration) {
  const part = makeCompiledTopwearFixture();
  part.chestParametric = makeP3Fixture(part);
  Runtime.state.manifest = { anchors: {}, parameters: [], physics: {
    config: { update_hz: 60 }, upper_torso_driver: {
      model: "inertial_relative_v2", breath_displacement_px: 0.8,
      pose_bias_px: 0.15, ...calibration,
    },
  }, motion: { body_sway: { enabled: false } } };
  Runtime.state.frameOperations = [
    { id: "body", kind: "body_sway", phase: "primary" },
    { id: "p3", kind: "chest_parametric_deformer", phase: "secondary", config: part.chestParametric },
  ];
  Runtime.state.motionQA = { inertia: true, inertiaOnly: false, asymmetry: 1,
    inertiaMultiplier: 1, settleMultiplier: 1, chestImpulseX: 0, chestImpulseY: 0,
    side: "both", shapeGain: null, poseActive: false, poseQ: 0, poseV: 0, p3Pose: null };
  Runtime.state.physicsDrivers = { torso: createUpperTorsoSecondaryDriver({
    model: "inertial_relative_v2", profile: calibration.profile || "soft",
    naturalFrequencyHz: calibration.natural_frequency_hz,
    dampingRatio: calibration.damping_ratio,
    lagSecondsX: calibration.lag_seconds_x ?? 0,
    lagSecondsY: calibration.lag_seconds_y ?? 1.4,
    maxDisplacementPx: calibration.max_displacement_px ?? 16,
    breathDisplacementPx: 0.8, poseBiasPx: 0.15,
    inertiaCouplingY: 3, dragCouplingY: 0,
  }) };
  Runtime.state.bodySwayEnabled = false;
  Runtime.state.p3SeparateBreath = true;
  Runtime.resetPhysics();
  Runtime.state.bodyPulse.vy = 48;
  const probes = Runtime.selectChestProbes(part);
  const source = [], paramY = [], mesh = [], root = [];
  for (let tick = 1; tick <= 240; tick++) {
    Runtime.advancePhysics(tick * 1000 / 60, { breath: 0, angleY: 0, strandTarget: 0 });
    source.push(Number(Runtime.state.physicsOutputs.torso.value));
    root.push(Math.abs(Runtime.state.bodyMotion.vy));
    const motion = makeChestMotion(Runtime.state.physicsOutputs.torso, { physicsDistribution: { version: 2 } });
    motion.bodySwayPosition = [Runtime.state.bodyMotion.x, Runtime.state.bodyMotion.y];
    paramY.push(Runtime.chestParametricValues(motion, part.chestParametric).y);
    Runtime.deform(part, tick * 1000 / 60, motion);
    const index = probes.leftPrimary * 2;
    mesh.push(Math.hypot(part.mesh.live[index] - part.mesh.rest[index] - Runtime.state.bodyMotion.x,
      part.mesh.live[index + 1] - part.mesh.rest[index + 1] - Runtime.state.bodyMotion.y));
  }
  return { source, paramY, mesh, root };
}

const soft = run({ profile: "soft", natural_frequency_hz: 1.8, damping_ratio: 0.75,
  lag_seconds_y: 0.25, max_displacement_px: 16 });
const springy = run({ profile: "springy", natural_frequency_hz: 2.2, damping_ratio: 0.35,
  lag_seconds_y: 1.4, max_displacement_px: 16 });
const trajectoryDelta = Math.max(...soft.source.map((value, index) => Math.abs(value - springy.source[index])));
const paramDelta = Math.max(...soft.paramY.map((value, index) => Math.abs(value - springy.paramY[index])));
const meshDelta = Math.max(...soft.mesh.map((value, index) => Math.abs(value - springy.mesh[index])));
if (!(trajectoryDelta > 0.01 && paramDelta > 0.001 && meshDelta > 0.01))
  throw new Error(`R3 calibration did not change real trajectory: source ${trajectoryDelta}, ParamBustY ${paramDelta}, mesh ${meshDelta}`);
const softPeak = Math.max(...soft.source.map(Math.abs));
const springyPeak = Math.max(...springy.source.map(Math.abs));
if (!(springyPeak > softPeak))
  throw new Error(`lower-damping calibration did not increase kick response: soft ${softPeak}, springy ${springyPeak}`);
if (soft.root.every((value) => value < 0.01) || springy.root.every((value) => value < 0.01))
  throw new Error("Body Kick Y did not produce root derivatives");
console.log(`R3 real Body Kick calibration passed (source Δ ${trajectoryDelta.toFixed(3)}px, mesh Δ ${meshDelta.toFixed(3)}px)`);
