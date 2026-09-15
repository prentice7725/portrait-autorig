// R6-A/R6-D/R6-E layer-free mouth-form geometry, authoring, and QA checks.
import assert from "node:assert/strict";
const controls = {};
const control = (id) => (controls[id] ||= {
  id, checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {},
  classList: { add() {}, remove() {} },
});
globalThis.document = {
  getElementById: control,
  createElement: () => control("tmp" + Math.random()),
  addEventListener() {},
};
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch in harness"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { deform, mouthFormDelta, jawOpenDelta, buildMesh, state,
  applyMouthFormAuthoring, captureMouthFormAuthoring, clearMouthFormAuthoring } = Runtime;

let failures = 0;
function check(name, condition, detail = "") {
  if (condition) console.log(`  ok   ${name}`);
  else { console.log(`  FAIL ${name} ${detail}`); failures++; }
}
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

const spec = {
  version: 1, enabled: true, target_tags: ["mouth", "mouth_open", "mouth_closed", "face"],
  mouth_box: [40, 70, 80, 80],
  keyforms: {
    "-1": { corner_drop_ratio: 0.18, corner_inward_ratio: 0.06,
      center_drop_ratio: 0.025, face_drop_ratio: 0.08, face_inward_ratio: 0.08, face_gain: 0.22 },
    "+1": { corner_lift_ratio: 0.20, corner_outward_ratio: 0.06,
      center_lift_ratio: 0, face_lift_ratio: 0.10, face_outward_ratio: 0.08, face_gain: 0.22 },
  },
  face_corrective: { center: [60, 75], radius_x: 54, radius_y: 14, gain: 0.22 },
};
const operation = { id: "mouth_form", kind: "mouth_form", phase: "corrective",
  parameters: ["ParamMouthForm"], targets: { tags: ["mouth", "face"] }, config: spec };

state.manifest = { anchors: {}, parameters: [{ id: "ParamMouthForm", min: -1, max: 1, default: 0 }] };
state.parameters = {};
state.canvasW = 120;
state.canvasH = 140;
state.frameOperations = [operation];

const mouthPart = {
  spec: { tag: "mouth", name: "mouth", xyxy: [40, 70, 80, 80], group: "head", depth: 0.1,
    weight: { mode: "constant", value: 1 } },
  mesh: { rest: new Float32Array([40, 75, 60, 75, 80, 75]),
    live: new Float32Array(6), weight: new Float32Array([1, 1, 1]) },
};
const facePart = { spec: { tag: "face", name: "face", xyxy: [10, 10, 110, 130], group: "head", depth: 0.5,
  weight: { mode: "constant", value: 1 } } };

check("neutral mouth form is exact rest", near(mouthFormDelta(mouthPart, 40, 75,
  { parameters: { ParamMouthForm: 0 } }, operation)[0], 0)
  && near(mouthFormDelta(mouthPart, 40, 75,
  { parameters: { ParamMouthForm: 0 } }, operation)[1], 0));
check("mouth form clamps above +1", near(mouthFormDelta(mouthPart, 40, 75,
  { parameters: { ParamMouthForm: 4 } }, operation)[1],
  mouthFormDelta(mouthPart, 40, 75, { parameters: { ParamMouthForm: 1 } }, operation)[1]));
check("smile moves the left corner upward and outward",
  mouthFormDelta(mouthPart, 40, 75, { parameters: { ParamMouthForm: 1 } }, operation)[0] < 0
  && mouthFormDelta(mouthPart, 40, 75, { parameters: { ParamMouthForm: 1 } }, operation)[1] < 0);
check("smile moves the right corner upward and outward",
  mouthFormDelta(mouthPart, 80, 75, { parameters: { ParamMouthForm: 1 } }, operation)[0] > 0
  && mouthFormDelta(mouthPart, 80, 75, { parameters: { ParamMouthForm: 1 } }, operation)[1] < 0);
check("frown moves both corners downward",
  mouthFormDelta(mouthPart, 40, 75, { parameters: { ParamMouthForm: -1 } }, operation)[1] > 0
  && mouthFormDelta(mouthPart, 80, 75, { parameters: { ParamMouthForm: -1 } }, operation)[1] > 0);
check("symmetric source has symmetric corner displacement",
  near(mouthFormDelta(mouthPart, 40, 75, { parameters: { ParamMouthForm: 1 } }, operation)[0],
    -mouthFormDelta(mouthPart, 80, 75, { parameters: { ParamMouthForm: 1 } }, operation)[0]));
check("face corrective is zero outside its influence region",
  mouthFormDelta(facePart, 60, 20, { parameters: { ParamMouthForm: 1 } }, operation).every((v) => near(v, 0)));

state.frameOperations = [operation];
state.parameters = {};
mouthPart.mesh.live.fill(0);
deform(mouthPart, 0, { parameters: { ParamMouthForm: 0 }, blink: { l: 0, r: 0 }, overrides: {} });
check("runtime neutral deformation keeps every vertex exact rest",
  mouthPart.mesh.live.every((v, i) => near(v, mouthPart.mesh.rest[i])));
