import assert from "node:assert/strict";
import { buildParameterModel, fallbackLabel } from "./parameter-panel.mjs";

const manifest = {
  parameters: [
    { id: "ParamAngleX", min: -1, max: 1, default: 0 },
    { id: "ParamMouthOpenY", min: 0, max: 1, default: 0.25 },
    { id: "ParamEyeLOpen", min: 0, max: 1, default: 1 },
    { id: "ParamMouthForm", min: -1, max: 1, default: 0 },
    { id: "ParamCustomSmile", min: -2, max: 2, default: 0 },
    { id: "ParamBad", min: 1, max: 1, default: 1 },
  ],
  capabilities: {
    head_turn: "ready",
    mouth_open: "degraded",
    blink_l: "disabled",
  },
  deformers: [{ parameters: ["ParamAngleX", "ParamMouthOpenY", "ParamEyeLOpen", "ParamCustomSmile"] }],
};

const model = buildParameterModel(manifest);
assert.deepEqual(model.map((item) => item.id), ["ParamAngleX", "ParamMouthOpenY", "ParamCustomSmile"]);
assert.deepEqual(model[0].min, -1);
assert.deepEqual(model[0].max, 1);
assert.deepEqual(model[1].default, 0.25);
assert.deepEqual(model[1].capabilityState, "degraded");
assert.deepEqual(model[2].label, "Custom Smile");
assert.deepEqual(fallbackLabel("ParamEyeBallX"), "Eye Ball X");

console.log("manifest parameter panel checks passed (order, parity, filtering, fallback label)");
