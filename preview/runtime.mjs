/**
 * Portrait Rig Preview -- runtime.
 *
 * Extracted verbatim out of index.html's inline <script> (PORTRAIT_AUTORIG_
 * PRIOR_ART_ABSORPTION_PLAN v0.1 #5, #18, P0-C): every function, constant,
 * and the shared `state` object are unchanged, only `export` was added to
 * each top-level declaration. This is the canonical deformation/build/
 * animation logic; index.html loads it as a module script, and
 * check_deformation.mjs / measure_disocclusion.mjs import it directly
 * instead of string-slicing HTML and `new Function`-evaluating it.
 *
 * Runs in the page it is imported into: top-level statements that touch
 * `document` (event wiring, the ?manifest= autoload) execute at module-
 * evaluation time exactly as they did as a classic inline script. A Node
 * caller must stub the DOM/fetch/performance/location globals this module
 * reads before importing it, mirroring what the old string-eval harness
 * already stubbed.
 */

"use strict";

// Parallax strength as a fraction of the canvas, so the same manifest reads
// the same at any render resolution. Near layers travel further than far ones,
// which is the entire illusion; these are starting values to be tuned against
// A-001, not measurements.
export const TURN_BASE = 0.015;   // every head part moves at least this much
export const TURN_SPAN = 0.045;   // ... plus this much more the nearer it is
export const TURN_Y_SCALE = 0.7;  // vertical parallax reads stronger, so damp it

// How far the idle loop may turn, whatever the manifest allows.
//
// The manifest's `max_x` is the point past which the rig visibly tears, and
// scaling idle by it was the first answer and not enough of one: the reveal
// does not begin there, it merges there. Counted on A-001, the largest
// contiguous region a turn exposes is 584 px of scattered edge at 0.2 and
// 1027 at 0.4, and somewhere between 0.4 and 0.6 those merge into one gash
// down the temple -- 3275 px at 0.6. Idle plays unattended and must not be
// what discovers that, so it stays below where the merge begins. The sliders
// reach 1.5, which is what found it.
export const IDLE_TURN = 0.3;
export const CHEST_WIDEN = 0.004; // ribcage expansion, as a fraction of chest width

// Upper Torso Soft Morph (docs/PORTRAIT_AUTORIG_CHEST_SOFT_MORPH_DESIGN_v0.1.md).
// A local two-lobe volume response layered on top of breathing, confined to
// `topwear` -- CHEST_WIDEN above stays exactly as it is; this is additive.
export const SOFT_MORPH_TAG = "topwear";     // Phase 1 scope: this tag only (design doc 5)
export const SOFT_MORPH_DEFLATE_SCALE = 0.35; // exhale moves less than inhale (design doc 9)
export const SOFT_MORPH_CENTER_TRANSITION = 0.15; // fraction of topwear width past center_lock
                                            // before the lock fully releases (design doc 8.2)

// Groups that can legitimately draw *over* `topwear` at rest -- crossed-arm
// `handwear`, a `neckwear` layered on top -- mirrors `rig.chest_occluder_alpha`'s
// rule exactly (group + drawn-after-topwear), so a vertex under one of these
// gets locked to zero here for the same reason the manifest degrades
// confidence for it there: `topwear` still deforms underneath a static prop,
// and since the prop does not move with it, its edge can crack loose right at
// their seam. This is the precise, per-vertex version of that same concern --
// see `soft_morph.soft_morph_preflight`'s `occluder_alpha`.
export const SOFT_MORPH_OCCLUDER_GROUPS = new Set(["body", "neck"]);

// Ellipsoid shell (H6), read from Anime2.5DRig's 3D-shell mode. Depth parallax
// slides each layer rigidly, so `front hair` and `head` drift apart by their
// depth difference no matter how far apart they are on the picture -- which is
// what opened the temple gash at turnX 1.0. A shell instead lifts every vertex
// onto a head-shaped surface and rotates *that*, so two layers on the same
// shell travel together at the rim and part only by their shells' difference.
//
// Fitted to the `face` part's box, in units of its width and height. The
// numbers are Anime2.5DRig's empirical defaults, kept as starting values.
export const SHELL_CY = 0.45;     // shell centre, down from the top of the face box
export const SHELL_RX = 0.62;     // ... as a fraction of face width
export const SHELL_RY = 0.72;     // ... of face height
export const SHELL_RZ = 0.45;     // how far the nose plane sits in front of the axis
export const HAIR_SCALE = 1.10;   // the hair rides a slightly larger shell, so bangs
export const HAIR_RZ = 1.05;      // ... float above the forehead instead of on it
export const HAIR_LIFT = 0.06;    // ... and sit a little higher on the skull

// Perspective for the reprojection: a short focal length exaggerates the
// foreshortening that makes the turn read as depth rather than as a slide.
export const SHELL_FOCAL = 5.0;   // in units of the shell's own rz
export const SHELL_PERSP = 0.5;

// turn 1.0 in shell radians. Chosen so the nose travels about as far as the
// parallax path moves the face at the same turn value: the blend slider then
// changes *how* the head turns without also changing how much, which is the
// only way the two can be compared on one picture.
export const SHELL_MAX_YAW = 0.52;
export const SHELL_MAX_PITCH = 0.52 * 0.7;   // damped like TURN_Y_SCALE

// Layers that ride the hair shell rather than the head shell.
export const HAIR_SHELL_TAGS = new Set(["front hair", "back hair", "headwear", "hair"]);

export const EYE_TAGS = new Set([
  "eyewhite", "eyewhitel", "eyewhiter",
  "irides", "iridesl", "iridesr",
  "eyelash", "eyelashl", "eyelashr",
  "eyes", "eyel", "eyer",
]);

// The lash is the closed eye. A shut anime eye is a dark line, not an absence,
// and the `face` layer underneath is inpainted skin with no eye drawn on it --
// correctly so -- which means anything that collapses to zero height leaves a
// blank cheek. So the lash keeps a fraction of its height and lands on the lid
// line, while the white and the iris do vanish behind it. A synthesized
// closed-eye layer would be better and is deliberately out of scope for v0.1.
export const LID_TAGS = new Set(["eyelash", "eyelashl", "eyelashr"]);

// How much of the lash's height survives a full close. The layer holds two
// strokes -- an upper lash arc and a thinner lower lash, with a near-empty gap
// between them -- so squashing it too far averages both strokes and the gap
// into one grey band instead of a line, while too little squash leaves the two
// strokes visibly apart. The readable value depends on how the eye was drawn,
// which is why it is a slider.
export const LID_MIN_SCALE = 0.18;

// An eye closes by the upper lid coming *down*, so everything collapses onto
// the lower lid rather than onto the middle of the opening. Closing to the
// centre leaves the lash as a short bar floating in the socket with skin above
// and below it, which reads as a squint rather than a blink. 1.0 is the bottom
// of the eye opening, 0.5 its centre.
export const LID_LINE_RATIO = 0.85;

// Which layer defines the eye opening the lid closes onto, best first.
export const EYE_OPENING_TAGS = ["eyewhite", "irides", "eyes"];

export const DEFAULT_EVALUATION_PHASES = [
  "base", "primary", "corrective", "secondary", "constraints", "visibility", "render",
];

// Phase dispatch is the runtime seam.  Deformers describe *what* is active;
// these handlers decide which phase consumes each kind.  The legacy `deform`
// function remains the geometry backend called by the render loop, rather
// than being the place where a fixed invocation order defines semantics.
export const PHASE_DEFORMER_HANDLERS = {
  gaze(deformer, context) {
    if (context.motion && deformer.config) {
      context.motion.gaze = { ...(context.motion.gaze || {}), ...deformer.config };
    }
  },
  sprite_swap(deformer, context) {
    (context.visibility || (context.visibility = [])).push(deformer.id);
  },
  visibility_curve(deformer, context) {
    (context.visibility || (context.visibility = [])).push(deformer.id);
  },
};

// An expression pack (M4.1) carries drawings the decomposition cannot produce:
// a shut eye, an open mouth. Where one exists it *owns* the feature while it is
// showing, and the parts it stands in for fade out under it.
//
// The crossfade is short and centred on the half-closed pose. A long dissolve
// shows an open eye and a shut one at the same time, which reads as a ghost; an
// instant swap pops. The open eye keeps squashing until the art has taken over,
// so the lid is still seen coming down rather than the eye simply changing.
export const SWAP_LO = 0.35;
export const SWAP_HI = 0.65;

/** Who draws a feature at a given amount of closing, and how far the layers
 *  being replaced are still squashed. With no art this is the v0.1 rig exactly:
 *  the lash squash is the blink. */
export function expressionSwap(amount, hasArt) {
  if (!hasArt) return { art: 0, base: 1, squash: amount };
  const art = smoothstep(SWAP_LO, SWAP_HI, amount);
  return { art, base: 1 - art, squash: Math.min(amount, SWAP_HI) };
}

