// P3 stable Edit Pose lifecycle regression.
// The test uses the real runtime exports and mode event, with a small DOM and
// physics-driver harness. It verifies that Edit pauses time-evolving physics,
// holds the authoring pose, and restores the previous Preview state on exit.
import assert from "node:assert/strict";

const controls = new Map();
function control(id) {
  if (!controls.has(id)) {
    controls.set(id, {
      id,
      checked: ["bodySway", "chestInertia", "doBlink", "doBreathe", "doTalk", "useArt"].includes(id),
      value: id === "r2EditMode" ? "" : "0",
      textContent: "",
      innerHTML: "",
      dataset: {},
      style: {},
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener() {},
      append() {},
      appendChild() {},
      remove() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
    });
  }
  return controls.get(id);
}

const listeners = new Map();
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};
globalThis.window = {
  addEventListener(type, listener) {
    if (!listeners.has(type)) listeners.set(type, []);
    listeners.get(type).push(listener);
  },
  dispatchEvent(event) {
    for (const listener of listeners.get(event.type) || []) listener(event);
  },
};
globalThis.document = {
  getElementById: control,
  createElement: () => control(`created-${controls.size}`),
  addEventListener() {},
};
globalThis.performance = { now: () => 1000 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch in harness"); };

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { state } = Runtime;

state.manifest = {
  parameters: [
    { id: "ParamAngleX", min: -1, max: 1, default: 0 },
    { id: "ParamBreath", min: -1, max: 1, default: 0 },
  ],
  physics: { config: { update_hz: 60 } },
  motion: { body_sway: { enabled: true } },
};
state.parameters = { ParamAngleX: 0.35, ParamBreath: 0.6 };
state.parameterOverrides = { ParamBreath: 0.6 };
state.turnX = 0.35;
state.turnY = -0.2;
state.tiltDeg = 4;
state.mouthOpen = 0.25;
state.gazeTargets = [0.3, -0.15];
state.motionQA = { inertia: true, inertiaOnly: false, asymmetry: 1, inertiaMultiplier: 1,
  settleMultiplier: 1, chestImpulseX: 0, chestImpulseY: 0, side: "both", shapeGain: null,
  poseActive: false, poseQ: 0, poseV: 0, p3Pose: null };
state.r2 = { pose: "bust_x_pos", editTarget: "cage", editMode: false,
  activePoint: null, dragging: false, dirty: false };
state.physicsOutputs = {};
let stepped = 0, reset = 0, warmed = 0;
state.physicsDrivers = {
  torso: {
    resetPhysics() { reset++; return { value: 0 }; },
    warmupPhysics(seconds) { warmed += seconds; return { value: 0 }; },
    stepPhysicsFixed() { stepped++; return { value: stepped }; },
  },
};
control("autoIdle").checked = true;
control("bodySway").checked = true;
control("chestInertia").checked = true;
control("doBlink").checked = true;
control("doBreathe").checked = true;
control("doTalk").checked = true;
control("r2EditMode").checked = false;
control("turnX").value = "0.35";
control("turnY").value = "-0.2";
control("gazeX").value = "0.3";
control("gazeY").value = "-0.15";

Runtime.resetPhysics();
Runtime.advancePhysics(0, { breath: 0, angleY: 0, strandTarget: 0 });
Runtime.advancePhysics(1000 / 60, { breath: 0, angleY: 0, strandTarget: 0 });
assert.ok(stepped > 0, "preview physics should step before Edit");
const steppedBeforeEdit = stepped;

window.dispatchEvent(new CustomEvent("rigstudio:modechange", { detail: { mode: "edit" } }));
assert.equal(state.editSession.active, true);
assert.equal(state.editSession.physicsSuspended, true);
assert.equal(state.turnX, 0, "Edit must enter at the stable neutral pose");
assert.equal(state.mouthOpen, 0, "Edit must clear transient mouth motion");
assert.equal(control("autoIdle").checked, false);
assert.equal(control("bodySway").checked, false);
assert.equal(control("doBlink").checked, false);
assert.equal(control("doBreathe").checked, false);
assert.equal(control("r2EditMode").checked, true, "Edit must enable direct manipulation");
Runtime.advancePhysics(5000, { breath: 1, angleY: 1, strandTarget: 1 });
assert.equal(stepped, steppedBeforeEdit, "Edit must not advance time-evolving physics");

// Authoring edits are in-memory editor state and must survive lifecycle exit.
state.r2.dirty = true;
state.motionQA.p3Pose = { x: 0, y: 1 };
window.dispatchEvent(new CustomEvent("rigstudio:modechange", { detail: { mode: "preview" } }));
assert.equal(state.editSession.active, false);
assert.equal(state.editSession.physicsSuspended, false);
assert.equal(state.turnX, 0.35, "Preview head pose must be restored");
assert.equal(state.mouthOpen, 0.25, "Preview expression state must be restored");
assert.deepEqual(state.parameters, { ParamAngleX: 0.35, ParamBreath: 0.6 });
assert.deepEqual(state.parameterOverrides, { ParamBreath: 0.6 });
assert.equal(control("autoIdle").checked, true);
assert.equal(control("bodySway").checked, true);
assert.equal(control("doBlink").checked, true);
assert.equal(control("doBreathe").checked, true);
assert.equal(control("r2EditMode").checked, false);
assert.equal(state.r2.dirty, true, "Edit authoring changes must not be discarded on exit");
assert.ok(reset >= 2, "enter and exit must reset physics history");
assert.ok(warmed >= 0.15, "exit must run deterministic physics warmup");

console.log("P3 stable Edit Pose lifecycle checks passed");
