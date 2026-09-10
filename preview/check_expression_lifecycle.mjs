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
  },
};
assert.deepEqual(expressionCatalog(manifest).map((entry) => entry.id), ["annoyed", "smile", "sad"]);
assert.equal(expressionCatalog(manifest)[1].label, "Warm Smile");

const state = { manifest, parameters: {}, gazeTargets: [0, 0] };
const controller = createRigController({ runtimeState: state });
controller.configure(manifest);
assert.equal(controller.activeExpression, null);
assert.equal(controller.setExpression("smile"), "smile");
assert.equal(controller.activeExpression, "smile");
assert.throws(() => controller.setExpression("missing"), /unknown ExpressionPreset/);
assert.equal(controller.releaseExpression(), null);
assert.equal(controller.activeExpression, null);

console.log("P6.2 expression catalog/lifecycle checks passed");

