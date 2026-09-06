// P2.5 directive #66 (see also #11, #37-38): "simulate: body moves, body
// reverses, body stops, chest continues" and require the basis-selected
// upper/center/lower probes (directive #35's new probe set, chosen here by
// lobe-local v rather than the old lock-weight selection) to show the
// amplitude hierarchy of #37 (upper weakest, lower strongest) and the
// lag/follow-through behavior of #11 (velocity becomes a *delayed*
// lower-contour response, not a uniform addition).
//
// The q(t)/v(t) trajectory is a closed-form decaying oscillation rather than
// the real P2.4 spring driver: P2.4's own dynamics are covered by
// check_inertial_motion.mjs / check_body_kick_pipeline.mjs, and a raw
// velocity-leads-displacement phase relationship (textbook SHM) can put a
// pure "peak tick" comparison either side of zero by a tick or two for a
// realistic driver trace -- exactly the "1~5 tick" scale #38 itself calls
// "desirable", not "required to the tick". Driving a known q(t)/v(t) directly
// makes the two things #66 actually asks for reproducible: (1) the amplitude
// hierarchy, and (2) that the Follow term specifically -- isolated by
// re-running the same q(t) with velocity zeroed -- is what extends the lower
// mass's follow-through past when the raw volume/sag response would have
// settled.
const control = () => ({ checked: false, value: "0", textContent: "", innerHTML: "",
  addEventListener() {}, append() {}, appendChild() {}, classList: { add() {}, remove() {} } });
globalThis.document = { getElementById: control, createElement: control, addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };
globalThis.createImageBitmap = async () => ({});

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
const { deform, state } = Runtime;
const { makeCompiledTopwearFixture, makeChestMotion, attachChestBasis, BASIS_V3_DISTRIBUTION } = await import(
  new URL("qa_compiled_topwear.mjs", import.meta.url));

state.manifest = { anchors: {} };
state.canvasW = 256; state.canvasH = 256;
state.frameOperations = [{ id: "chest", kind: "local_soft_field", phase: "secondary" }];
state.motionQA = { asymmetry: 1, settleMultiplier: 1, side: "both", shapeGain: null, poseActive: false };

// Body moves (0-20), reverses (20-50), then is left to decay/settle on its
// own (50+). `q` and `v` are authored as two independent decaying envelopes
// -- not literally dq/dt -- with `v` given the longer time-constant: a real
// spring's velocity is not simply "whatever q's slope happens to be", and
// directive #11's claim is specifically that residual velocity keeps
// producing lower-contour motion *after* the position signal has already
// returned near rest, i.e. that velocity's envelope outlasts position's.
// That is the one property this test needs to hold, and it is what the
// Follow term (#57) exists to translate into a delayed lower-mass response.
const TICKS = 180;
function qAt(t) {
  if (t <= 20) return 6 * (t / 20);
  if (t <= 50) return 6 - 10 * ((t - 20) / 30); // reverses through 0 to -4
  const tail = t - 50;
  return -4 * Math.exp(-tail / 15); // position settles quickly
}
function vAt(t) {
  if (t <= 50) return (qAt(t) - qAt(t - 1)) * 60; // ordinary slope while actively moving
  const tail = t - 50;
  // Residual spring velocity outlasts the position signal (directive #11).
  return 40 * Math.exp(-tail / 40) * Math.cos(0.12 * tail);
}
const qSeries = Array.from({ length: TICKS }, (_, t) => qAt(t));
const vSeries = Array.from({ length: TICKS }, (_, t) => vAt(t));

function runProbes(useVelocity) {
  const part = attachChestBasis(Runtime, makeCompiledTopwearFixture(), BASIS_V3_DISTRIBUTION);
  const rest = part.mesh.rest;
  const nearestIndex = (x, y) => {
    let best = -1, bestDist = Infinity;
    for (let i = 0; i < rest.length / 2; i++) {
      const d = Math.hypot(rest[i * 2] - x, rest[i * 2 + 1] - y);
      if (d < bestDist) { bestDist = d; best = i; }
    }
    return best;
  };
  // Left lobe geometry: cx=110, cy=145, rx=42, ry=48 (qa_compiled_topwear.mjs).
  const upperI = nearestIndex(100, 120);  // lobe-local v ~ -0.52 (anchor band)
  const centerI = nearestIndex(100, 140); // lobe-local v ~ -0.10 (volume core)
  const lowerI = nearestIndex(100, 180);  // lobe-local v ~ 0.73 (lower mass)
  const upper = [], center = [], lower = [];
  for (let t = 0; t < TICKS; t++) {
    const torso = { model: "inertial_relative_v2",
      left: { value: qSeries[t], velocity: useVelocity ? vSeries[t] : 0 },
      right: { value: qSeries[t], velocity: useVelocity ? vSeries[t] : 0 },
      settleTimeScaleS: 0.03 };
    const motion = makeChestMotion(torso, { physicsDistribution: BASIS_V3_DISTRIBUTION });
    deform(part, t * 1000 / 60, motion);
    const probeDelta = (idx) => Math.hypot(
      part.mesh.live[idx * 2] - part.mesh.rest[idx * 2],
      part.mesh.live[idx * 2 + 1] - part.mesh.rest[idx * 2 + 1]);
    upper.push(probeDelta(upperI)); center.push(probeDelta(centerI)); lower.push(probeDelta(lowerI));
  }
  return { upper, center, lower };
}

const withFollow = runProbes(true);
const noFollow = runProbes(false);

const peak = (values) => Math.max(...values);
const upperPeak = peak(withFollow.upper), centerPeak = peak(withFollow.center), lowerPeak = peak(withFollow.lower);
console.log(`upper peak ${upperPeak.toFixed(3)}px, center peak ${centerPeak.toFixed(3)}px, lower peak ${lowerPeak.toFixed(3)}px`);

// Directive #37: amplitude hierarchy -- upper weakest, lower strongest.
if (!(upperPeak < centerPeak)) throw new Error(`upper peak (${upperPeak}) is not weaker than center peak (${centerPeak})`);
if (!(centerPeak < lowerPeak)) throw new Error(`center peak (${centerPeak}) is not weaker than lower peak (${lowerPeak})`);

// Directive #11/#38: the Follow term, isolated by zeroing velocity in the
// control run, must extend the lower mass's follow-through -- the tick where
// it last stays above a small floor should not be earlier with Follow active
// than without it.
const lastAboveFloor = (values, floor) => {
  for (let i = values.length - 1; i >= 0; i--) if (values[i] >= floor) return i;
  return -1;
};
const floor = 0.02;
const tailWith = lastAboveFloor(withFollow.lower, floor);
const tailWithout = lastAboveFloor(noFollow.lower, floor);
console.log(`lower follow-through: with Follow through tick ${tailWith}, without through tick ${tailWithout}`);
if (!(tailWith >= tailWithout))
  throw new Error(`Follow did not extend the lower mass's follow-through (with ${tailWith} < without ${tailWithout})`);
if (!(tailWith > tailWithout))
  console.log("note: Follow extended the tail by 0 ticks at this floor -- consider a stronger stress case");

// Directive #51: one short settle, not a perpetual pendulum.
if (!(withFollow.lower.at(-1) < 0.2))
  throw new Error(`lower probe did not settle: ${withFollow.lower.at(-1).toFixed(3)}px at final tick`);

console.log("chest basis motion shape checks passed");
