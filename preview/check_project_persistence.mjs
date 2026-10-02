import assert from "node:assert/strict";

const controls = new Map();
let downloads = 0;
function control(id) {
  if (!controls.has(id)) controls.set(id, {
    id, value: "0", checked: false, textContent: "", innerHTML: "", dataset: {}, style: {},
    listeners: new Map(), addEventListener(type, fn) { this.listeners.set(type, fn); },
    append() {}, appendChild() {}, setAttribute() {}, remove() {},
    click() { if (this.download) downloads++; },
    classList: { add() {}, remove() {}, toggle() {} },
    querySelector() { return null; }, querySelectorAll() { return []; },
  });
  return controls.get(id);
}
globalThis.document = {
  getElementById: control, createElement: () => control(`new${controls.size}`), addEventListener() {},
};
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("Network forbidden in test"); };
const { state, persistR2Authoring } = await import("./runtime.mjs");
const spec = { enabled: true, keyforms: { "+1": { corner_lift_ratio: 0.2 }, "-1": {} }, mouth_bbox: [40, 70, 80, 80] };
state.manifest = { motion: { mouth_form: spec }, deformers: [{ kind: "mouth_form", config: spec }], parameters: [] };
state.autoManifest = structuredClone(state.manifest);
state.authoring = { version: 1, deformers: {}, physics: {} };
function edit(value) {
  const input = control("r6MouthCorner");
  input.value = String(value);
  input.listeners.get("input")({ target: input });
}
edit(0.3);
assert.equal(state.r6Mouth.dirty, true);
assert.equal(control("projectDirty").dataset.state, "dirty", "mouth edits must mark the project dirty");
assert.equal(await persistR2Authoring(), false);
assert.equal(downloads, 1);
assert.equal(state.r6Mouth.dirty, true);
assert.match(control("projectDirty").textContent, /ダウンロード|다운로드/);

let writes = [];
let failAt = 2;
let duringWrite = null;
const directory = {
  async getDirectoryHandle() { return directory; },
  async getFileHandle(name) {
    return { async createWritable() { return {
      async write(text) {
        writes.push({ name, text });
        if (writes.length === failAt) throw new Error("simulated disk failure");
        if (duringWrite) { const editNow = duringWrite; duringWrite = null; editNow(); }
      }, async close() {},
    }; } };
  },
};
state.projectDirectoryHandle = directory;
assert.equal(await persistR2Authoring(), false);
assert.equal(downloads, 1, "partial folder write must never silently fall back to download");
assert.equal(state.persistenceDirty, true);
assert.equal(state.r6Mouth.dirty, true);
assert.match(control("projectDirty").textContent, /저장 실패/);

writes = []; failAt = -1;
assert.equal(await persistR2Authoring(), true);
assert.equal(writes.length, 5);
assert.equal(state.persistenceDirty, false);
assert.equal(state.r6Mouth.dirty, false);
assert.equal(control("projectDirty").dataset.state, "clean");
edit(0.4);
writes = []; duringWrite = () => edit(0.5);
assert.equal(await persistR2Authoring(), false, "edits made during save must remain dirty");
assert.equal(state.r6Mouth.dirty, true);
assert.equal(control("projectDirty").dataset.state, "dirty");
assert.equal(await persistR2Authoring(), true);

writes = [];
duringWrite = () => {
  state.r3.dirty = true;
  state.qa.r3.physics = { damping_ratio: 0.7 };
};
assert.equal(await persistR2Authoring(), false, "calibration edits made during save must remain dirty too");
assert.equal(state.r3.dirty, true);
control("saveProject").listeners.get("click")();
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(state.authoring.physics.upper_torso.damping_ratio, 0.7);
assert.equal(state.persistenceDirty, false);

state.qa.r3.physics = { damping_ratio: 0.1 };
state.r3.dirty = false;
control("saveProject").listeners.get("click")();
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(state.authoring.physics?.upper_torso?.damping_ratio, 0.7,
  "QA-only probes must not become authored overrides through Project Save");
console.log("project persistence checks passed");
