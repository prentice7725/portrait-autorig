import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  RIG_STUDIO_A11Y_VERSION, UI_SCALE_OPTIONS, MOTION_PREFERENCES, keyboardNudge,
  normalizeUiScale, isTextEntryTarget, initAccessibility,
} from "./accessibility.mjs";

assert.equal(RIG_STUDIO_A11Y_VERSION, "A11Y-1.1");
assert.deepEqual(UI_SCALE_OPTIONS, [100, 125, 150]);
assert.deepEqual(MOTION_PREFERENCES, ["system", "reduce", "full"]);
assert.equal(normalizeUiScale(undefined), 100);
assert.equal(normalizeUiScale(80), 100);
assert.equal(normalizeUiScale(130), 125);
assert.equal(normalizeUiScale(200), 150);
assert.deepEqual(keyboardNudge("ArrowLeft", 1), [-1, 0]);
assert.deepEqual(keyboardNudge("ArrowUp", 2, 10), [0, -20]);
assert.deepEqual(keyboardNudge("ArrowDown", 2, 0.1), [0, 0.2]);
assert.equal(keyboardNudge("Escape", 1), null);
assert.equal(keyboardNudge("ArrowLeft", Number.NaN), null);

const html = await readFile(new URL("./index.html", import.meta.url), "utf8");
const modeModule = await readFile(new URL("./ui-mode.mjs", import.meta.url), "utf8");
assert.match(html, /id="motionPreference"[\s\S]*value="system"[\s\S]*value="reduce"[\s\S]*value="full"/);
assert.match(html, /id="uiScale"[\s\S]*value="100"[\s\S]*value="125"[\s\S]*value="150"/);
assert.match(html, /id="regionOverlay"[^>]*tabindex="0"/);
assert.match(html, /id="r2PointX"[^>]*type="number"/);
assert.match(html, /id="r2PointY"[^>]*type="number"/);
assert.match(html, /id="r2NudgeStep"[^>]*type="number"/);
assert.match(html, /Ctrl\/Cmd \+ S/);
assert.match(html, /Shift는 10배/);
assert.match(html, /id="r2OverlayLegend"/);
assert.match(modeModule, /\{ "1": "preview", "2": "edit", "3": "qa" \}/);

assert.equal(isTextEntryTarget({ matches: (selector) => selector.includes("input") }), true);
assert.equal(isTextEntryTarget({ matches: () => false }), false);
assert.equal(isTextEntryTarget({ closest: (selector) => selector.includes("contenteditable") ? {} : null }), true);

const events = [];
const storage = new Map();
const controls = new Map([
  ["motionPreference", { value: "system", addEventListener(type, handler) { this[type] = handler; } }],
  ["uiScale", { value: "100", addEventListener(type, handler) { this[type] = handler; } }],
  ["motionStatus", { dataset: {}, textContent: "" }],
  ["uiScaleStatus", { textContent: "" }],
]);
const root = { dataset: {}, style: { setProperty() {} } };
const fakeDocument = {
  documentElement: root,
  body: { setAttribute(name, value) { this[name] = value; } },
  getElementById(id) { return controls.get(id) || null; },
};
let mediaListener = null;
const media = { matches: true, addEventListener(type, handler) { mediaListener = handler; } };
const fakeWindow = {
  CustomEvent: class CustomEvent { constructor(type, init) { this.type = type; this.detail = init.detail; } },
  dispatchEvent(event) { events.push(event); },
  localStorage: {
    getItem(key) { return storage.get(key) || null; },
    setItem(key, value) { storage.set(key, value); },
  },
  matchMedia() { return media; },
};
const accessibility = initAccessibility(fakeDocument, fakeWindow);
assert.equal(accessibility.motionPreference, "system");
assert.equal(accessibility.reducedMotion, true, "system preference seeds effective motion state");
assert.equal(root.dataset.reduceMotion, "true");
assert.equal(controls.get("motionPreference").value, "system");

controls.get("motionPreference").value = "full";
controls.get("motionPreference").change({ currentTarget: controls.get("motionPreference") });
assert.equal(accessibility.reducedMotion, false, "explicit full preference overrides the OS");
assert.equal(storage.get("portrait-autorig.motion-preference"), "full");
assert.equal(events.at(-1).type, "rigstudio:reducedmotionchange");

controls.get("motionPreference").value = "system";
controls.get("motionPreference").change({ currentTarget: controls.get("motionPreference") });
assert.equal(accessibility.reducedMotion, true, "system preference restores OS behavior");
// The captured listener follows OS changes only while the preference is system.
media.matches = false; mediaListener({ matches: false });
assert.equal(accessibility.reducedMotion, false);
controls.get("motionPreference").value = "reduce";
controls.get("motionPreference").change({ currentTarget: controls.get("motionPreference") });
media.matches = true; mediaListener({ matches: true });
assert.equal(accessibility.reducedMotion, true, "explicit reduced preference ignores later OS changes");

assert.equal(accessibility.setUiScale(150), 150);
assert.equal(root.dataset.uiScale, "150");
assert.equal(fakeDocument.body["data-ui-scale"], "150");
assert.equal(events.at(-1).type, "rigstudio:uiscalechange");

console.log("Rig Studio accessibility checks passed (system motion preference, UI scale, keyboard editing cues)");
