// P5 DOM-free controller contract checks.
import assert from "node:assert/strict";
import { createRigController, RIG_CONTROLLER_VERSION, CURSOR_FOLLOW_VERSION, LIPSYNC_VERSION } from "./rig-controller.mjs";

assert.equal(RIG_CONTROLLER_VERSION, "P5.0");
assert.equal(CURSOR_FOLLOW_VERSION, "P6.1");
assert.equal(LIPSYNC_VERSION, "P6.3");
const runtimeState = {
  manifest: null,
  parameters: {},
  parameterOverrides: {},
  gazeTargets: [0, 0],
  turnX: 0, turnY: 0, tiltDeg: 0, shell: 0,
  mouthOpen: 0, talkUntil: 0, talkTarget: 0,
  blink: { l: 0, r: 0 }, blinkTimer: 0, blinkPhase: null,
  bodySwayEnabled: false,
  motionQA: { inertia: true, asymmetry: 1, shapeGain: null, side: "both" },
  r2: { editMode: false },
  displayPreset: "full",
};
const controller = createRigController({ runtimeState, random: () => 0.5 });
controller.configure({
  parameters: [
    { id: "ParamAngleX", min: -1, max: 1, default: 0 },
    { id: "ParamAngleY", min: -1, max: 1, default: 0 },
    { id: "ParamEyeBallX", min: -1, max: 1, default: 0 },
    { id: "ParamEyeBallY", min: -1, max: 1, default: 0 },
    { id: "ParamBreath", min: -1, max: 1, default: 0 },
  ],
  motion: {
    head_turn: { max_x: 1, max_y: 1 }, head_tilt: { max_deg: 10 },
    blink: { interval_s: [2, 4], close_s: 0.1, hold_s: 0.1, open_s: 0.1 },
    breathing: { period_s: 4 },
  },
});
for (const [id, value] of [["autoIdle", true], ["bodySway", true], ["chestInertia", true],
  ["doBlink", true], ["doBreathe", true], ["doTalk", false], ["useArt", false],
  ["gazeX", 0.2], ["gazeY", -0.1], ["mouthOpen", 0.25], ["r2EditMode", false]])
  controller.setControl(id, value);

assert.equal(controller.setParameter("ParamAngleX", 4), 1);
assert.equal(runtimeState.turnX, 1);
assert.equal(controller.parameterValue("ParamAngleX"), 1);
const previewFrame = controller.tick(1000, { t: 1, dt: 1 / 60 });
const previewTurnX = runtimeState.turnX;
assert.equal(previewFrame.autoIdle, true);
assert.equal(previewFrame.bodySwayEnabled, true);
assert.equal(previewFrame.gazeX, 0.2);
assert.equal(previewFrame.mouthOpen, 0.25);

// P6.1 cursor mapping: center is neutral, edges clamp, and the optional head
// share is deterministic. The controller is DOM-free so this is also the
// runtime contract used by the browser adapter.
controller.setControl("followCursor", true);
controller.setCursorGazeEnabled(true);
controller.lookAt(0, 0);
let cursorFrame = controller.tick(1100, { t: 1.1, dt: 1 / 60 });
assert.equal(cursorFrame.gazeX, 0);
assert.equal(cursorFrame.gazeY, 0);
assert.equal(cursorFrame.turnX, 0);
assert.equal(cursorFrame.turnY, 0);
controller.lookAt(2, -2);
cursorFrame = controller.tick(1200, { t: 1.2, dt: 1 / 60 });
assert.equal(cursorFrame.gazeX, 1);
assert.equal(cursorFrame.gazeY, -1);
assert.equal(cursorFrame.turnX, 0.2);
assert.equal(cursorFrame.turnY, -0.15);
assert.equal(cursorFrame.cursorActive, true);