export const VERT_SRC = `
attribute vec2 a_pos;
attribute vec2 a_uv;
uniform vec2 u_canvas;
varying vec2 v_uv;
void main() {
  vec2 clip = vec2(a_pos.x / u_canvas.x * 2.0 - 1.0,
                   1.0 - a_pos.y / u_canvas.y * 2.0);
  gl_Position = vec4(clip, 0.0, 1.0);
  v_uv = a_uv;
}`;

export const FRAG_SRC = `
precision mediump float;
uniform sampler2D u_tex;
uniform float u_wire;
uniform float u_alpha;
varying vec2 v_uv;
void main() {
  // Premultiplied output throughout: the wire overlay's RGB is pre-scaled by
  // its own alpha, and a part fade scales every channel by u_alpha equally
  // (not just alpha) so the blend stays correctly premultiplied at any fade.
  if (u_wire > 0.5) { gl_FragColor = vec4(0.215, 0.33, 0.5, 0.5); return; }
  gl_FragColor = texture2D(u_tex, v_uv) * u_alpha;
}`;

export const state = {
  manifest: null,
  parts: [],
  gl: null, prog: null, loc: null,
  canvasW: 0, canvasH: 0,
  turnX: 0, turnY: 0, tiltDeg: 0, shell: 0,
  blink: { l: 0, r: 0 },
  mouthOpen: 0, talkUntil: 0, talkTarget: 0,
  art: { l: null, r: null, mouth: null },
  blinkTimer: 0, blinkPhase: null,
  canMipmap: false,
  collarOverride: null,   // null = use whatever the manifest baked in
  shells: null,           // fitted in build(); null disables the shell path
  variantSets: {},
  variantSelections: {},
  variantFades: {},
  parameters: {},
  gazeTargets: [],
  eyeOpening: { l: null, r: null },
  phaseTrace: [],
  phaseDispatch: {},
  t0: performance.now(),
};

/** Set a manifest parameter from a host or a test harness.  Values are
 * clamped to the immutable parameter descriptor range when one is present. */
export function setParameter(id, value) {
  const descriptor = (state.manifest?.parameters || []).find((p) => p.id === id);
  let numeric = Number(value);
  if (!Number.isFinite(numeric)) numeric = descriptor?.default ?? 0;
  if (descriptor) numeric = Math.max(descriptor.min, Math.min(descriptor.max, numeric));
  state.parameters[id] = numeric;
  return numeric;
}

function parameterValue(id, motion = {}) {
  if (motion.parameters && motion.parameters[id] != null) return Number(motion.parameters[id]);
  if (id === "ParamAngleX") return Number(motion.turnX ?? state.turnX ?? 0);
  if (id === "ParamAngleY") return Number(motion.turnY ?? state.turnY ?? 0);
  if (id === "ParamAngleZ") return Number(motion.tiltRad ?? 0);
  if (id === "ParamEyeLOpen" && motion.blink) return 1 - Number(motion.blink.l ?? 0);
  if (id === "ParamEyeROpen" && motion.blink) return 1 - Number(motion.blink.r ?? 0);
  if (id === "ParamMouthOpenY" && motion.mouthOpen != null) return Number(motion.mouthOpen);
  if (id === "ParamBreath" && motion.breath != null) return Number(motion.breath);
  if (id === "ParamEyeBallX") return Number(motion.gazeX ?? state.parameters[id] ?? 0);
  if (id === "ParamEyeBallY") return Number(motion.gazeY ?? state.parameters[id] ?? 0);
  if (state.parameters[id] != null) return Number(state.parameters[id]);
  return 0;
}

/** Runtime binding for Composer VariantSets (P0-F2).  Composer instance ids
 * are resolved through manifest.member_bindings; no semantic-name guessing is
 * performed here. */
export function applyVariantSet(setId, memberId, options = {}) {
  const spec = state.manifest && (state.manifest.variant_sets || {})[setId];
  if (!spec || !spec.members.includes(memberId)) {
    throw new Error(`unknown VariantSet member: ${setId}/${memberId}`);
  }
  const transition = options.transition || spec.transition || "discrete";
  if (transition !== "discrete" && transition !== "crossfade") {
    throw new Error(`unsupported VariantSet transition: ${transition}`);
  }
  const names = spec.members.map((id) => spec.member_bindings[id]?.part).filter(Boolean);
  const byName = new Map(state.parts.map((p) => [p.spec.name, p]));
  if (names.length !== spec.members.length || names.some((name) => !byName.has(name))) {
    throw new Error(`VariantSet ${setId} has an incomplete member binding`);
  }
  const previous = state.variantSelections[setId] ?? spec.default;
  state.variantSelections[setId] = memberId;
  if (transition === "crossfade" && previous !== memberId) {
    state.variantFades[setId] = {
      from: previous, to: memberId, start: performance.now(),
      duration: Math.max(1, Number(options.duration_ms ?? 120)),
    };
    for (const id of spec.members) byName.get(spec.member_bindings[id].part).visible = true;
  } else {
    delete state.variantFades[setId];
    for (const id of spec.members) {
      byName.get(spec.member_bindings[id].part).visible = id === memberId;
    }
  }
  return { set: setId, member: memberId, transition };
}

/** Apply all selections as one validated transaction. */
export function applyExpressionPreset(presetId, options = {}) {
  const preset = state.manifest && (state.manifest.expression_presets || {})[presetId];
  if (!preset || !preset.variants) throw new Error(`unknown ExpressionPreset: ${presetId}`);
  const selections = Object.entries(preset.variants);
  for (const [setId, memberId] of selections) {
    const spec = (state.manifest.variant_sets || {})[setId];
    if (!spec || !spec.members.includes(memberId)) {
      throw new Error(`ExpressionPreset ${presetId} selects invalid member ${setId}/${memberId}`);
    }
  }
  const result = [];
  for (const [setId, memberId] of selections) result.push(applyVariantSet(setId, memberId, options));
  return result;
}

function visibilityCurveValue(deformer, value) {
  const points = deformer.points || deformer.stops || deformer.curve
    || deformer.config?.points || deformer.config?.stops || deformer.config?.curve || [];
  if (!Array.isArray(points) || points.length === 0) return 1;
  const normalized = points.map((p) => Array.isArray(p)
    ? { value: Number(p[0]), alpha: Number(p[1]) }
    : { value: Number(p.value ?? p.x), alpha: Number(p.alpha ?? p.y) })
    .filter((p) => Number.isFinite(p.value) && Number.isFinite(p.alpha))
    .sort((a, b) => a.value - b.value);
  if (!normalized.length) return 1;
  if (value <= normalized[0].value) return Math.max(0, Math.min(1, normalized[0].alpha));
  const last = normalized[normalized.length - 1];
  if (value >= last.value) return Math.max(0, Math.min(1, last.alpha));
  for (let i = 1; i < normalized.length; i++) {
    const hi = normalized[i], lo = normalized[i - 1];
    if (value <= hi.value) {
      const t = (value - lo.value) / Math.max(1e-9, hi.value - lo.value);
      return Math.max(0, Math.min(1, lo.alpha + (hi.alpha - lo.alpha) * t));
    }
  }
  return 1;
}

function curveTargets(deformer) {
  const raw = deformer.targets ?? deformer.target ?? deformer.config?.targets ?? [];
  if (typeof raw === "string") return [raw];
  if (Array.isArray(raw)) return raw;
  if (raw && typeof raw === "object") {
    if (Array.isArray(raw.tags)) return raw.tags;
    if (Array.isArray(raw.parts)) return raw.parts;
    if (typeof raw.tag === "string") return [raw.tag];
    if (typeof raw.part === "string") return [raw.part];
  }
  return [];
}

function visibilityCurveAlpha(part, motion) {
  let alpha = 1;
  for (const deformer of (state.manifest?.deformers || [])) {
    if (deformer.kind !== "visibility_curve" || deformer.phase !== "visibility") continue;
    const targets = curveTargets(deformer);
    if (!targets.includes(part.spec.name) && !targets.includes(part.spec.tag)) continue;
    const parameter = deformer.parameter || deformer.parameters?.[0];
    const value = parameter ? parameterValue(parameter, motion) : 0;
    alpha *= visibilityCurveValue(deformer, Number.isFinite(value) ? value : 0);
  }
  return Math.max(0, Math.min(1, alpha));
}

/** Consume visibility-phase entries and finish expired VariantSet fades. */
export function evaluateVisibilityPhase(now = performance.now()) {
  for (const [setId, fade] of Object.entries(state.variantFades)) {
    if (now - fade.start >= fade.duration) applyVariantSet(setId, fade.to, { transition: "discrete" });
  }
  return (state.manifest?.deformers || []).filter(
    (d) => (d.kind === "sprite_swap" || d.kind === "visibility_curve") && d.phase === "visibility");
}

export function evaluateDrivers(phase, context = {}) {
  const entries = (state.manifest?.drivers || []).filter((d) => (d.phase || "secondary") === phase);
  context.executedDrivers = (context.executedDrivers || []).concat(entries.map((d) => d.id));
  return entries;
}

