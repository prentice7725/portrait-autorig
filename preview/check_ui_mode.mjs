import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const here = new URL("./", import.meta.url);
const html = await readFile(new URL("./index.html", here), "utf8");
const modeModule = await readFile(new URL("./ui-mode.mjs", here), "utf8");

assert.match(html, /<header id="topbar">[\s\S]*data-mode="preview"[\s\S]*data-mode="edit"[\s\S]*data-mode="qa"/);
assert.match(html, /<aside id="semanticTree"/);
assert.match(html, /<script type="module" src="\.\/ui-mode\.mjs"><\/script>\s*<script type="module" src="\.\/semantic-inspector\.mjs"><\/script>\s*<script type="module" src="\.\/parameter-panel\.mjs"><\/script>\s*<script type="module" src="\.\/runtime\.mjs"><\/script>/);
assert.match(modeModule, /section\.id = `\$\{mode\}Panel`/);
assert.match(modeModule, /"autoIdle"/);
assert.match(modeModule, /"r2Save"/);
assert.match(modeModule, /"profiler"/);
assert.match(modeModule, /"shell"/);

const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
const counts = new Map();
for (const id of ids) counts.set(id, (counts.get(id) || 0) + 1);
const duplicates = [...counts].filter(([, count]) => count !== 1);
assert.deepEqual(duplicates, [], `static DOM ids must remain unique: ${JSON.stringify(duplicates)}`);

console.log(`UI mode shell checks passed (${ids.length} unique legacy DOM ids)`);