// Manual claims outrank cursor follow and keep their value through the grace
// window after release, preventing a visible snap while the user lets go.
controller.setControl("gazeX", 0.35);
controller.setControl("gazeY", -0.25);
controller.setControl("turnX", 0.4);
controller.setControl("turnY", -0.3);
controller.beginManual("gazeX");
controller.beginManual("turnX");
cursorFrame = controller.tick(1300, { t: 1.3, dt: 1 / 60 });
assert.equal(cursorFrame.gazeX, 0.35);
assert.equal(cursorFrame.gazeY, -0.25);
assert.equal(cursorFrame.turnX, 0.4);
assert.equal(cursorFrame.turnY, -0.3);
controller.endManual("gazeX", 1300);
controller.endManual("turnX", 1300);
cursorFrame = controller.tick(1600, { t: 1.6, dt: 1 / 60 });
assert.equal(cursorFrame.gazeX, 0.35);
assert.equal(cursorFrame.turnX, 0.4);
cursorFrame = controller.tick(1701, { t: 1.7, dt: 1 / 60 });
assert.equal(cursorFrame.gazeX, 1);
assert.equal(cursorFrame.turnX, 0.2);

controller.setControl("autoIdle", false);
controller.setCursorGazeEnabled(false);
controller.setControl("turnX", 0.4);
controller.setControl("turnY", -0.3);
cursorFrame = controller.tick(1800, { t: 1.8, dt: 1 / 60 });
assert.equal(cursorFrame.cursorActive, false);
assert.equal(cursorFrame.gazeX, 0.35);
assert.equal(cursorFrame.turnX, 0.4);

assert.deepEqual(controller.normalizePointer(50, 50, { left: 0, top: 0, width: 100, height: 100 }), { x: 0, y: 0 });
assert.deepEqual(controller.normalizePointer(0, 0, { left: 0, top: 0, width: 100, height: 100 }), { x: -1, y: -1 });
assert.deepEqual(controller.normalizePointer(100, 0, { left: 0, top: 0, width: 100, height: 100 }), { x: 1, y: -1 });
assert.deepEqual(controller.normalizePointer(-50, 200, { left: 0, top: 0, width: 100, height: 100 }), { x: -1, y: 1 });

// P6.3 external RMS owns the mouth only while enabled. Bad samples are safe,
// and disabling the source returns the mouth to clean rest.
assert.equal(controller.setLipSyncRms(0.8), 0);
assert.equal(controller.setLipSyncEnabled(true), true);
assert.equal(controller.setLipSyncRms(0.65), 0.65);
let lipFrame = controller.tick(1900, { t: 1.9, dt: 1 / 60, mouthAvailable: true });
assert.equal(lipFrame.lipSyncActive, true);
assert.equal(lipFrame.mouthOpen, 0.65);
assert.equal(controller.setLipSyncRms(Number.NaN), 0.65);
assert.equal(controller.setLipSyncRms(Number.POSITIVE_INFINITY), 1);
assert.equal(controller.setLipSyncEnabled(false), false);
assert.equal(runtimeState.mouthOpen, 0);
controller.setControl("mouthOpen", 0.25);
runtimeState.mouthOpen = 0.25;

const editTurnX = runtimeState.turnX;
controller.enterEdit(2000);
assert.equal(controller.editActive, true);
assert.equal(runtimeState.turnX, 0);
assert.equal(runtimeState.parameterOverrides.ParamBreath, undefined);
assert.equal(controller.tick(9000, { t: 9, dt: 1 }).editActive, true);
assert.equal(runtimeState.bodySwayEnabled, false);
assert.equal(controller.editActive, true);

runtimeState.mouthOpen = 0.7; // editor-side transient state must not leak out
controller.exitEdit();
assert.equal(controller.editActive, false);
assert.equal(runtimeState.turnX, editTurnX);
assert.equal(runtimeState.mouthOpen, 0.25);
assert.equal(runtimeState.parameters.ParamAngleX, 1);
controller.setControl("autoIdle", true);
assert.equal(controller.tick(10000, { t: 10, dt: 1 / 60 }).bodySwayEnabled, true);

console.log("P6.1 DOM-free cursor-follow controller checks passed");
