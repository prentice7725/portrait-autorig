// Regression for the canvas_normalized lock-zone basis bug: center_lock /
// neckline_lock / the center transition are authored as fractions of the
// topwear crop's own width/height (soft_morph.py's CENTER_LOCK_WIDTH /
// NECKLINE_LOCK_WIDTH), never of the canvas. A Composer Assembly region with
// `coordinate_space: "canvas_normalized"` still positions its lobes with the
// canvas-normalized basis, but a torso crop narrower than the canvas must not
// inflate the lock/transition zone -- wide enough to land on the lobe's own
// centre and crush its weight everywhere, which reads as "the chest doesn't
// move" no matter how strong the morph or physics signal is (A002).
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
Runtime.state.canvasW = 768;
Runtime.state.canvasH = 768;

// A torso crop far narrower than the canvas (like A002's 442px topwear on a
// 768px canvas), with lobes positioned in canvas-normalized coordinates close
// enough to the body midline that canvas-width-basis locks would land on top
// of them: left lobe centre at x=258 is 126px from canvas-centre (384), which
// used to fall inside the old canvas-basis transition band [76.8, 192].
const part = { xyxy: [162, 345, 604, 768], tag: "topwear" };
const spec = {
  coordinate_space: "canvas_normalized",
  center_lock: 0.1, neckline_lock: 0.16,
  left: { center: [0.336, 0.732], radius: [0.094, 0.122] },
  right: { center: [0.657, 0.732], radius: [0.092, 0.114] },
};
const n = 4000;
const rest = new Float32Array(n * 2);
// Dense sample grid across the crop so some vertex lands near each lobe centre.
const cols = 63, rows = 63;
for (let r = 0; r <= rows; r++) {
  for (let c = 0; c <= cols; c++) {
    const i = r * (cols + 1) + c;
    rest[i * 2] = part.xyxy[0] + (part.xyxy[2] - part.xyxy[0]) * c / cols;
    rest[i * 2 + 1] = part.xyxy[1] + (part.xyxy[3] - part.xyxy[1]) * r / rows;
  }
}
const mesh = { rest };
const weights = Runtime.buildSoftMorphWeights(part, mesh, spec, []);
let maxWeight = 0;
for (let i = 0; i < weights.left.length; i++)
  maxWeight = Math.max(maxWeight, weights.left[i] || 0, weights.right[i] || 0);
console.log("max lobe weight reachable:", maxWeight.toFixed(3));
if (maxWeight < 0.85)
  throw new Error(`canvas-normalized lock zone crushed lobe weight to ${maxWeight.toFixed(3)} `
    + "(expected close to 1.0 at the lobe centre)");
console.log("lock-zone basis check passed");