export function evaluateDeformers(phase, context = {}) {
  const entries = (state.manifest?.deformers || []).filter((d) => d.phase === phase);
  context.executedDeformers = (context.executedDeformers || []).concat(entries.map((d) => d.id));
  state.phaseDispatch[phase] = entries.map((d) => ({ id: d.id, kind: d.kind }));
  for (const deformer of entries) {
    const handler = PHASE_DEFORMER_HANDLERS[deformer.kind];
    if (handler) handler(deformer, context);
  }
  if (phase === "visibility") evaluateVisibilityPhase(context.now ?? performance.now());
  return entries;
}

export function evaluateConstraints(phase, context = {}) {
  const entries = (state.manifest?.constraints || []).filter((d) => (d.phase || "constraints") === phase);
  context.executedConstraints = (context.executedConstraints || []).concat(entries.map((d) => d.id));
  state.phaseDispatch[phase] = (state.phaseDispatch[phase] || []).concat(
    entries.map((d) => ({ id: d.id, kind: d.kind || "constraint" })));
  return entries;
}

/** Execute the manifest's declared phase order. Geometry remains in the
 * render loop, while every declarative phase is visited in this one order. */
export function evaluatePhase(phase, now = performance.now(), context = {}) {
  const allowed = state.manifest?.evaluation?.phases;
  if (allowed && !allowed.includes(phase)) throw new Error(`unknown evaluation phase: ${phase}`);
  context.now = now;
  evaluateDrivers(phase, context);
  const result = evaluateDeformers(phase, context);
  evaluateConstraints(phase, context);
  state.phaseTrace.push(phase);
  return result;
}

export function evaluateAllPhases(now = performance.now(), context = {}) {
  state.phaseTrace = [];
  state.phaseDispatch = {};
  const phases = state.manifest?.evaluation?.phases || DEFAULT_EVALUATION_PHASES;
  for (const phase of phases) evaluatePhase(phase, now, context);
  return state.phaseTrace.slice();
}

function phaseEnabled(phase) {
  const phases = state.manifest?.evaluation?.phases;
  return !Array.isArray(phases) || phases.includes(phase);
}

/* ---------- loading ---------- */

export const dropEl = document.getElementById("drop");
export const errEl = document.getElementById("err");

document.getElementById("pick").addEventListener("click", () => {
  const input = document.createElement("input");
  input.type = "file";
  input.webkitdirectory = true;
  input.addEventListener("change", () => loadFromFiles([...input.files]));
  input.click();
});

document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", async (e) => {
  e.preventDefault();
  const files = [];
  const walk = async (entry, path) => {
    if (entry.isFile) {
      const file = await new Promise((res) => entry.file(res));
      file._path = path + entry.name;
      files.push(file);
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch;
      do {
        batch = await new Promise((res) => reader.readEntries(res));
        for (const child of batch) await walk(child, path + entry.name + "/");
      } while (batch.length);
    }
  };
  for (const item of e.dataTransfer.items) {
    const entry = item.webkitGetAsEntry && item.webkitGetAsEntry();
    if (entry) await walk(entry, "");
  }
  loadFromFiles(files);
});

/** Every image the manifest names, as [name, spec]: the rig's parts plus the
 *  expression pack's, which live in their own block so a run without one loads
 *  exactly as it did before. */
export function allParts(manifest) {
  const out = manifest.parts.map((p) => [p.name, p]);
  const pack = (manifest.expressions || {}).parts || {};
  for (const [name, entry] of Object.entries(pack)) out.push([name, entry]);
  return out;
}

export function pathOf(file) {
  return (file._path || file.webkitRelativePath || file.name).replace(/\\/g, "/");
}

export async function loadFromFiles(files) {
  errEl.textContent = "";
  const manifestFile = files.find((f) => /_rig_manifest\.json$/.test(pathOf(f)));
  if (!manifestFile) {
    errEl.textContent = "No *_rig_manifest.json in that folder. Run A-001 with " +
                        "\"Export 2.5D rig manifest\" enabled.";
    return;
  }
  let manifest;
  try {
    manifest = JSON.parse(await manifestFile.text());
  } catch (e) {
    errEl.textContent = "Could not parse the manifest: " + e.message;
    return;
  }
  // Match each part's declared image path against the picked files by suffix:
  // the picker roots paths at whatever folder was chosen, which may be the run
  // directory or its parent.
  const byPath = new Map(files.map((f) => [pathOf(f), f]));
  const find = (rel) => {
    for (const [path, file] of byPath) if (path.endsWith("/" + rel) || path === rel) return file;
    return null;
  };
  const missing = [];
  const images = new Map();
  for (const [name, part] of allParts(manifest)) {
    const file = find(part.image);
    if (!file) { missing.push(part.image); continue; }
    images.set(name, await createImageBitmap(file));
  }
  if (missing.length) {
    errEl.textContent = "Missing part images:\n" + missing.join("\n");
    return;
  }
  build(manifest, images);
  dropEl.classList.add("hidden");
}

// Serving the run over HTTP instead? ?manifest=<url> skips the picker.
export const fromQuery = new URLSearchParams(location.search).get("manifest");
if (fromQuery) {
  (async () => {
    try {
      // `no-store` throughout: a run directory is rewritten in place, and a
      // cached layer beside a fresh manifest renders an artifact that was
      // fixed hours ago -- which is worse than no preview at all, because it
      // looks like a finding.
      const manifest = await (await fetch(fromQuery, { cache: "no-store" })).json();
      const base = fromQuery.slice(0, fromQuery.lastIndexOf("/") + 1);
      const images = new Map();
      for (const [name, part] of allParts(manifest)) {
        const blob = await (await fetch(base + part.image, { cache: "no-store" })).blob();
        images.set(name, await createImageBitmap(blob));
      }
      build(manifest, images);
      dropEl.classList.add("hidden");
    } catch (e) {
      errEl.textContent = "Could not load ?manifest=: " + e.message;
    }
  })();
}

/* ---------- geometry ---------- */

export function smoothstep(edge0, edge1, x) {
  if (edge1 === edge0) return x < edge0 ? 0 : 1;
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

/** Head-follow weight for a vertex, from the manifest's weight spec. The
 *  gradient is what a bone rig cannot express: the top of the neck follows the
 *  head while its bottom stays with the body. */
export function weightAt(spec, y) {
  if (spec.mode === "gradient_y") {
    return spec.bottom + (spec.top - spec.bottom) * (1 - smoothstep(spec.y_top, spec.y_bottom, y));
  }
  return spec.value;
}

/** Vertical breathing profile: 1 above the chest, falling linearly to 0 at the
 *  planted bottom of the torso. One field for every part, so the head, the
 *  neck and the shoulders cannot drift apart at their seams. */
export function breathRamp(y) {
  const top = state.breathTop, bottom = state.breathBottom;
  if (!(bottom > top)) return 1;          // no torso to plant against
  if (y <= top) return 1;
  if (y >= bottom) return 0;
  return (bottom - y) / (bottom - top);
}

/** Fit the head and hair ellipsoids to the `face` part's box. Everything the
 *  shell needs is one box: the manifest has no head model and is not going to
 *  grow one for a feasibility rig. Returns null when there is no face layer,
 *  which disables the shell path rather than guessing. */
export function fitShells(parts) {
  const face = parts.find((p) => p.tag === "face") || parts.find((p) => p.tag === "head");
  if (!face) return null;
  const [x1, y1, x2, y2] = face.xyxy;
  const w = x2 - x1, h = y2 - y1;
  if (!(w > 0 && h > 0)) return null;
  const head = {
    cx: (x1 + x2) / 2, cy: y1 + h * SHELL_CY,
    rx: w * SHELL_RX, ry: h * SHELL_RY, rz: w * SHELL_RZ,
  };
  return {
    head,
    hair: {
      cx: head.cx, cy: head.cy - head.ry * HAIR_LIFT,
      rx: head.rx * HAIR_SCALE, ry: head.ry * HAIR_SCALE, rz: head.rz * HAIR_RZ,
    },
  };
}

// Scratch, so the per-vertex path allocates nothing.
export const SHELL_OUT = [0, 0];

/** Where a vertex goes when it is lifted onto `shell`, rotated by yaw/pitch and
 *  reprojected -- as a *difference* from where the same lift and reprojection
 *  put it at rest. Difference-only is what lets the shell blend with parallax:
 *  at yaw = pitch = 0 it returns (0, 0) exactly, so a shell weight of 1 with no
 *  turn is still the rest pose, and the projection's own distortion never
 *  reaches the picture.
 *
 *  Vertices outside the ellipse sit on its rim (z = 0) rather than being
 *  clamped inward, so a layer that overhangs the head -- back hair, the jaw of
 *  the `head` layer -- stays continuous with the part of it that is on the
 *  shell. */
export function shellDelta(shell, x, y, yaw, pitch, out = SHELL_OUT) {
  const u = (x - shell.cx) / shell.rx, v = (y - shell.cy) / shell.ry;
  const z = Math.sqrt(Math.max(0, 1 - Math.min(1, u * u + v * v)));
  const X = u * shell.rx, Y = v * shell.ry, Z = z * shell.rz;
  const cy = Math.cos(yaw), sy = Math.sin(yaw);
  const cp = Math.cos(pitch), sp = Math.sin(pitch);
  const X2 = X * cy + Z * sy, Z2 = -X * sy + Z * cy;
  const Y2 = Y * cp - Z2 * sp, Z3 = Y * sp + Z2 * cp;
  const f = shell.rz * SHELL_FOCAL;
  const sc = f / (f - Z3 * SHELL_PERSP), sc0 = f / (f - Z * SHELL_PERSP);
  out[0] = X2 * sc - X * sc0;
  out[1] = Y2 * sc - Y * sc0;
  return out;
}

/** Uniform grid: the P0 default, unchanged from before P1-A. Returns
 *  `{pts, idx, wire}` -- `pts` as `{x, y, u, v}`, canvas-absolute position
 *  plus the UV it was generated from (not re-derived from x/y, so this is
 *  bit-for-bit the arithmetic buildMesh always did). */
function gridVertexList(part) {
  const [x1, y1, x2, y2] = part.xyxy;
  const cell = Math.max(4, part.mesh.cell);
  const cols = Math.max(1, Math.round((x2 - x1) / cell));
  const rows = Math.max(1, Math.round((y2 - y1) / cell));
  const pts = [];
  for (let r = 0; r <= rows; r++) {
    for (let c = 0; c <= cols; c++) {
      const u = c / cols, v = r / rows;
      pts.push({ x: x1 + (x2 - x1) * u, y: y1 + (y2 - y1) * v, u, v });
    }
  }
  const idx = [], wire = [];
  const at = (r, c) => r * (cols + 1) + c;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const a = at(r, c), b = at(r, c + 1), d = at(r + 1, c), e = at(r + 1, c + 1);
      idx.push(a, b, d, b, e, d);
      wire.push(a, b, a, d);
      if (c === cols - 1) wire.push(b, e);
      if (r === rows - 1) wire.push(d, e);
    }
  }
  return { pts, idx, wire };
}

