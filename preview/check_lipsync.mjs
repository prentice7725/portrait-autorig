// P6.3 pure audio sampling and external lip-sync contract checks.
import assert from "node:assert/strict";
import { rmsFromTimeDomain, AUDIO_TEST_VERSION } from "./audio-test-ui.mjs";
import { createRigController, LIPSYNC_VERSION } from "./rig-controller.mjs";

assert.equal(AUDIO_TEST_VERSION, "P6.3");
assert.equal(LIPSYNC_VERSION, "P6.3");
assert.equal(rmsFromTimeDomain(new Uint8Array([128, 128, 128])), 0);
assert(Math.abs(rmsFromTimeDomain(new Uint8Array([0, 255])) - 1) < 0.01);
assert.equal(rmsFromTimeDomain([]), 0);

const state = {
  manifest: { parameters: [], motion: {} },
  parameters: {}, parameterOverrides: {}, mouthOpen: 0,
  blink: { l: 0, r: 0 }, blinkTimer: 0, blinkPhase: null,
  gazeTargets: [0, 0], turnX: 0, turnY: 0, tiltDeg: 0,
};
const controller = createRigController({ runtimeState: state });
controller.configure(state.manifest);
for (const [id, value] of [["doTalk", false], ["doBreathe", false], ["doBlink", false], ["useArt", false]])
  controller.setControl(id, value);
controller.setLipSyncEnabled(true);
controller.setLipSyncRms(0.4);
assert.equal(controller.tick(100, { mouthAvailable: true }).mouthOpen, 0.4);
controller.setLipSyncEnabled(false);
assert.equal(controller.tick(200, { mouthAvailable: true }).mouthOpen, 0);

console.log("P6.3 RMS lip-sync checks passed");
