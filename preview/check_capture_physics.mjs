// Golden-mode capture contract: reset -> warmup -> fixed ticks must replay
// identically, independent of prior interactive state.
const controls = {};
const control = (id) => (controls[id] ||= {
  id, checked: id === "doBlink" || id === "doBreathe", value: "0",
  textContent: "", innerHTML: "", addEventListener() {}, append() {}, appendChild() {},
  classList: { add() {}, remove() {} }, click() {},
});
globalThis.document = { getElementById: control, createElement: () => control("tmp"), addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { createUpperTorsoSecondaryDriver } = await import(new URL("physics.mjs", import.meta.url));

function capture() {
  Runtime.state.physicsDrivers = {
    torso: createUpperTorsoSecondaryDriver({ profile: "soft" }),
  };
  return Runtime.preparePhysicsCapture(0.25, { breath: 1, angleY: 0.2 });
}
const first = capture();
const second = capture();
const a = first.torso, b = second.torso;
if (a.value !== b.value || a.velocity !== b.velocity || a.degraded || b.degraded)
  throw new Error("capture reset/warmup is not deterministic");
Runtime.state.physicsDrivers = null;
const asymmetric = createUpperTorsoSecondaryDriver({ profile: "soft", turnAsymmetry: 0.2 });
asymmetric.resetPhysics();
const asymmetricFrame = asymmetric.stepPhysicsFixed(8, 1, 0.5);
if (!(asymmetricFrame.left.value !== asymmetricFrame.right.value))
  throw new Error("torso turn asymmetry did not produce independent lobe outputs");
const warmedAfterHistory = createUpperTorsoSecondaryDriver({ profile: "soft", inputMode: "velocity" });
warmedAfterHistory.stepPhysicsFixed(1, 1, 0);
warmedAfterHistory.warmupPhysics(0, 0, 0);
const cleanReference = createUpperTorsoSecondaryDriver({ profile: "soft", inputMode: "velocity" });
cleanReference.warmupPhysics(0, 0, 0);
const afterWarmup = warmedAfterHistory.stepPhysicsFixed(1, 1, 0);
const cleanStep = cleanReference.stepPhysicsFixed(1, 1, 0);
if (afterWarmup.left.value !== cleanStep.left.value || afterWarmup.right.value !== cleanStep.right.value)
  throw new Error("torso warmup did not clear input history");
const coupled = createUpperTorsoSecondaryDriver({ velocityGain: 1, accelerationGain: 0 });
const uncoupled = createUpperTorsoSecondaryDriver({ velocityGain: 0, accelerationGain: 0 });
const coupledFrame = coupled.stepPhysicsFixed(1, 0, 0, 1, 0);
const uncoupledFrame = uncoupled.stepPhysicsFixed(1, 0, 0, 1, 0);
if (!(coupledFrame.value > uncoupledFrame.value))
  throw new Error("torso body velocity coupling was not applied");
console.log("capture physics golden check passed");
