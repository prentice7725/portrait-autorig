// Deterministic compiled-topwear fixture used by physical-response QA.
// It is deliberately a small multi-vertex mesh with authored lobe weights,
// lower-bias values, and a centre lock -- never a one-vertex/unit-weight
// synthetic shortcut.  The probe helpers in runtime.mjs select from this
// exact mesh just as they do from a production compiled part.

// Lobe geometry the `left`/`right` weight fields below are actually derived
// from -- exposed as `softMorph.geometry` (P2.5 directive #8, #61) so a v3
// distribution has real lobe-local (u, v) to build a basis from, and so the
// grid's mirror symmetry about x=140 (xs is symmetric around it) makes it
// usable for L/R mirror-sign checks too.
export const CHEST_LOBE_GEOMETRY = {
  left: { cx: 110, cy: 145, rx: 42, ry: 48 },
  right: { cx: 170, cy: 145, rx: 42, ry: 48 },
};

export function makeCompiledTopwearFixture() {
  const xs = [80, 100, 120, 140, 160, 180, 200];
  const ys = [100, 120, 140, 160, 180];
  const rest = [];
  const left = [], right = [], lowerBias = [];
  for (const y of ys) for (const x of xs) {
    rest.push(x, y);
    const isLock = y === 100 || x === 140;
    const leftRadius = Math.hypot((x - 110) / 42, (y - 145) / 48);
    const rightRadius = Math.hypot((x - 170) / 42, (y - 145) / 48);
    let wl = x < 140 ? Math.max(0, 1 - 0.28 * leftRadius ** 2) : 0;
    let wr = x > 140 ? Math.max(0, 1 - 0.28 * rightRadius ** 2) : 0;
    if (isLock) { wl = 0; wr = 0; }
    left.push(wl); right.push(wr);
    lowerBias.push(isLock ? 0 : (y >= 120 ? 0.96 : 0.6));
  }
  const count = rest.length / 2;
  return {
    name: "topwear",
    visible: true,
    spec: { name: "topwear", tag: "topwear", group: "body", depth: 0.4 },
    mesh: { rest: new Float32Array(rest), live: new Float32Array(rest),
      weight: new Float32Array(count).fill(1) },
    weight: { mode: "constant", value: 1 },
    eyeSide: null, isEye: false, isLid: false, shell: null,
    softMorph: { left: new Float32Array(left), right: new Float32Array(right),
      lowerBias: new Float32Array(lowerBias), strength: 1,
      geometry: { left: { ...CHEST_LOBE_GEOMETRY.left }, right: { ...CHEST_LOBE_GEOMETRY.right } } },
  };
}

// The directive #20 v3 contract's own defaults, verbatim -- used as the
// default distribution for every v3 QA fixture/test unless a caller
// overrides specific gains.
export const BASIS_V3_DISTRIBUTION = {
  version: 3, carrier_gain: 1.0, volume_gain: 0.55, sag_gain: 0.85, follow_gain_s: 0.035,
  shear_gain_x_s: 0.018, shear_gain_y_s: 0.012, compression_gain: 0.20,
  upper_anchor_start: -0.75, upper_anchor_end: -0.15,
  lower_start: 0.0, lower_power: 1.7, tangent_ratio: 0.15,
  max_follow_px: 3.0, max_shear_px: 2.0,
};

/** Attach precomputed v3 basis arrays (directive #8) to an already-built
 *  fixture's `softMorph`, from its `geometry` and `mesh.rest` -- mirrors what
 *  `buildSoftMorphWeights` does for a real compiled part, since
 *  `makeCompiledTopwearFixture`'s weights are hand-authored rather than run
 *  through it. `Runtime` is the imported `runtime.mjs` module (its basis
 *  helpers are exported precisely so QA fixtures can do this without
 *  duplicating the per-vertex math). */
export function attachChestBasis(Runtime, part, rawDistribution = BASIS_V3_DISTRIBUTION) {
  const distribution = Runtime.physicalDistribution({ physicsDistribution: rawDistribution });
  const rest = part.mesh.rest;
  const n = rest.length / 2;
  const basis = { left: Runtime.makeChestBasisArrays(n), right: Runtime.makeChestBasisArrays(n) };
  for (let i = 0, v = 0; i < n; i++, v += 2) {
    Runtime.writeChestBasisAt(basis.left, i, rest[v], rest[v + 1], part.softMorph.geometry.left, distribution);
    Runtime.writeChestBasisAt(basis.right, i, rest[v], rest[v + 1], part.softMorph.geometry.right, distribution);
  }
  part.softMorph.basis = basis;
  return part;
}

export function makeChestMotion(physics, overrides = {}) {
  const { physicsDistribution, ...rest } = overrides;
  return {
    now: 0, turnX: 0, turnY: 0, tiltRad: 0, shell: 0, yaw: 0, pitch: 0,
    gazeX: 0, gazeY: 0, blink: { l: 0, r: 0 }, squash: { l: 0, r: 0 },
    mouthOpen: 0, breath: 0, breathAmp: 0, chestX: 0, lidRatio: 0.85,
    lidThickness: 0.18, bodySwayPosition: [0, 0],
    bodySway: { enabled: false },
    bodyVelocityX: 0, bodyVelocityY: 0,
    softMorph: { enabled: true, morph: 0, strength: 0,
      horizontalPx: 0, verticalPx: 0, physicsDistribution: physicsDistribution || {
        version: 2, horizontal_gain: 0.45, vertical_gain: 1.0, vertical_floor: 0.35,
      } },
    physics: { torso: physics },
    overrides: { ghost: false, neck: "normal", collar: null, ...rest },
  };
}
