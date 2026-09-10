// P4 semantic tree/context inspector contract checks.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const here = new URL("./", import.meta.url);
const html = await readFile(new URL("./index.html", here), "utf8");
const uiMode = await readFile(new URL("./ui-mode.mjs", here), "utf8");
const inspector = await readFile(new URL("./semantic-inspector.mjs", here), "utf8");

for (const context of ["chest", "eyes", "hair", "raw"])
  assert.match(html, new RegExp(`data-context="${context}"`));
assert.match(html, /semantic-inspector\.mjs/);
assert.match(uiMode, /"Chest Physics": "chest"/);
assert.match(uiMode, /"Chest Shape": "chest"/);
assert.match(uiMode, /"Raw Parts \(Advanced\)": "raw"/);
assert.match(inspector, /group\.hidden = group\.dataset\.context !== next/);
assert.match(inspector, /rigstudio:contextchange/);
assert.match(inspector, /read-only advanced view/);

// The P4 selector must not replace the existing R2/R3 controls or save ids.
for (const id of ["r2Save", "r2Reset", "r2Download", "r3Save", "r3Reset"])
  assert.match(uiMode, new RegExp(`"${id}"`));

console.log("P4 semantic tree/context inspector checks passed");