/** Contour mesh (P1-A, absorption plan #8): `part.mesh.vertices`/`.triangles`
 *  are baked at compile time (`mesh.contour_mesh` in the Python compiler) --
 *  this only reads them and derives UV/wireframe from them, the same way
 *  the grid path derives UV from its own procedural vertices. Wireframe
 *  edges come from the triangle list directly (every triangle edge,
 *  deduplicated) rather than grid row/col adjacency, so the debug overlay
 *  shows the real triangulation, diagonals included. */
function contourVertexList(part) {
  const [x1, y1, x2, y2] = part.xyxy;
  const width = x2 - x1, height = y2 - y1;
  const pts = part.mesh.vertices.map(([x, y]) => ({
    x, y,
    u: width === 0 ? 0 : (x - x1) / width,
    v: height === 0 ? 0 : (y - y1) / height,
  }));
  const idx = [];
  for (const [a, b, c] of part.mesh.triangles) idx.push(a, b, c);
  const seen = new Set();
  const wire = [];
  const addEdge = (a, b) => {
    const key = a < b ? `${a}_${b}` : `${b}_${a}`;
    if (seen.has(key)) return;
    seen.add(key);
    wire.push(a, b);
  };
  for (const [a, b, c] of part.mesh.triangles) { addEdge(a, b); addEdge(b, c); addEdge(c, a); }
  return { pts, idx, wire };
}

export function buildMesh(part) {
  const isContour = part.mesh && part.mesh.kind === "contour"
    && part.mesh.vertices && part.mesh.triangles;
  const { pts, idx, wire } = isContour ? contourVertexList(part) : gridVertexList(part);

  const rest = [], uv = [], weight = [], ramp = [];
  const spec = part.weight;
  const span = spec.mode === "gradient_y" ? spec.top - spec.bottom : 0;
  for (const p of pts) {
    const w = weightAt(spec, p.y);
    rest.push(p.x, p.y);
    uv.push(p.u, p.v);
    weight.push(w);
    // Where this vertex sits along its gradient, 0 at the bottom value and 1
    // at the top, so a slider can re-aim the top without a rebuild.
    ramp.push(span === 0 ? 0 : (w - spec.bottom) / span);
  }
  return {
    rest: new Float32Array(rest), uv: new Float32Array(uv),
    weight: new Float32Array(weight), ramp: new Float32Array(ramp),
    live: new Float32Array(rest),
    index: new Uint16Array(idx), wireIndex: new Uint16Array(wire),
    count: idx.length, wireCount: wire.length,
  };
}

/** Read back a loaded part's own alpha channel, for sampling against other
 *  parts' vertices. `ImageBitmap` has no direct pixel read, so this draws it
 *  once onto a scratch canvas -- done only for the handful of parts that can
 *  occlude `topwear`, not per frame. */
export function readAlpha(bitmap) {
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0);
  return ctx.getImageData(0, 0, bitmap.width, bitmap.height).data;
}

/** Every loaded part that can draw *over* `topwear` at rest (design doc 8.3's
 *  shoulder lock, generalized): later in z, sharing the body/neck plane.
 *  Each entry carries its own crop `xyxy` plus its raw alpha, so a canvas
 *  point can be tested against it directly without re-deriving anything the
 *  manifest already computed for the part itself. */
export function gatherChestOccluders(manifest, images) {
  const topwear = manifest.parts.find((p) => p.tag === SOFT_MORPH_TAG);
  if (!topwear) return [];
  return manifest.parts
    .filter((p) => p.tag !== SOFT_MORPH_TAG && p.z > topwear.z
                && SOFT_MORPH_OCCLUDER_GROUPS.has(p.group))
    .map((p) => {
      const bitmap = images.get(p.name);
      return bitmap ? { xyxy: p.xyxy, width: bitmap.width, alpha: readAlpha(bitmap) } : null;
    })
    .filter(Boolean);
}

/** Alpha (0-255) of one occluder at an absolute canvas point, 0 outside its
 *  own crop. Matches the manifest's own `alpha_threshold` convention (10) at
 *  the call site, not here -- this only samples. */
export function occluderAlphaAt(occluder, x, y) {
  const [ox1, oy1, ox2, oy2] = occluder.xyxy;
  if (x < ox1 || x >= ox2 || y < oy1 || y >= oy2) return 0;
  const lx = Math.floor(x - ox1), ly = Math.floor(y - oy1);
  return occluder.alpha[(ly * occluder.width + lx) * 4 + 3];
}

/** Precompute the two-lobe soft-morph weight field for a `topwear` mesh
 *  (design doc 6-8): per-vertex left/right ellipse weight, each already
 *  multiplied by the neckline and center locks, plus a lower-bias factor for
 *  the small vertical component (9.2). Baked once at build time exactly like
 *  `weight`/`ramp` in `buildMesh` -- the region geometry never changes frame
 *  to frame, only `morph` (the breathing-driven scalar) does.
 *
 *  `occluders` (see `gatherChestOccluders`) additionally locks any vertex
 *  actually covered by a static prop like crossed-arm `handwear` to exactly
 *  zero: that part of `topwear` is invisible at rest, but would otherwise
 *  still deform underneath a layer that never moves with it, cracking loose
 *  right at their seam. Everywhere else -- the part of the lobe genuinely on
 *  screen -- keeps its full weight, which a global strength cut cannot do. */
export function buildSoftMorphWeights(part, mesh, spec, occluders) {
  const [x1, y1, x2, y2] = part.xyxy;
  const width = x2 - x1, height = y2 - y1;
  const centerX = (x1 + x2) / 2;
  const neckLockBottom = y1 + height * spec.neckline_lock;
  const centerLockHalf = spec.center_lock * width;
  const centerLockOuter = centerLockHalf + SOFT_MORPH_CENTER_TRANSITION * width;

  const lobeGeom = (lobe) => ({
    cx: x1 + lobe.center[0] * width, cy: y1 + lobe.center[1] * height,
    rx: Math.max(1e-6, lobe.radius[0] * width), ry: Math.max(1e-6, lobe.radius[1] * height),
  });
  const left = lobeGeom(spec.left), right = lobeGeom(spec.right);

  const n = mesh.rest.length / 2;
  const wl = new Float32Array(n), wr = new Float32Array(n), lower = new Float32Array(n);
  for (let i = 0, v = 0; i < n; i++, v += 2) {
    const x = mesh.rest[v], y = mesh.rest[v + 1];
    // Neckline lock (8.1): 0 at the garment's own top edge, released by the
    // manifest's `neckline_lock` fraction of its height. Center lock (8.2):
    // 0 within `center_lock` of the button/seam line, released over the
    // fixed transition band above.
    let lock = smoothstep(y1, neckLockBottom, y) * smoothstep(centerLockHalf, centerLockOuter, Math.abs(x - centerX));
    if (lock > 0) {
      for (const occ of occluders) {
        if (occluderAlphaAt(occ, x, y) > 10) { lock = 0; break; }
      }
    }

    const dl2 = ((x - left.cx) / left.rx) ** 2 + ((y - left.cy) / left.ry) ** 2;
    const dr2 = ((x - right.cx) / right.rx) ** 2 + ((y - right.cy) / right.ry) ** 2;
    wl[i] = smoothstep(1, 0, dl2) * lock;
    wr[i] = smoothstep(1, 0, dr2) * lock;
    // Concentrates the vertical component toward the bottom of whichever
    // lobe a vertex is nearer, rather than lifting the whole zone uniformly
    // -- which would fight the neckline lock right above it.
    const near = dl2 <= dr2 ? left : right;
    lower[i] = Math.max(0, Math.min(1, (y - near.cy) / near.ry));
  }
  return { left: wl, right: wr, lowerBias: lower };
}

