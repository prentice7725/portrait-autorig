// P2.5 directive #63: an A002-shaped narrow topwear crop (directive #46's
// A002 permanent regression geometry) must keep max L/R lobe weight >= 0.95
// and its center/neckline locks <= 0.05px under combined v3 basis stress --
// no basis term may bypass the lock-aware weight field it is multiplied by.
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { deform, state, buildSoftMorphWeights, selectChestProbes, measureProbeDisplacement } = Runtime;
state.canvasW = 768; state.canvasH = 768;

// Same A002-shaped crop/lobe geometry as check_lock_zone_basis.mjs.
const partSpec = { xyxy: [162, 345, 604, 768], tag: "topwear", group: "body", depth: 0.4 };
const spec = {
  coordinate_space: "canvas_normalized",
  center_lock: 0.1, neckline_lock: 0.16,
  left: { center: [0.336, 0.732], radius: [0.094, 0.122] },
  right: { center: [0.657, 0.732], radius: [0.092, 0.114] },
  physics_distribution: {
    version: 3, volume_gain: 0.60, sag_gain: 0.95, follow_gain_s: 0.035,
    shear_gain_x_s: 0.018, shear_gain_y_s: 0.012, compression_gain: 0.20,
    upper_anchor_start: -0.75, upper_anchor_end: -0.15,
    lower_start: 0.0, lower_power: 1.7, tangent_ratio: 0.15,
    max_follow_px: 3.0, max_shear_px: 2.0,
  },
};

const cols = 63, rows = 63;
const rest = [];
for (let r = 0; r <= rows; r++) {
  for (let c = 0; c <= cols; c++) {
    rest.push(
      partSpec.xyxy[0] + (partSpec.xyxy[2] - partSpec.xyxy[0]) * c / cols,
      partSpec.xyxy[1] + (partSpec.xyxy[3] - partSpec.xyxy[1]) * r / rows,
    );
  }
}
const restArr = new Float32Array(rest);
const mesh = { rest: restArr, live: new Float32Array(restArr), weight: new Float32Array(restArr.length / 2).fill(1) };
const weights = buildSoftMorphWeights(partSpec, mesh, spec, []);
if (!weights.basis) throw new Error("expected a v3 basis field for this fixture");

let maxWeight = 0;
for (let i = 0; i < weights.left.length; i++)
  maxWeight = Math.max(maxWeight, weights.left[i] || 0, weights.right[i] || 0);
console.log("max lobe weight:", maxWeight.toFixed(3));
if (maxWeight < 0.95) throw new Error(`max L/R lobe weight ${maxWeight} < 0.95`);

const part = {
  name: "topwear", spec: partSpec, mesh,
  weight: { mode: "constant", value: 1 },
  eyeSide: null, isEye: false, isLid: false, shell: null,
  softMorph: weights,
};

const operations = [{ id: "chest", kind: "local_soft_field", phase: "secondary" }];
state.manifest = { anchors: {} };
state.frameOperations = operations;
state.motionQA = { asymmetry: 1, settleMultiplier: 1, side: "both", shapeGain: null, poseActive: false };

const motion = {
  turnX: 0, turnY: 0, tiltRad: 0, shell: 0, squash: { l: 0, r: 0 }, blink: { l: 0, r: 0 },
  overrides: { ghost: false, neck: "normal", collar: null },
  softMorph: { enabled: true, morph: 0, strength: 0, horizontalPx: 0, verticalPx: 0,
    physicsDistribution: spec.physics_distribution },
  bodySwayPosition: [0, 0], bodyVelocityX: 40, bodyVelocityY: -30,
  physics: { torso: { model: "inertial_relative_v2", value: -6,
    left: { value: -6, velocity: 24 }, right: { value: 5, velocity: -24 },
    settleTimeScaleS: 0.03 } },
};
deform(part, 0, motion);

const probes = selectChestProbes(part);
if (!probes?.lock) throw new Error("fixture did not produce a lock probe");
const lockDisp = measureProbeDisplacement(part, probes.lock);
console.log("lock probe displacement:", lockDisp.toFixed(4), "px");
if (lockDisp > 0.05) throw new Error(`lock probe moved ${lockDisp}px (> 0.05px)`);

// Neckline-specific probe: nearest vertex right at the neckline release line,
// well inside the center band (locked regardless of x).
const neckY = partSpec.xyxy[1] + (partSpec.xyxy[3] - partSpec.xyxy[1]) * spec.neckline_lock * 0.3;
let neckIdx = -1, neckBestDist = Infinity;
for (let i = 0; i < restArr.length / 2; i++) {
  const d = Math.abs(restArr[i * 2 + 1] - neckY);
  if (d < neckBestDist) { neckBestDist = d; neckIdx = i; }
}
const neckDisp = measureProbeDisplacement(part, neckIdx);
console.log("neckline probe displacement:", neckDisp.toFixed(4), "px");
if (neckDisp > 0.05) throw new Error(`neckline probe moved ${neckDisp}px (> 0.05px)`);

console.log("chest basis lock preservation checks passed");
