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
console.log("capture physics golden check passed");