/* ---------- GL ---------- */

export function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
  return sh;
}

export function initGL(canvas) {
  // WebGL2 first, only for its NPOT mipmap support: a blinking eye squashes its
  // lash to a fifth of its height, and minifying that far with a plain LINEAR
  // sampler takes two texels out of the six it should be averaging, which turns
  // a lash into a shimmering band. WebGL1 remains a working fallback.
  const opts = { premultipliedAlpha: false, antialias: true };
  const gl = canvas.getContext("webgl2", opts) || canvas.getContext("webgl", opts);
  if (!gl) throw new Error("WebGL is not available in this browser.");
  state.canMipmap = typeof gl.texStorage2D === "function";  // i.e. WebGL2
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT_SRC));
  gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FRAG_SRC));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  gl.useProgram(prog);
  gl.enable(gl.BLEND);
  // Premultiplied-alpha blend: RGB is already scaled by alpha (both in the
  // uploaded texture and in the shader's own fade), so the source RGB factor
  // is ONE, not SRC_ALPHA. This is what stops linear filtering from bleeding
  // a fully-transparent border texel's undefined RGB into a part's edge --
  // the seam that showed up between independently-cropped parts like neck and
  // topwear.
  gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  gl.disable(gl.DEPTH_TEST);  // draw order is the manifest's z, back to front
  return {
    gl, prog,
    loc: {
      pos: gl.getAttribLocation(prog, "a_pos"),
      uv: gl.getAttribLocation(prog, "a_uv"),
      canvas: gl.getUniformLocation(prog, "u_canvas"),
      tex: gl.getUniformLocation(prog, "u_tex"),
      wire: gl.getUniformLocation(prog, "u_wire"),
      alpha: gl.getUniformLocation(prog, "u_alpha"),
    },
  };
}

export function makeTexture(gl, bitmap) {
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  // Part crops are arbitrary sizes, so no mipmaps and clamp at the edges.
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
  if (state.canMipmap) {
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
  } else {
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  }
  return tex;
}

/* ---------- build ---------- */

/** P0-D adapter (PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1 #7, #19):
 *  reconstruct the v0.1-shaped `motion{}` this runtime evaluates with from
 *  `manifest.deformers[]`, which is v0.2's source of truth for the same
 *  tuning numbers (see `manifest.deformers_from_motion` in the Python
 *  compiler -- each deformer's `config` is a verbatim copy of the
 *  corresponding v0.1 `motion.*` sub-object). The deformation math itself
 *  (`deform`, `scheduleBlink`, `startBlink`, the idle loop in `frame`) is
 *  unchanged: only where it reads its tuning numbers from changes. A
 *  manifest with no `deformers[]` (pre-P0-B) falls back to its own
 *  `motion{}` untouched, so an old saved manifest keeps working. Anything
 *  P0-B does not synthesize a deformer for (`upper_torso_soft_morph`) is
 *  carried through from `motion{}` unchanged either way. */
export function motionFromDeformers(manifest) {
  const deformers = manifest.deformers;
  const motion = { ...(manifest.motion || {}) };
  if (!deformers || !deformers.length) return motion;
  const byKind = {};
  for (const d of deformers) (byKind[d.kind] ||= []).push(d);

  const shell = (byKind.shell_turn || [])[0];
  if (shell) motion.head_turn = shell.config;

  const tilt = (byKind.weighted_rotation || [])[0];
  if (tilt) motion.head_tilt = tilt.config;

  const breathing = (byKind.continuous_field || [])
    .find((d) => (d.parameters || []).includes("ParamBreath"));
  if (breathing) motion.breathing = breathing.config;

  const blinkL = (byKind.eye_fold || [])
    .find((d) => d.targets && d.targets.side === "l");
  if (blinkL) motion.blink = blinkL.config;

  const gaze = (byKind.gaze || [])[0];
  if (gaze) motion.gaze = gaze.config || {};

  return motion;
}

