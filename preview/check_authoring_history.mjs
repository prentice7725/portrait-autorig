import assert from "node:assert/strict";
import {
  createAuthoringHistory, pushAuthoringHistory,
  undoAuthoringHistory, redoAuthoringHistory,
} from "./authoring-history.mjs";

const history = createAuthoringHistory(2);
const a = { deformers: { upper_torso: { range_override: { y: 6 } } } };
const b = { deformers: { upper_torso: { range_override: { y: 8 } } } };
const c = { deformers: { upper_torso: { range_override: { y: 10 } } } };
assert.equal(pushAuthoringHistory(history, a, a), false);
assert.equal(pushAuthoringHistory(history, a, b), true);
assert.equal(pushAuthoringHistory(history, b, c), true);
assert.deepEqual(undoAuthoringHistory(history, c), b);
assert.deepEqual(undoAuthoringHistory(history, b), a);
assert.equal(undoAuthoringHistory(history, a), null);
assert.deepEqual(redoAuthoringHistory(history, a), b);
assert.deepEqual(redoAuthoringHistory(history, b), c);
assert.equal(redoAuthoringHistory(history, c), null);
console.log("authoring history checks passed");
