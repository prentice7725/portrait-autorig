// Deterministic compiled-topwear fixture used by physical-response QA.
// It is deliberately a small multi-vertex mesh with authored lobe weights,
// lower-bias values, and a centre lock -- never a one-vertex/unit-weight
// synthetic shortcut.  The probe helpers in runtime.mjs select from this
// exact mesh just as they do from a production compiled part.

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
      lowerBias: new Float32Array(lowerBias), strength: 1 },
  };
}

export function makeChestMotion(physics, overrides = {}) {
  return {
    now: 0, turnX: 0, turnY: 0, tiltRad: 0, shell: 0, yaw: 0, pitch: 0,
    gazeX: 0, gazeY: 0, blink: { l: 0, r: 0 }, squash: { l: 0, r: 0 },
    mouthOpen: 0, breath: 0, breathAmp: 0, chestX: 0, lidRatio: 0.85,
    lidThickness: 0.18, bodySwayPosition: [0, 0],
    bodySway: { enabled: false },
    softMorph: { enabled: true, morph: 0, strength: 0,
      horizontalPx: 0, verticalPx: 0, physicsDistribution: {
        horizontal_gain: 0.45, vertical_gain: 1,
      } },
    physics: { torso: physics },
    overrides: { ghost: false, neck: "normal", collar: null, ...overrides },
  };
}