export function build(manifest, images) {
  const canvas = document.getElementById("gl");
  const overlayCanvas = document.getElementById("regionOverlay");
  manifest = { ...manifest, motion: motionFromDeformers(manifest) };
  state.manifest = manifest;
  state.parameters = {};
  for (const descriptor of (manifest.parameters || [])) {
    if (descriptor && descriptor.id) state.parameters[descriptor.id] = Number(descriptor.default ?? 0);
  }
  state.phaseTrace = [];
  state.canvasW = manifest.canvas.width;
  state.canvasH = manifest.canvas.height;
  canvas.width = state.canvasW;
  canvas.height = state.canvasH;
  overlayCanvas.width = state.canvasW;
  overlayCanvas.height = state.canvasH;

  const { gl, prog, loc } = initGL(canvas);
  state.gl = gl; state.prog = prog; state.loc = loc;
  gl.uniform2f(loc.canvas, state.canvasW, state.canvasH);

  const anchors = manifest.anchors || {};

  // The eye opening, per side, taken from whichever layer actually draws it --
  // the lash's own box includes the upper lashes and sits too high to close on.
  const opening = {};
  for (const suffix of ["l", "r", ""]) {
    for (const base of EYE_OPENING_TAGS) {
      const found = manifest.parts.find((p) => p.tag === base + suffix);
      if (found) { opening[suffix] = found.xyxy; break; }
    }
  }
  state.eyeOpening = { l: opening.l || opening[""] || null, r: opening.r || opening[""] || null };

  state.shells = fitShells(manifest.parts);

  // An expression sprite is placed by the parts it stands in for: their front
  // z, their nearest depth, and -- the point -- *their* weight, so it moves
  // exactly as the feature it is covering rather than as a new tag that
  // happened to land in the head group.
  const byName = new Map(manifest.parts.map((p) => [p.name, p]));
  const packEntries = Object.entries((manifest.expressions || {}).parts || {});
  const expressionSpecs = packEntries.map(([name, entry]) => {
    const replaced = (entry.replaces || []).map((n) => byName.get(n)).filter(Boolean);
    const front = replaced.length
      ? replaced.reduce((a, b) => (a.z > b.z ? a : b)) : null;
    return {
      name, tag: name, image: entry.image, xyxy: entry.xyxy, group: "head",
      depth: entry.depth != null ? entry.depth : front ? front.depth : 0.5,
      z: entry.z != null ? entry.z : front ? front.z + 0.5 : 99,
      weight: front ? front.weight : { mode: "constant", value: 1.0 },
      mesh: { cell: 42 },
      expression: { kind: entry.kind, side: entry.side, replaces: entry.replaces || [] },
    };
  });

  const softSpec = (manifest.motion || {}).upper_torso_soft_morph;
  const hasSoftRegion = !!(softSpec && softSpec.left && softSpec.right);
  const chestOccluders = hasSoftRegion ? gatherChestOccluders(manifest, images) : [];

  state.parts = manifest.parts.concat(expressionSpecs)
      .sort((a, b) => a.z - b.z).map((part) => {
    const mesh = buildMesh(part);
    const isEye = EYE_TAGS.has(part.tag);
    // Only eye parts get a side: plenty of other tags end in 'l' or 'r'
    // ("back hair", "topwear") and must not claim an eye anchor.
    const side = !isEye ? null : part.tag.endsWith("l") ? "l" : part.tag.endsWith("r") ? "r" : null;
    const eyeAnchor = side === "l" ? anchors.eye_left : side === "r" ? anchors.eye_right : null;
    const box = opening[side || ""] || part.xyxy;
    return {
      spec: part, mesh, visible: part.visible !== false,
      tex: makeTexture(gl, images.get(part.name)),
      buf: { pos: gl.createBuffer(), uv: gl.createBuffer(),
             idx: gl.createBuffer(), wire: gl.createBuffer() },
      isEye,
      // A body part with a gradient is a collar riding over the neck, and its
      // strength is the one weight in the manifest that is a taste call.
      isCollar: part.group === "body" && part.weight.mode === "gradient_y",
      isLid: LID_TAGS.has(part.tag),
      expression: part.expression || null,
      replacedBy: null,
      // The shell is a model of a head, so the torso does not ride it: a
      // vertex below the ellipse would only be squeezed toward the head's axis.
      // Anime2.5DRig gives the body its own cylinder; that is a separate
      // experiment and this one is about the head's turn.
      shell: !state.shells || part.group === "body" ? null
           : HAIR_SHELL_TAGS.has(part.tag) ? state.shells.hair : state.shells.head,
      eyeSide: side,
      eyeCenterY: eyeAnchor ? eyeAnchor[1] : (part.xyxy[1] + part.xyxy[3]) / 2,
      openTop: box[1],
      openBottom: box[3],
      // Phase 1 scope (design doc 5): only `topwear` deforms.
      softMorph: (hasSoftRegion && part.tag === SOFT_MORPH_TAG)
        ? buildSoftMorphWeights(part, mesh, softSpec, chestOccluders) : null,
    };
  });

  state.variantSets = manifest.variant_sets || {};
  state.variantSelections = {};
  state.variantFades = {};
  for (const [setId, spec] of Object.entries(state.variantSets)) {
    state.variantSelections[setId] = spec.default;
    // The manifest marks the default member visible; enforce it here too so
    // old runtimes loading a hand-edited manifest cannot show two members.
    for (const member of spec.members || []) {
      const partName = spec.member_bindings?.[member]?.part;
      const part = state.parts.find((p) => p.spec.name === partName);
      if (part) part.visible = member === spec.default;
    }
  }

  // Who owns which feature. A pack part answers to one key; the parts it
  // stands in for answer to the same one, so a single number drives both sides
  // of the fade and they cannot disagree about how far it has got.
  state.art = { l: null, r: null, mouth: null };
  for (const p of state.parts) {
    if (!p.expression) continue;
    const key = p.expression.kind === "mouth" ? "mouth" : p.expression.side;
    if (!key || !(key in state.art)) continue;
    state.art[key] = p;
    for (const name of p.expression.replaces) {
      const target = state.parts.find((q) => q.spec.name === name);
      if (target) target.replacedBy = key;
    }
  }

  // The chest band the breathing field is measured against. `topwear` is the
  // torso proper; body_remainder can reach far up the canvas and would drag the
  // band with it, so it is only a fallback.
  const torso = state.parts.filter((p) => p.spec.group === "body");
  const chest = torso.find((p) => p.spec.tag === "topwear") || torso[0];
  state.breathTop = chest ? chest.spec.xyxy[1] : 0;
  state.breathBottom = anchors.body_pivot ? anchors.body_pivot[1]
                     : chest ? chest.spec.xyxy[3] : state.canvasH;
  state.chestCx = chest ? (chest.spec.xyxy[0] + chest.spec.xyxy[2]) / 2 : state.canvasW / 2;

  for (const p of state.parts) {
    gl.bindBuffer(gl.ARRAY_BUFFER, p.buf.uv);
    gl.bufferData(gl.ARRAY_BUFFER, p.mesh.uv, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, p.buf.pos);
    gl.bufferData(gl.ARRAY_BUFFER, p.mesh.live, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, p.buf.idx);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, p.mesh.index, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, p.buf.wire);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, p.mesh.wireIndex, gl.STATIC_DRAW);
  }

  const collarPart = state.parts.find((p) => p.isCollar);
  if (collarPart) document.getElementById("collar").value = collarPart.spec.weight.top;

  const amp = document.getElementById("breathAmp");
  amp.value = manifest.motion.breathing.amplitude_px;
  document.getElementById("breathAmpv").textContent =
    Number(amp.value).toFixed(1) + "px";

  const lid = document.getElementById("lidLine");
  lid.value = manifest.motion.blink.lid_ratio ?? LID_LINE_RATIO;
  document.getElementById("lidLinev").textContent = Number(lid.value).toFixed(2);
  const thick = document.getElementById("lidThick");
  thick.value = manifest.motion.blink.lid_thickness ?? LID_MIN_SCALE;
  document.getElementById("lidThickv").textContent = Number(thick.value).toFixed(2);

  const doSoft = document.getElementById("doSoftMorph");
  const softStrength = document.getElementById("softStrength");
  const softHoriz = document.getElementById("softHoriz");
  const softVert = document.getElementById("softVert");
  const softMeta = document.getElementById("softMeta");
  if (hasSoftRegion) {
    doSoft.checked = !!softSpec.enabled;
    doSoft.disabled = false;
    softStrength.value = softSpec.strength ?? 0;
    softHoriz.value = softSpec.horizontal_px ?? 0;
    softVert.value = softSpec.vertical_px ?? 0;
    const reasons = softSpec.status_reasons || [];
    softMeta.innerHTML = `<div>status <b>${softSpec.status}</b> &middot; `
      + `confidence ${(softSpec.confidence ?? 0).toFixed(2)}</div>`
      + (reasons.length ? `<div class="warn">${reasons.join(", ")}</div>` : "");
  } else {
    doSoft.checked = false;
    doSoft.disabled = true;
    const reasons = (softSpec && softSpec.status_reasons) || ["no_topwear"];
    softMeta.textContent = softSpec ? `disabled: ${reasons.join(", ")}` : "not available in this run";
  }
  document.getElementById("softStrengthv").textContent = Number(softStrength.value).toFixed(2);
  document.getElementById("softHorizv").textContent = Number(softHoriz.value).toFixed(1) + "px";
  document.getElementById("softVertv").textContent = Number(softVert.value).toFixed(1) + "px";

  renderPanel();
  requestAnimationFrame(frame);
}

export function renderPanel() {
  const m = state.manifest;
  const anchors = Object.keys(m.anchors || {});
  const verts = state.parts.reduce((n, p) => n + p.mesh.rest.length / 2, 0);
  document.getElementById("runmeta").innerHTML =
    `<div>run <b>${m.source.run_id || "(unnamed)"}</b> &middot; ${m.source.tag_version || "?"}</div>` +
    `<div>depth source: <b>${m.source.depth}</b></div>` +
    `<div>${m.parts.length} parts &middot; ${verts} vertices</div>` +
    `<div>anchors: ${anchors.join(", ") || "<span class='warn'>none</span>"}</div>` +
    (anchors.includes("neck_pivot") ? "" :
      "<div class='warn'>no neck_pivot: tilt disabled</div>");

  const pack = state.parts.filter((p) => p.expression);
  document.getElementById("packmeta").innerHTML = pack.length
    ? pack.map((p) => `<div>${p.spec.name} &rarr; ${p.expression.replaces.join(", ") || "(unplaced)"}</div>`).join("")
    : "no pack in this run";

  const host = document.getElementById("parts");
  host.innerHTML = "";
  for (const p of state.parts) {
    const row = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = true;
    cb.addEventListener("change", () => { p.visible = cb.checked; });
    const z = document.createElement("span");
    z.className = "z"; z.textContent = p.spec.z;
    const name = document.createElement("span");
    name.textContent = `${p.spec.tag} (${p.spec.group})`;
    row.append(cb, z, name);
    host.appendChild(row);
  }
}

/** `Show region` debug overlay (design doc 18): the two derived ellipses plus
 *  the neckline/center lock lines, drawn on a plain 2D canvas stacked over
 *  the WebGL one so the geometry can be checked without touching the render
 *  path. No-ops when the checkbox is off or this run has no region. */
export function drawSoftRegionOverlay() {
  const ctx = document.getElementById("regionOverlay").getContext("2d");
  ctx.clearRect(0, 0, state.canvasW, state.canvasH);
  if (!document.getElementById("softRegion").checked) return;
  const spec = (state.manifest.motion || {}).upper_torso_soft_morph;
  const topwear = state.parts.find((p) => p.spec.tag === SOFT_MORPH_TAG);
  if (!spec || !spec.left || !spec.right || !topwear) return;

  const [x1, y1, x2, y2] = topwear.spec.xyxy;
  const width = x2 - x1, height = y2 - y1;
  const drawLobe = (lobe, color) => {
    const cx = x1 + lobe.center[0] * width, cy = y1 + lobe.center[1] * height;
    const rx = lobe.radius[0] * width, ry = lobe.radius[1] * height;
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1, width * 0.006);
    ctx.stroke();
  };
  drawLobe(spec.left, "rgba(110,168,254,0.9)");
  drawLobe(spec.right, "rgba(254,168,110,0.9)");

  const neckY = y1 + height * spec.neckline_lock;
  ctx.strokeStyle = "rgba(255,255,255,0.5)";
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x1, neckY); ctx.lineTo(x2, neckY); ctx.stroke();

  const centerX = (x1 + x2) / 2, half = spec.center_lock * width;
  ctx.strokeStyle = "rgba(255,255,255,0.35)";
  ctx.beginPath(); ctx.moveTo(centerX - half, y1); ctx.lineTo(centerX - half, y2); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(centerX + half, y1); ctx.lineTo(centerX + half, y2); ctx.stroke();
}

/* ---------- animation ---------- */

export function scheduleBlink(now) {
  const cfg = state.manifest.motion.blink;
  const [lo, hi] = cfg.interval_s;
  state.blinkTimer = now + (lo + Math.random() * (hi - lo)) * 1000;
}

export function startBlink(now, sides) {
  const cfg = state.manifest.motion.blink;
  state.blinkPhase = {
    start: now, sides,
    close: cfg.close_s * 1000, hold: cfg.hold_s * 1000, open: cfg.open_s * 1000,
  };
}

export function blinkAmount(now) {
  const ph = state.blinkPhase;
  if (!ph) return { l: 0, r: 0 };
  const dt = now - ph.start;
  let a;
  if (dt < ph.close) a = dt / ph.close;
  else if (dt < ph.close + ph.hold) a = 1;
  else if (dt < ph.close + ph.hold + ph.open) a = 1 - (dt - ph.close - ph.hold) / ph.open;
  else { state.blinkPhase = null; return { l: 0, r: 0 }; }
  return { l: ph.sides.includes("l") ? a : 0, r: ph.sides.includes("r") ? a : 0 };
}