deform(mouthPart, 0, { parameters: { ParamMouthForm: 1 }, blink: { l: 0, r: 0 }, overrides: {} });
check("runtime smile changes the mouth mesh without a new layer",
  mouthPart.mesh.live.some((v, i) => !near(v, mouthPart.mesh.rest[i])));

console.log("\nR6-D mouth authoring ownership");
const generatedManifest = {
  motion: { mouth_form: spec },
  deformers: [{ kind: "mouth_form", config: spec }],
};
const authored = { version: 1, deformers: { mouth_form: {
  keyform_overrides: { "+1": { corner_lift_ratio: 0.44 } },
} } };
const resolved = applyMouthFormAuthoring(generatedManifest, authored);
check("mouth authoring changes the resolved smile keyform",
  resolved.motion.mouth_form.keyforms["+1"].corner_lift_ratio === 0.44);
check("mouth authoring keeps the generated manifest immutable",
  generatedManifest.motion.mouth_form.keyforms["+1"].corner_lift_ratio === 0.20);
const captured = captureMouthFormAuthoring(resolved, authored);
check("mouth authoring capture persists both endpoint keyforms",
  captured.deformers.mouth_form.keyform_overrides["-1"]
  && captured.deformers.mouth_form.keyform_overrides["+1"].corner_lift_ratio === 0.44);
const cleared = clearMouthFormAuthoring(captured);
check("mouth reset removes only the mouth override",
  !cleared.deformers.mouth_form);

console.log("\nR6-E mouth QA presets");
const qaPart = {
  tag: "mouth", xyxy: [40, 70, 80, 80], mesh: { cell: 10 },
  weight: { mode: "constant", value: 1 },
};
const qaMeshPart = { spec: { ...qaPart }, mesh: buildMesh(qaPart) };
const qaPresets = [
  ["Smile +1", 1], ["Smile +0.5", 0.5], ["Neutral", 0],
  ["Frown -0.5", -0.5], ["Frown -1", -1],
];
const signedMotion = (value) => ({ parameters: { ParamMouthForm: value }, blink: { l: 0, r: 0 }, overrides: {} });
let maxStretch = 0;
let inverted = 0;
for (const [label, value] of qaPresets) {
  state.frameOperations = [operation];
  deform(qaMeshPart, 0, signedMotion(value));
  const indices = [...qaMeshPart.mesh.index];
  for (let i = 0; i < indices.length; i += 3) {
    const area = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    const point = (index, live) => [live[index * 2], live[index * 2 + 1]];
    const restArea = area(point(indices[i], qaMeshPart.mesh.rest), point(indices[i + 1], qaMeshPart.mesh.rest), point(indices[i + 2], qaMeshPart.mesh.rest));
    const liveArea = area(point(indices[i], qaMeshPart.mesh.live), point(indices[i + 1], qaMeshPart.mesh.live), point(indices[i + 2], qaMeshPart.mesh.live));
    if (restArea * liveArea <= 0) inverted++;
  }
  for (let i = 0; i < qaMeshPart.mesh.rest.length; i += 2) {
    const next = i + 2 < qaMeshPart.mesh.rest.length ? i + 2 : i;
    if (next === i) continue;
    const restLength = Math.hypot(qaMeshPart.mesh.rest[next] - qaMeshPart.mesh.rest[i], qaMeshPart.mesh.rest[next + 1] - qaMeshPart.mesh.rest[i + 1]);
    const liveLength = Math.hypot(qaMeshPart.mesh.live[next] - qaMeshPart.mesh.live[i], qaMeshPart.mesh.live[next + 1] - qaMeshPart.mesh.live[i + 1]);
    if (restLength > 1e-6) maxStretch = Math.max(maxStretch, liveLength / restLength);
  }
  check(`${label} remains finite`, qaMeshPart.mesh.live.every(Number.isFinite));
}
check("QA presets have no triangle inversion", inverted === 0, `inverted=${inverted}`);
check("QA presets avoid excessive texture stretch", Number.isFinite(maxStretch) && maxStretch < 2.5,
  `max stretch=${maxStretch.toFixed(3)}`);
const faceDeltaA = mouthFormDelta(facePart, 60, 75, { parameters: { ParamMouthForm: 1 } }, operation);
const faceDeltaB = mouthFormDelta(facePart, 61, 75, { parameters: { ParamMouthForm: 1 } }, operation);
check("face corrective stays continuous at the mouth seam",
  Math.hypot(faceDeltaA[0] - faceDeltaB[0], faceDeltaA[1] - faceDeltaB[1]) < 1);
const jawOperation = { config: { version: 1, enabled: true, target_tag: "face",
  max_drop_ratio: 0.04, influence: { start_y: 70, end_y: 130, center_x: 60, radius_x: 40, edge_gain: 0.45 } } };
const formAtOpen = mouthFormDelta(facePart, 60, 75, { parameters: { ParamMouthForm: 1 } }, operation);
const jawAtOpen = jawOpenDelta(facePart, 60, 100, { mouthOpen: 1 }, jawOperation);
check("mouth-open composition keeps form and jaw axes independent",
  formAtOpen[1] < 0 && jawAtOpen[1] > 0 && formAtOpen[1] + jawAtOpen[1] !== formAtOpen[1]);

if (failures) process.exit(1);
