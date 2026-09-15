// P6.2 expression catalog and transient lifecycle checks.
import assert from "node:assert/strict";
import { expressionCatalog, EXPRESSION_UI_VERSION } from "./expression-ui.mjs";
import { createRigController, EXPRESSION_LIFECYCLE_VERSION } from "./rig-controller.mjs";

assert.equal(EXPRESSION_UI_VERSION, "P6.2");
assert.equal(EXPRESSION_LIFECYCLE_VERSION, "P6.2");
assert.deepEqual(expressionCatalog({}), []);

const manifest = {
  expression_presets: {
    sad: { variants: { eyes: "sad" } },
    smile: { metadata: { label: "Warm Smile", order: 1 }, variants: { mouth: "smile" } },
    annoyed: { metadata: { label: "Annoyed", order: 1 }, variants: { eyes: "annoyed" } },
    happy: { parameters: { ParamMouthForm: 0.78 } },
  },
};
assert.deepEqual(expressionCatalog(manifest).map((entry) => entry.id), ["annoyed", "smile", "happy", "sad"]);
assert.equal(expressionCatalog(manifest)[1].label, "Warm Smile");

const state = { manifest, parameters: {}, gazeTargets: [0, 0] };
const controller = createRigController({ runtimeState: state });
controller.configure(manifest);
assert.equal(controller.activeExpression, null);
assert.equal(controller.setExpression("smile"), "smile");
assert.equal(controller.activeExpression, "smile");
assert.throws(() => controller.setExpression("missing"), /unknown ExpressionPreset/);
assert.equal(controller.setExpression("happy"), "happy");
assert.equal(controller.releaseExpression(), null);
assert.equal(controller.activeExpression, null);

const ownedState = {
  manifest: { parameters: [{ id: "ParamMouthForm", min: -1, max: 1, default: 0 }] },
  parameters: { ParamMouthForm: 0.12 },
  parameterOwners: {},
};
const ownedController = createRigController({ runtimeState: ownedState });
ownedController.configure(ownedState.manifest);
ownedController.setParameter("ParamMouthForm", 0.76, "expression");
assert.equal(ownedState.parameterOwners.ParamMouthForm, "expression");
assert.equal(ownedController.releaseExpression(), null);
assert.equal(ownedState.parameters.ParamMouthForm, 0.12,
  "release restores the value that expression temporarily owned");
assert.equal(ownedState.parameterOwners.ParamMouthForm, undefined);

ownedController.setParameter("ParamMouthForm", 0.31, "manual");
ownedController.setParameter("ParamMouthForm", -0.8, "expression");
assert.equal(ownedState.parameters.ParamMouthForm, 0.31,
  "manual parameter ownership has priority over expression");
assert.equal(ownedState.parameterOwners.ParamMouthForm, "manual");
assert.equal(ownedController.releaseExpression(), null);
assert.equal(ownedState.parameters.ParamMouthForm, 0.31,
  "release never overwrites a manual value");

console.log("P6.2 expression catalog/lifecycle checks passed");