/** How opaque a part is this frame. Only the expression pack moves this: with
 *  no pack every part draws at 1, which is the v0.1 rig. */
export function opacityOf(part, motion) {
  let alpha = Number(part.spec?.authored_visibility ?? part.spec?.visibility ?? 1);
  if (part.spec && part.spec.variant_set) {
    const setId = part.spec.variant_set;
    const spec = state.variantSets[setId];
    const member = part.spec.variant_member;
    const fade = state.variantFades[setId];
    if (fade && spec) {
      const amount = Math.max(0, Math.min(1, (motion.now - fade.start) / fade.duration));
      if (amount >= 1) alpha *= member === fade.to ? 1 : 0;
      else if (member === fade.from) alpha *= 1 - amount;
      else if (member === fade.to) alpha *= amount;
      else alpha = 0;
    } else {
      alpha *= spec && state.variantSelections[setId] === member ? 1 : 0;
    }
  }
  if (motion.swap && part.expression) {
    const key = part.expression.kind === "mouth" ? "mouth" : part.expression.side;
    alpha *= motion.swap[key] ? motion.swap[key].art : 0;
  } else if (motion.swap && part.replacedBy) {
    alpha *= motion.swap[part.replacedBy].base;
  }
  if (!Number.isFinite(alpha)) alpha = 0;
  return Math.max(0, Math.min(1, alpha * visibilityCurveAlpha(part, motion)));
}

/** Weight overrides for the H2/H3 experiments. `motion.overrides` is read once
 *  per frame -- doing a DOM lookup per vertex costs more than the deformation. */
export function effectiveWeight(part, i, overrides) {
  if (overrides.ghost && part.spec.tag === "head_remainder") return 0.16;
  if (part.spec.group === "neck") {
    if (overrides.neck === "rigid") return 1.0;
    if (overrides.neck === "detached") return 0.0;
  }
  if (part.isCollar && overrides.collar != null) {   // loose: also skips undefined
    const bottom = part.spec.weight.bottom;
    return bottom + part.mesh.ramp[i] * (overrides.collar - bottom);
  }
  return part.mesh.weight[i];
}

function gazeTarget(part) {
  const tag = part.spec.tag;
  if (tag === "iridesl" || tag === "iridesr") return tag.endsWith("l") ? "l" : "r";
  if (tag === "eyel" || tag === "eyer") return tag.endsWith("l") ? "l" : "r";
  if (tag === "irides" || tag === "eyes") return "both";
  return null;
}

function gazeDelta(part, motion) {
  const target = gazeTarget(part);
  if (!target || !motion.gaze) return [0, 0];
  const cfg = motion.gaze;
  const x = Math.max(-1, Math.min(1, parameterValue("ParamEyeBallX", motion)));
  const y = Math.max(-1, Math.min(1, parameterValue("ParamEyeBallY", motion)));
  const anchor = target === "r" ? state.manifest.anchors?.eye_right
    : state.manifest.anchors?.eye_left;
  const box = anchor ? (target === "r" ? state.eyeOpening?.r : state.eyeOpening?.l) : null;
  const width = box ? Math.max(1, box[2] - box[0]) : Math.max(1, part.spec.xyxy[2] - part.spec.xyxy[0]);
  const height = box ? Math.max(1, box[3] - box[1]) : Math.max(1, part.spec.xyxy[3] - part.spec.xyxy[1]);
  let dx = x * Number(cfg.max_x ?? 0.22) * width;
  let dy = y * Number(cfg.max_y ?? 0.14) * height;
  const margin = Math.max(0, Math.min(0.45, Number(cfg.safe_margin ?? 0.08)));
  const limitX = width * Math.max(0, 0.5 - margin);
  const limitY = height * Math.max(0, 0.5 - margin);
  dx = Math.max(-limitX, Math.min(limitX, dx));
  dy = Math.max(-limitY, Math.min(limitY, dy));
  return [dx, dy];
}

export function deform(part, now, motion) {
  const { rest, live } = part.mesh;
  const anchors = state.manifest.anchors || {};
  const pivot = anchors.neck_pivot;
  const span = Math.max(state.canvasW, state.canvasH);
  const parallax = span * (TURN_BASE + TURN_SPAN * (1 - part.spec.depth));
  const tilt = pivot ? motion.tiltRad : 0;
  const primaryEnabled = phaseEnabled("primary");
  const secondaryEnabled = phaseEnabled("secondary");
  // How far the *drawn* eye closes. With an expression pack this is held at
  // the swap point instead of going to 1: past there the art owns the eye, and
  // squashing a layer that is fading out only adds a second motion under it.
  const squash = motion.squash || motion.blink;
  const blink = part.eyeSide === "l" ? squash.l
              : part.eyeSide === "r" ? squash.r
              : Math.max(squash.l, squash.r);

  for (let i = 0, v = 0; v < rest.length; i++, v += 2) {
    let x = rest[v], y = rest[v + 1];
    const w = effectiveWeight(part, i, motion.overrides);

    // Eyes close toward their own centre line before anything moves them, so
    // the lid stays put while the head turns.
    if (primaryEnabled && part.isEye && blink > 0) {
      const floor = part.isLid ? motion.lidThickness : 0;
      const lid = part.openTop + motion.lidRatio * (part.openBottom - part.openTop);
      y = lid + (y - lid) * (1 - blink * (1 - floor));
    }

    // Gaze is deliberately restricted to iris/coarse-eye targets.  The eye
    // white and lash never inherit this offset, so head turn and blink remain
    // responsible for their own motion.
    const gaze = gazeDelta(part, motion);
    if (primaryEnabled && (gaze[0] !== 0 || gaze[1] !== 0)) {
      x += gaze[0];
      y += gaze[1];
    }

    // Depth-differential parallax: near parts travel further than far ones.
    let dx = primaryEnabled ? motion.turnX * parallax : 0;
    let dy = primaryEnabled ? motion.turnY * parallax * TURN_Y_SCALE : 0;
    // ... blended toward the shell rotation (H6). The head-follow weight scales
    // the blended result, not just the parallax, so the neck's gradient still
    // governs both paths and the two seams stay continuous either way.
    if (primaryEnabled && motion.shell > 0 && part.shell) {
      const d = shellDelta(part.shell, x, y, motion.yaw, motion.pitch);
      dx += motion.shell * (d[0] - dx);
      dy += motion.shell * (d[1] - dy);
    }
    x += dx * w;
    y += dy * w;

    // Tilt about the neck pivot, scaled by the same weight, which is what
    // keeps the bottom of the neck attached to the torso.
    if (primaryEnabled && tilt !== 0 && w !== 0) {
      const a = tilt * w, cos = Math.cos(a), sin = Math.sin(a);
      const dx = x - pivot[0], dy = y - pivot[1];
      x = pivot[0] + dx * cos - dy * sin;
      y = pivot[1] + dx * sin + dy * cos;
    }

    // Breathing is one continuous displacement field over y, not a per-group
    // formula. Giving the head a translation and the torso a scale meant the
    // two disagreed at the collar and the neck visibly stretched: everything
    // above the chest has to rise by the *same* amount the chest top rises.
    if (primaryEnabled && motion.breath !== 0) {
      const ramp = breathRamp(y);
      if (ramp > 0) {
        y -= motion.breath * motion.breathAmp * ramp;
        if (part.spec.group === "body" && motion.chestX !== 0) {
          // A ribcage widens as well as rises; without it the torso reads as
          // bobbing rather than breathing.
          x = state.chestCx + (x - state.chestCx) * (1 + motion.breath * motion.chestX * ramp);
        }
      }
    }

    // Chest soft morph: a small local volume response layered on top of the
    // global breathing field above, confined to `topwear` alone. `wl`/`wr`
    // already carry the neckline/center locks baked in, so this is a plain
    // additive push -- outward for whichever lobe a vertex belongs to, and a
    // little downward bias so the effect reads as cloth settling rather than
    // sliding sideways in a straight line.
    if (secondaryEnabled && part.softMorph && motion.softMorph.enabled) {
      const sm = motion.softMorph;
      const amount = sm.strength * sm.morph;
      if (amount !== 0) {
        const wl = part.softMorph.left[i], wr = part.softMorph.right[i];
        if (wl > 0 || wr > 0) {
          x += sm.horizontalPx * amount * (wr - wl);
          y += sm.verticalPx * amount * Math.max(wl, wr) * part.softMorph.lowerBias[i];
        }
      }
    }

    live[v] = x; live[v + 1] = y;
  }
}

export function frame(now) {
  const gl = state.gl, loc = state.loc;
  const t = (now - state.t0) / 1000;
  const dt = Math.min(0.1, (now - (state.lastFrame || now)) / 1000);
  state.lastFrame = now;
  if (document.getElementById("autoIdle").checked) {
    // Two incommensurable periods so the loop never visibly repeats, and the
    // turn held well inside where it starts to cost something.
    const turn = state.manifest.motion.head_turn;
    const limit = Math.min(turn.max_x, IDLE_TURN);
    setSlider("turnX", (Math.sin(t * 0.37) * 0.73 + Math.sin(t * 0.13) * 0.27) * limit);
    setSlider("turnY", Math.sin(t * 0.29 + 1.1) * 0.45 * Math.min(turn.max_y, IDLE_TURN));
    setSlider("tilt", Math.sin(t * 0.23 + 0.6) * state.manifest.motion.head_tilt.max_deg);
  }

  if (document.getElementById("doBlink").checked) {
    if (!state.blinkTimer) scheduleBlink(now);
    if (!state.blinkPhase && now >= state.blinkTimer) {
      startBlink(now, ["l", "r"]);
      scheduleBlink(now);
      // Occasionally blink twice in quick succession.
      if (Math.random() < 0.2) state.blinkTimer = now + 260;
    }
  }

  // Talk: a mouth that opens and closes on its own, only when the pack brought
  // a mouth to open. Irregular on purpose -- an even cycle reads as chewing.
  if (state.art.mouth && document.getElementById("doTalk").checked) {
    if (now >= state.talkUntil) {
      state.talkTarget = state.talkTarget > 0.5 ? 0 : 0.55 + Math.random() * 0.45;
      state.talkUntil = now + (state.talkTarget > 0.5 ? 90 + Math.random() * 110
                                                      : 70 + Math.random() * 160);
    }
    state.mouthOpen += (state.talkTarget - state.mouthOpen) * Math.min(1, dt * 18);
  } else {
    state.mouthOpen = parseFloat(document.getElementById("mouthOpen").value);
  }

  const useArt = document.getElementById("useArt").checked;
  const blink = blinkAmount(now);
  const swap = {
    l: expressionSwap(blink.l, useArt && !!state.art.l),
    r: expressionSwap(blink.r, useArt && !!state.art.r),
    mouth: expressionSwap(state.mouthOpen, useArt && !!state.art.mouth),
  };

  const breathSin = document.getElementById("doBreathe").checked
    ? Math.sin(t * 2 * Math.PI / state.manifest.motion.breathing.period_s) : 0;
  // Same signal as the global breathing field, reshaped so exhale moves less
  // than inhale (design doc 9) -- this is the one scalar chest soft morph
  // rides on, it never runs on a clock of its own.
  const softMorphAmount = Math.max(0, breathSin) + Math.min(0, breathSin) * SOFT_MORPH_DEFLATE_SCALE;

  const motion = {
    now,
    turnX: state.turnX, turnY: state.turnY,
    gazeX: parseFloat(document.getElementById("gazeX").value),
    gazeY: parseFloat(document.getElementById("gazeY").value),
    tiltRad: state.tiltDeg * Math.PI / 180,
    shell: state.shell,
    yaw: state.turnX * SHELL_MAX_YAW,
    // Negated: a positive turnY drops the face in the parallax path, and the
    // two paths have to agree on which way "down" is or the blend fights itself.
    pitch: -state.turnY * SHELL_MAX_PITCH,
    blink,
    mouthOpen: state.mouthOpen,
    squash: { l: swap.l.squash, r: swap.r.squash },
    swap,
    breath: breathSin,
    breathAmp: parseFloat(document.getElementById("breathAmp").value),
    lidRatio: parseFloat(document.getElementById("lidLine").value),
    lidThickness: parseFloat(document.getElementById("lidThick").value),
    chestX: CHEST_WIDEN,
    softMorph: {
      enabled: document.getElementById("doSoftMorph").checked,
      morph: softMorphAmount,
      strength: parseFloat(document.getElementById("softStrength").value),
      horizontalPx: parseFloat(document.getElementById("softHoriz").value),
      verticalPx: parseFloat(document.getElementById("softVert").value),
    },
    overrides: {
      ghost: document.getElementById("ghost").checked,
      neck: document.getElementById("neckMode").value,
      collar: state.collarOverride,
    },
  };

  // v0.2's manifest phase list is the runtime ordering contract.  The
  // deformation math below remains the legacy-compatible render backend, but
  // it is now reached only after every declared phase has been evaluated.
  evaluateAllPhases(now, { motion });

  gl.viewport(0, 0, state.canvasW, state.canvasH);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);

  const wire = document.getElementById("wire").checked;
  for (const p of state.parts) {
    if (!p.visible) continue;
    const opacity = opacityOf(p, motion);
    if (opacity <= 0.002) continue;
    deform(p, now, motion);

    gl.bindBuffer(gl.ARRAY_BUFFER, p.buf.pos);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, p.mesh.live);
    gl.enableVertexAttribArray(loc.pos);
    gl.vertexAttribPointer(loc.pos, 2, gl.FLOAT, false, 0, 0);

    gl.bindBuffer(gl.ARRAY_BUFFER, p.buf.uv);
    gl.enableVertexAttribArray(loc.uv);
    gl.vertexAttribPointer(loc.uv, 2, gl.FLOAT, false, 0, 0);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, p.tex);
    gl.uniform1i(loc.tex, 0);

    gl.uniform1f(loc.wire, 0);
    gl.uniform1f(loc.alpha, opacity);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, p.buf.idx);
    gl.drawElements(gl.TRIANGLES, p.mesh.count, gl.UNSIGNED_SHORT, 0);

    if (wire) {
      gl.uniform1f(loc.wire, 1);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, p.buf.wire);
      gl.drawElements(gl.LINES, p.mesh.wireCount, gl.UNSIGNED_SHORT, 0);
    }
  }
  drawSoftRegionOverlay();
  requestAnimationFrame(frame);
}

/* ---------- controls ---------- */

export function setSlider(id, value) {
  const el = document.getElementById(id);
  el.value = value;
  syncSlider(id);
}

export function syncSlider(id) {
  const value = parseFloat(document.getElementById(id).value);
  if (id === "turnX") { state.turnX = value; document.getElementById("turnXv").textContent = value.toFixed(2); }
  if (id === "turnY") { state.turnY = value; document.getElementById("turnYv").textContent = value.toFixed(2); }
  if (id === "tilt") { state.tiltDeg = value; document.getElementById("tiltv").textContent = value.toFixed(1) + "°"; }
  if (id === "gazeX") { setParameter("ParamEyeBallX", value); document.getElementById("gazeXv").textContent = value.toFixed(2); }
  if (id === "gazeY") { setParameter("ParamEyeBallY", value); document.getElementById("gazeYv").textContent = value.toFixed(2); }
}

document.getElementById("gazeX").addEventListener("input", () => syncSlider("gazeX"));
document.getElementById("gazeY").addEventListener("input", () => syncSlider("gazeY"));

document.getElementById("mouthOpen").addEventListener("input", () => {
  document.getElementById("doTalk").checked = false;
  state.mouthOpen = parseFloat(document.getElementById("mouthOpen").value);
  document.getElementById("mouthOpenv").textContent = state.mouthOpen.toFixed(2);
});

document.getElementById("shell").addEventListener("input", () => {
  state.shell = parseFloat(document.getElementById("shell").value);
  document.getElementById("shellv").textContent = state.shell.toFixed(2);
});

for (const id of ["turnX", "turnY", "tilt"]) {
  document.getElementById(id).addEventListener("input", () => {
    document.getElementById("autoIdle").checked = false;
    syncSlider(id);
  });
}

document.getElementById("lidThick").addEventListener("input", () => {
  document.getElementById("lidThickv").textContent =
    parseFloat(document.getElementById("lidThick").value).toFixed(2);
});

document.getElementById("lidLine").addEventListener("input", () => {
  document.getElementById("lidLinev").textContent =
    parseFloat(document.getElementById("lidLine").value).toFixed(2);
});

document.getElementById("collar").addEventListener("input", () => {
  state.collarOverride = parseFloat(document.getElementById("collar").value);
  document.getElementById("collarv").textContent = state.collarOverride.toFixed(2);
});

document.getElementById("breathAmp").addEventListener("input", () => {
  document.getElementById("breathAmpv").textContent =
    parseFloat(document.getElementById("breathAmp").value).toFixed(1) + "px";
});

document.getElementById("softStrength").addEventListener("input", () => {
  document.getElementById("softStrengthv").textContent =
    parseFloat(document.getElementById("softStrength").value).toFixed(2);
});
document.getElementById("softHoriz").addEventListener("input", () => {
  document.getElementById("softHorizv").textContent =
    parseFloat(document.getElementById("softHoriz").value).toFixed(1) + "px";
});
document.getElementById("softVert").addEventListener("input", () => {
  document.getElementById("softVertv").textContent =
    parseFloat(document.getElementById("softVert").value).toFixed(1) + "px";
});

document.getElementById("blinkNow").addEventListener("click",
  () => startBlink(performance.now(), ["l", "r"]));
document.getElementById("winkL").addEventListener("click",
  () => startBlink(performance.now(), ["l"]));
document.getElementById("winkR").addEventListener("click",
  () => startBlink(performance.now(), ["r"]));
