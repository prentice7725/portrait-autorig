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

import { createStrandSpringDriver, createUpperTorsoSecondaryDriver } from "./physics.mjs";

export const PREVIEW_RUNTIME_VERSION = "P2.3";

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
export const SOFT_MORPH_TAG = "topwear";     // canonical torso semantic
export const SOFT_MORPH_TAGS = new Set(["topwear", "topwear_with_arms", "topwear_with_handwear"]);
const isSoftMorphTag = (tag) => SOFT_MORPH_TAGS.has(tag);
export const SOFT_MORPH_DEFLATE_SCALE = 0.35; // exhale moves less than inhale (design doc 9)
export const SOFT_MORPH_CENTER_TRANSITION = 0.15; // fraction of topwear width past center_lock
                                            // before the lock fully releases (design doc 8.2)
export const PHYSICS_MAX_CATCHUP_STEPS = 4;

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
function registerDeformerOperation(deformer, context) {
  (context.operations || (context.operations = [])).push({
    id: deformer.id, kind: deformer.kind, phase: deformer.phase,
    config: deformer.config || {}, parameters: deformer.parameters || [],
    targets: deformer.targets || {},
  });
}

export const PHASE_DEFORMER_HANDLERS = {
  parallax_turn(deformer, context) { registerDeformerOperation(deformer, context); },
  shell_turn(deformer, context) { registerDeformerOperation(deformer, context); },
  weighted_rotation(deformer, context) { registerDeformerOperation(deformer, context); },
  continuous_field(deformer, context) { registerDeformerOperation(deformer, context); },
  body_sway(deformer, context) {
    registerDeformerOperation(deformer, context);
    if (context.motion) context.motion.bodySway = deformer.config || {};
  },
  eye_fold(deformer, context) { registerDeformerOperation(deformer, context); },
  gaze(deformer, context) {
    registerDeformerOperation(deformer, context);
    if (context.motion && deformer.config) {
      context.motion.gaze = { ...(context.motion.gaze || {}), ...deformer.config };
    }
  },
  local_soft_field(deformer, context) { registerDeformerOperation(deformer, context); },
  strand_spring(deformer, context) { registerDeformerOperation(deformer, context); },
  upper_torso_physics(deformer, context) { registerDeformerOperation(deformer, context); },
  sprite_swap(deformer, context) {
    registerDeformerOperation(deformer, context);
    (context.visibility || (context.visibility = [])).push(deformer.id);
  },
  visibility_curve(deformer, context) {
    registerDeformerOperation(deformer, context);
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
varying vec2 v_pos;
void main() {
  vec2 clip = vec2(a_pos.x / u_canvas.x * 2.0 - 1.0,
                   1.0 - a_pos.y / u_canvas.y * 2.0);
  gl_Position = vec4(clip, 0.0, 1.0);
  v_uv = a_uv;
  v_pos = a_pos;
}`;

export const FRAG_SRC = `
precision mediump float;
uniform sampler2D u_tex;
uniform sampler2D u_mask;
uniform vec4 u_mask_box;
uniform float u_mask_enabled;
uniform float u_wire;
uniform float u_alpha;
varying vec2 v_uv;
varying vec2 v_pos;
void main() {
  // Premultiplied output throughout: the wire overlay's RGB is pre-scaled by
  // its own alpha, and a part fade scales every channel by u_alpha equally
  // (not just alpha) so the blend stays correctly premultiplied at any fade.
  if (u_wire > 0.5) { gl_FragColor = vec4(0.215, 0.33, 0.5, 0.5); return; }
  vec4 color = texture2D(u_tex, v_uv) * u_alpha;
  if (u_mask_enabled > 0.5) {
    vec2 maskSize = u_mask_box.zw - u_mask_box.xy;
    vec2 maskUv = (v_pos - u_mask_box.xy) / max(maskSize, vec2(1.0));
    if (maskUv.x < 0.0 || maskUv.x > 1.0 || maskUv.y < 0.0 || maskUv.y > 1.0) {
      color = vec4(0.0);
    } else {
      color *= texture2D(u_mask, maskUv).a;
    }
  }
  gl_FragColor = color;
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
  physicsDrivers: null,
  physicsOutputs: {},
  physicsAccumulator: 0,
  physicsLastNow: null,
  bodyMotion: { x: 0, y: 0, prevX: 0, prevY: 0, vx: 0, vy: 0,
                prevVx: 0, prevVy: 0, ax: 0, ay: 0 },
  bodySwayEnabled: false,
  physicsSimTime: 0,
  idleUiLast: -Infinity,
  overlayVisible: false,
  profiler: { fps: 0, physicsMs: 0, deformMs: 0, stitchMs: 0, uploadMs: 0,
              activeVertices: 0, totalVertices: 0, backlogDropped: 0, lastAt: -Infinity },
  motionQA: { inertia: true, inertiaOnly: false, asymmetry: 1, inertiaMultiplier: 1,
              settleMultiplier: 1, chestImpulseX: 0, chestImpulseY: 0 },
  bodyPulse: { x: 0, y: 0, vx: 0, vy: 0 },
  motionGraph: [],
  calibrationRequested: 0,
  shells: null,           // fitted in build(); null disables the shell path
  variantSets: {},
  variantSelections: {},
  variantFades: {},
  parameters: {},
  gazeTargets: [],
  eyeOpening: { l: null, r: null },
  phaseTrace: [],
  phaseDispatch: {},
  frameOperations: null,
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
function visibleVariantMembers(spec, selected) {
  const groupId = spec?.state_labels?.[selected];
  const grouped = groupId == null ? null : spec?.state_groups?.[groupId];
  return Array.isArray(grouped) ? new Set(grouped) : new Set([selected]);
}

// Composer owns feature state for Assembly inputs. Keep the lookup explicit
// and label-driven: a closed/open state is selected from state_labels and
// member_bindings, never guessed from a generated rig part name.
function variantSetForFeature(feature) {
  const needle = String(feature).toLowerCase();
  for (const [setId, spec] of Object.entries(state.variantSets || {})) {
    if (String(setId).toLowerCase().includes(needle)) return [setId, spec];
    const tags = Object.values(spec.member_bindings || {})
      .map((binding) => String(binding.tag || "").toLowerCase());
    if (tags.some((tag) => tag.includes(needle))) return [setId, spec];
  }
  return null;
}

function variantMemberForLabel(spec, label) {
  const labels = spec?.state_labels || {};
  const found = Object.entries(labels).find(([, value]) => value === label);
  return found ? found[0] : null;
}

function applyVariantLabel(feature, label) {
  const found = variantSetForFeature(feature);
  if (!found) return false;
  const [setId, spec] = found;
  const member = variantMemberForLabel(spec, label);
  if (!member || state.variantSelections[setId] === member) return false;
  applyVariantSet(setId, member, { transition: "discrete" });
  return true;
}

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
    const visible = visibleVariantMembers(spec, memberId);
    for (const id of spec.members) {
      byName.get(spec.member_bindings[id].part).visible = visible.has(id);
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
  // Constraints are deliberately kept out of the geometry deformer list:
  // they run in their declared phase and expose a separate, ordered backend
  // input.  A renderer may consume these records as a stencil (clip_mask) or
  // vertex relation (boundary_stitch) without making deform()'s operation
  // order carry constraint semantics.
  context.constraintOperations = (context.constraintOperations || []).concat(
    entries.map((d) => ({ id: d.id, kind: d.kind || "constraint", phase,
      source: d.source, targets: d.targets, groups: d.groups,
      config: d.config || {},
    })));
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
  context.operations = [];
  const phases = state.manifest?.evaluation?.phases || DEFAULT_EVALUATION_PHASES;
  for (const phase of phases) evaluatePhase(phase, now, context);
  // A pre-P0-B manifest has no declarative deformer list; retain its legacy
  // motion backend in that case.  Once deformers exist, this immutable list is
  // the only source of geometry operations for the frame.
  state.frameOperations = Array.isArray(state.manifest?.deformers)
    ? context.operations.slice() : null;
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
  const refinement = part.mesh.refinement;
  const axis = (start, end, baseCell, refineStart, refineEnd, refineCell) => {
    const count = Math.max(1, Math.round((end - start) / baseCell));
    const values = Array.from({ length: count + 1 }, (_, i) =>
      start + (end - start) * i / count);
    if (!(Number.isFinite(refineStart) && Number.isFinite(refineEnd)
          && refineEnd > refineStart && refineCell > 0)) return values;
    for (let value = Math.max(start, refineStart); value <= Math.min(end, refineEnd) + 1e-6;
         value += refineCell) values.push(value);
    values.push(Math.max(start, refineStart), Math.min(end, refineEnd));
    return [...new Set(values.map((value) => Number(value.toFixed(4))))].sort((a, b) => a - b);
  };
  const region = refinement?.region;
  const refineCell = Math.max(8, Number(refinement?.cell || 0));
  const xs = axis(x1, x2, cell, region?.[0], region?.[2], refineCell);
  const ys = axis(y1, y2, cell, region?.[1], region?.[3], refineCell);
  const cols = xs.length - 1, rows = ys.length - 1;
  const pts = [];
  for (let r = 0; r <= rows; r++) {
    for (let c = 0; c <= cols; c++) {
      const x = xs[c], y = ys[r];
      pts.push({ x, y, u: (x - x1) / Math.max(1, x2 - x1),
        v: (y - y1) / Math.max(1, y2 - y1) });
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
  const topwear = manifest.parts.find((p) => isSoftMorphTag(p.tag));
  if (!topwear) return [];
  return manifest.parts
    .filter((p) => !isSoftMorphTag(p.tag) && p.z > topwear.z
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
  // AutoRig-derived regions are normalized to the cropped part. Composer's
  // authored RigIntent is normalized to its target instance (canvas-sized in
  // the Assembly contract). Never reinterpret authored coordinates against
  // the cropped alpha bbox: doing so moves A002's chest lobes down and inward.
  const canvasSpace = spec.coordinate_space === "canvas_normalized";
  const bx1 = canvasSpace ? 0 : x1;
  const by1 = canvasSpace ? 0 : y1;
  const bw = canvasSpace ? state.canvasW : width;
  const bh = canvasSpace ? state.canvasH : height;
  const centerX = bx1 + bw / 2;
  const neckLockBottom = by1 + bh * spec.neckline_lock;
  const centerLockHalf = spec.center_lock * bw;
  const centerLockOuter = centerLockHalf + SOFT_MORPH_CENTER_TRANSITION * bw;

  const lobeGeom = (lobe) => ({
    cx: bx1 + lobe.center[0] * bw, cy: by1 + lobe.center[1] * bh,
    rx: Math.max(1e-6, lobe.radius[0] * bw), ry: Math.max(1e-6, lobe.radius[1] * bh),
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
    let lock = smoothstep(by1, neckLockBottom, y) * smoothstep(centerLockHalf, centerLockOuter, Math.abs(x - centerX));
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
      mask: gl.getUniformLocation(prog, "u_mask"),
      maskBox: gl.getUniformLocation(prog, "u_mask_box"),
      maskEnabled: gl.getUniformLocation(prog, "u_mask_enabled"),
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

  const bodySway = (byKind.body_sway || [])[0];
  if (bodySway) motion.body_sway = bodySway.config || {};

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
  state.frameOperations = null;
  state.physicsDrivers = null;
  state.physicsOutputs = {};
  state.physicsAccumulator = 0;
  state.physicsLastNow = null;
  state.bodySwayEnabled = false;
  state.physicsSimTime = 0;
  state.bodyPulse = { x: 0, y: 0, vx: 0, vy: 0 };
  state.motionGraph = [];
  state.calibrationRequested = 0;
  const physicsSpec = manifest.physics || null;
  if (physicsSpec) {
    const config = physicsSpec.config || {};
    state.physicsDrivers = {};
    const strandSpec = physicsSpec.strand_driver;
    if (strandSpec?.enabled !== false && Array.isArray(strandSpec?.strands) && strandSpec.strands.length) {
      state.physicsDrivers.strand = createStrandSpringDriver(strandSpec.strands, {
        stiffness: strandSpec.stiffness, damping: strandSpec.damping,
        mass: strandSpec.mass, input_mode: strandSpec.input_mode || "translation", config,
      });
    }
    const torsoSpec = physicsSpec.upper_torso_driver;
    if (torsoSpec?.enabled !== false && torsoSpec) {
      state.physicsDrivers.torso = createUpperTorsoSecondaryDriver({
        model: torsoSpec.model || "legacy_target_v1",
        profile: torsoSpec.profile || "soft",
        translationGain: torsoSpec.translation_gain ?? 1,
        angleGain: torsoSpec.angle_gain ?? 0.25,
        turnAsymmetry: torsoSpec.turn_asymmetry ?? 0.08,
        velocityGain: torsoSpec.velocity_gain ?? 0.03,
        accelerationGain: torsoSpec.acceleration_gain ?? 0.005,
        breathGain: torsoSpec.breath_gain ?? 1,
        poseBiasGain: torsoSpec.pose_bias_gain ?? 0.05,
        inertiaGainX: torsoSpec.inertia_gain_x ?? 0.015,
        inertiaGainY: torsoSpec.inertia_gain_y ?? 0.045,
        velocityDragX: torsoSpec.velocity_drag_x ?? 0.002,
        velocityDragY: torsoSpec.velocity_drag_y ?? 0.006,
        settleGain: torsoSpec.settle_gain ?? 0.08,
        leftMaterialScale: torsoSpec.left_material_scale || {},
        rightMaterialScale: torsoSpec.right_material_scale || {},
        breathDisplacementPx: torsoSpec.breath_displacement_px ?? 0.8,
        poseBiasPx: torsoSpec.pose_bias_px ?? 0.15,
        inertiaCouplingX: torsoSpec.inertia_coupling_x ?? 0.08,
        inertiaCouplingY: torsoSpec.inertia_coupling_y ?? 0.22,
        dragCouplingX: torsoSpec.drag_coupling_x ?? 0.01,
        dragCouplingY: torsoSpec.drag_coupling_y ?? 0.02,
        naturalFrequencyHz: torsoSpec.natural_frequency_hz,
        dampingRatio: torsoSpec.damping_ratio,
        maxDisplacementPx: torsoSpec.max_displacement_px ?? 4,
        maxVelocityPxS: torsoSpec.max_velocity_px_s ?? 24,
        settleTimeScaleS: torsoSpec.settle_time_scale_s ?? 0.03,
        inputMode: torsoSpec.input_mode || "translation",
        config,
      });
    }
    resetPhysics();
  }
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
  const opening = manifest.eye_opening || {};
  for (const suffix of ["l", "r", ""]) {
    if (opening[suffix]) continue;
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
    // Composer may keep both eyes in one unsuffixed sprite.  Its overall
    // bbox can span the whole face, so use the eye-anchor midpoint to derive
    // independent opening bounds for each half instead of folding both eyes
    // toward the sprite's global bottom edge.
    let eyeOpenings = null;
    if (isEye && !side) {
      eyeOpenings = { l: opening.l || null, r: opening.r || null };
    }
    if (isEye && !side && anchors.eye_left && anchors.eye_right
        && (!eyeOpenings?.l || !eyeOpenings?.r)) {
      const midpoint = (anchors.eye_left[0] + anchors.eye_right[0]) / 2;
      const halves = { l: [Infinity, Infinity, -Infinity, -Infinity],
                       r: [Infinity, Infinity, -Infinity, -Infinity] };
      for (let i = 0; i < mesh.rest.length; i += 2) {
        const half = mesh.rest[i] < midpoint ? halves.l : halves.r;
        half[0] = Math.min(half[0], mesh.rest[i]);
        half[1] = Math.min(half[1], mesh.rest[i + 1]);
        half[2] = Math.max(half[2], mesh.rest[i]);
        half[3] = Math.max(half[3], mesh.rest[i + 1]);
      }
      eyeOpenings = eyeOpenings || {};
      for (const [key, half] of Object.entries(halves)) {
        if (!eyeOpenings[key]) eyeOpenings[key] = Number.isFinite(half[0]) ? half : null;
      }
    }
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
      eyeOpenings,
      eyeCenterY: eyeAnchor ? eyeAnchor[1] : (part.xyxy[1] + part.xyxy[3]) / 2,
      openTop: box[1],
      openBottom: box[3],
      // Phase 1 scope (design doc 5): only `topwear` deforms.
      softMorph: (hasSoftRegion && isSoftMorphTag(part.tag))
        ? buildSoftMorphWeights(part, mesh, softSpec, chestOccluders) : null,
    };
  });

  state.variantSets = manifest.variant_sets || {};
  state.variantSelections = {};
  state.variantFades = {};
  state.clipMasks = [];
  for (const constraint of (manifest.constraints || [])) {
    if (constraint.kind !== "clip_mask") continue;
    state.clipMasks.push({ source: constraint.source,
      targets: Array.isArray(constraint.targets) ? constraint.targets.slice() : [] });
  }
  for (const part of state.parts) {
    const relation = state.clipMasks.find((mask) =>
      mask.targets.includes(part.spec.name) || mask.targets.includes(part.spec.tag));
    if (!relation) continue;
    part.clipMaskSource = state.parts.find((candidate) =>
      candidate.spec.name === relation.source || candidate.spec.tag === relation.source) || null;
  }
  for (const [setId, spec] of Object.entries(state.variantSets)) {
    state.variantSelections[setId] = spec.default;
    // The manifest marks the default member visible; enforce it here too so
    // old runtimes loading a hand-edited manifest cannot show two members.
    const visible = visibleVariantMembers(spec, spec.default);
    for (const member of spec.members || []) {
      const partName = spec.member_bindings?.[member]?.part;
      const part = state.parts.find((p) => p.spec.name === partName);
      if (part) part.visible = visible.has(member);
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

export function resetPhysics() {
  state.physicsAccumulator = 0;
  state.physicsLastNow = null;
  state.physicsSimTime = 0;
  state.bodyMotion = { x: 0, y: 0, prevX: 0, prevY: 0, vx: 0, vy: 0,
    prevVx: 0, prevVy: 0, ax: 0, ay: 0 };
  state.bodyPulse = { x: 0, y: 0, vx: 0, vy: 0 };
  state.motionGraph = [];
  state.calibrationRequested = 0;
  if (!state.physicsDrivers) return {};
  state.physicsOutputs = {};
  for (const [name, driver] of Object.entries(state.physicsDrivers)) {
    state.physicsOutputs[name] = driver.resetPhysics();
  }
  return state.physicsOutputs;
}

export function warmupPhysics(seconds, inputs = {}) {
  state.physicsLastNow = null;
  state.physicsAccumulator = 0;
  state.physicsSimTime = 0;
  state.bodyMotion = { x: 0, y: 0, prevX: 0, prevY: 0, vx: 0, vy: 0,
    prevVx: 0, prevVy: 0, ax: 0, ay: 0 };
  state.bodyPulse = { x: 0, y: 0, vx: 0, vy: 0 };
  state.motionGraph = [];
  if (!state.physicsDrivers) return {};
  for (const [name, driver] of Object.entries(state.physicsDrivers)) {
    state.physicsOutputs[name] = name === "torso"
      ? driver.warmupPhysics(seconds, inputs.breath || 0, inputs.angleY || 0)
      : driver.warmupPhysics(seconds, inputs.strandTarget || 0);
  }
  return state.physicsOutputs;
}

/** Deterministic capture hook: every preview/golden capture starts from rest. */
export function preparePhysicsCapture(seconds, inputs = {}) {
  resetPhysics();
  return warmupPhysics(seconds, inputs);
}

export function stepPhysicsFixed(count = 1, inputs = {}) {
  if (!state.physicsDrivers) return {};
  for (const [name, driver] of Object.entries(state.physicsDrivers)) {
    state.physicsOutputs[name] = name === "torso"
      ? driver.stepPhysicsFixed(count, inputs.breath || 0, inputs.angleY || 0,
          inputs.bodyVelocityY || inputs.bodyVelocity || 0,
          inputs.bodyAccelerationY || inputs.bodyAcceleration || 0,
          inputs.bodyVelocityX || 0, inputs.bodyAccelerationX || 0,
          inputs.impulseY || 0, inputs.impulseX || 0)
      : driver.stepPhysicsFixed(count, inputs.strandTarget || 0);
  }
  return state.physicsOutputs;
}

export function advancePhysics(now, inputs) {
  if (!state.physicsDrivers) return {};
  const previousNow = state.physicsLastNow;
  const elapsed = previousNow == null ? 0 : Math.max(0, (now - previousNow) / 1000);
  state.physicsAccumulator += Math.max(0, Math.min(0.1, elapsed));
  state.physicsLastNow = now;
  const hz = Number((state.manifest.physics?.config || {}).update_hz || 60);
  const tick = 1 / Math.max(1, hz);
  // Drop an excessive backlog instead of turning one late frame into a
  // physics spiral. At 60Hz this still permits roughly 66ms of catch-up.
  const maxBacklog = tick * PHYSICS_MAX_CATCHUP_STEPS;
  if (state.physicsAccumulator > maxBacklog) {
    state.profiler.backlogDropped += 1;
    state.physicsAccumulator = maxBacklog;
  }
  let count = 0;
  while (state.physicsAccumulator + 1e-12 >= tick && count < PHYSICS_MAX_CATCHUP_STEPS) {
    state.physicsAccumulator = Math.max(0, state.physicsAccumulator - tick); count++;
  }
  const swaySpec = state.bodySwayEnabled ? (state.manifest.motion?.body_sway || {}) : { enabled: false };
  for (let i = 0; i < count; i++) {
    const body = state.bodyMotion;
    const pulse = state.bodyPulse;
    // QA body kicks are root motion pulses. The pulse is integrated here,
    // before derivatives are measured, so chest inertia observes the actual
    // body movement rather than receiving a direct chest-only impulse.
    pulse.vx += (-pulse.x * 18 - pulse.vx * 7) * tick;
    pulse.vy += (-pulse.y * 18 - pulse.vy * 7) * tick;
    pulse.x += pulse.vx * tick; pulse.y += pulse.vy * tick;
    const previousX = body.x, previousY = body.y;
    const previousVx = body.vx, previousVy = body.vy;
    const [swayX, swayY] = bodySwayPosition(state.physicsSimTime + tick, swaySpec);
    const x = swayX + pulse.x, y = swayY + pulse.y;
    body.prevX = previousX; body.prevY = previousY;
    body.prevVx = previousVx; body.prevVy = previousVy;
    body.x = x; body.y = y;
    body.vx = (x - previousX) / tick; body.vy = (y - previousY) / tick;
    body.ax = (body.vx - previousVx) / tick; body.ay = (body.vy - previousVy) / tick;
    state.physicsSimTime += tick;
    const qa = state.motionQA;
    const inertia = qa.inertia ? qa.inertiaMultiplier : 0;
    stepPhysicsFixed(1, { ...inputs,
      breath: inputs.breath * (qa.inertiaOnly ? 0 : 1),
      bodyVelocityX: body.vx * inertia, bodyVelocityY: body.vy * inertia,
      bodyAccelerationX: body.ax * inertia, bodyAccelerationY: body.ay * inertia,
      impulseX: qa.chestImpulseX * inertia, impulseY: qa.chestImpulseY * inertia,
    });
    qa.chestImpulseX *= 0.82; qa.chestImpulseY *= 0.82;
  }
  return state.physicsOutputs;
}

export function renderPanel() {
  const m = state.manifest;
  const anchors = Object.keys(m.anchors || {});
  const verts = state.parts.reduce((n, p) => n + p.mesh.rest.length / 2, 0);
  document.getElementById("runmeta").innerHTML =
    `<div>AutoRig Preview <b>${PREVIEW_RUNTIME_VERSION}</b></div>` +
    `<div>run <b>${m.source.run_id || "(unnamed)"}</b> &middot; ${m.source.tag_version || "?"}</div>` +
    `<div>physics: <b>${m.physics?.upper_torso_driver?.model || "legacy/none"}</b></div>` +
    `<div>depth source: <b>${m.source.depth}</b></div>` +
    `<div>${m.parts.length} parts &middot; ${verts} vertices</div>` +
    `<div>anchors: ${anchors.join(", ") || "<span class='warn'>none</span>"}</div>` +
    (anchors.includes("neck_pivot") ? "" :
      "<div class='warn'>no neck_pivot: tilt disabled</div>");
  const physicsWarning = document.getElementById("physicsWarning");
  if (physicsWarning) {
    const torsoPhysics = m.physics?.upper_torso_driver;
    const active = torsoPhysics && torsoPhysics.enabled !== false
      && torsoPhysics.model === "inertial_relative_v2";
    physicsWarning.hidden = !!active;
    physicsWarning.textContent = active ? ""
      : "⚠ P2.3 PHYSICS NOT ACTIVE — This Rig Bundle was built without "
        + "physics.upper_torso_driver. Rebuild the Rig Bundle.";
  }

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
  const canvas = document.getElementById("regionOverlay");
  const enabled = !!document.getElementById("softRegion").checked;
  // Avoid a full overlay-canvas clear on every frame when the debug toggle is
  // off. Clear once on the transition so disabling the overlay never leaves a
  // stale outline behind.
  if (!enabled) {
    if (state.overlayVisible) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, state.canvasW, state.canvasH);
      state.overlayVisible = false;
    }
    return;
  }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, state.canvasW, state.canvasH);
  const spec = (state.manifest.motion || {}).upper_torso_soft_morph;
  const topwear = state.parts.find((p) => isSoftMorphTag(p.spec.tag));
  if (!spec || !spec.left || !spec.right || !topwear) {
    state.overlayVisible = false;
    return;
  }
  state.overlayVisible = true;

  const [x1, y1, x2, y2] = topwear.spec.xyxy;
  const local = spec.coordinate_space !== "canvas_normalized";
  const bx = local ? x1 : 0, by = local ? y1 : 0;
  const width = local ? x2 - x1 : state.canvasW;
  const height = local ? y2 - y1 : state.canvasH;
  const drawLobe = (lobe, color) => {
    const cx = bx + lobe.center[0] * width, cy = by + lobe.center[1] * height;
    const rx = lobe.radius[0] * width, ry = lobe.radius[1] * height;
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1, width * 0.006);
    ctx.stroke();
  };
  drawLobe(spec.left, "rgba(110,168,254,0.9)");
  drawLobe(spec.right, "rgba(254,168,110,0.9)");

  const neckY = by + height * spec.neckline_lock;
  ctx.strokeStyle = "rgba(255,255,255,0.5)";
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(bx, neckY); ctx.lineTo(bx + width, neckY); ctx.stroke();

  const centerX = bx + width / 2, half = spec.center_lock * width;
  ctx.strokeStyle = "rgba(255,255,255,0.35)";
  ctx.beginPath(); ctx.moveTo(centerX - half, by); ctx.lineTo(centerX - half, by + height); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(centerX + half, by); ctx.lineTo(centerX + half, by + height); ctx.stroke();
}

/* ---------- animation ---------- */

function updateIdleControls(now) {
  if (now - state.idleUiLast < 100) return;
  state.idleUiLast = now;
  // UI writes are intentionally throttled. The animation state is updated at
  // render rate below; only the human-facing slider/label is sampled at 10Hz.
  for (const [id, value, digits] of [["turnX", state.turnX, 2],
                                     ["turnY", state.turnY, 2],
                                     ["tilt", state.tiltDeg, 1]]) {
    const slider = document.getElementById(id);
    if (slider) slider.value = value;
    const label = document.getElementById(`${id}v`);
    if (label) label.textContent = Number(value).toFixed(digits) + (id === "tilt" ? "°" : "");
  }
}

function updateProfiler(now, frameMs, activeVertices, totalVertices) {
  state.profiler.activeVertices = activeVertices;
  state.profiler.totalVertices = totalVertices;
  if (now - state.profiler.lastAt < 100) return;
  state.profiler.lastAt = now;
  state.profiler.fps = frameMs > 0 ? 1000 / frameMs : 0;
  const el = document.getElementById("profiler");
  if (!el) return;
  const p = state.profiler;
  el.textContent = `FPS ${p.fps.toFixed(0)} · physics ${p.physicsMs.toFixed(2)}ms · `
    + `deform ${p.deformMs.toFixed(2)}ms · stitch ${p.stitchMs.toFixed(2)}ms · `
    + `upload ${p.uploadMs.toFixed(2)}ms · vertices ${p.activeVertices}/${p.totalVertices}`
    + ` · backlog drops ${p.backlogDropped}`;
}

function drawMotionGraph() {
  const canvas = document.getElementById("motionGraph");
  if (!canvas?.getContext) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const history = state.motionGraph;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (history.length < 2) return;
  const values = history.flatMap((sample) => [sample.body, sample.left, sample.right]);
  const min = Math.min(-1, ...values), max = Math.max(1, ...values), span = max - min;
  const draw = (key, color) => {
    ctx.strokeStyle = color; ctx.beginPath();
    history.forEach((sample, index) => {
      const x = index * (canvas.width - 1) / (history.length - 1);
      const y = canvas.height - 1 - (sample[key] - min) / span * (canvas.height - 2);
      if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.stroke();
  };
  draw("body", "#8ec5ff"); draw("left", "#ffc27d"); draw("right", "#d8a2ff");
}

export function bodySwayPosition(seconds, spec = {}) {
  if (spec.enabled === false) return [0, 0];
  const ax = Number(spec.amplitude_x_px ?? 1.8), ay = Number(spec.amplitude_y_px ?? 1.2);
  const px = Math.max(0.1, Number(spec.period_x_s ?? 7.3));
  const py = Math.max(0.1, Number(spec.period_y_s ?? 5.9));
  const harmonic = Math.max(0, Math.min(0.45, Number(spec.secondary_harmonic ?? 0.18)));
  const wx = 2 * Math.PI / px, wy = 2 * Math.PI / py;
  const x = ax * ((1 - harmonic) * Math.sin(seconds * wx + Number(spec.phase_x ?? 0.4))
    + harmonic * Math.sin(seconds * wx * 1.37 + Number(spec.phase_x ?? 0.4) * 1.7));
  const y = ay * ((1 - harmonic) * Math.sin(seconds * wy + Number(spec.phase_y ?? 1.2))
    + harmonic * Math.sin(seconds * wy * 1.29 + Number(spec.phase_y ?? 1.2) * 1.6));
  return [x, y];
}

function bodySwayInfluence(part) {
  // Body sway is a root-level upper-body translation. Keeping one influence
  // across head/neck/body avoids introducing a seam at their attachment.
  return ["head", "neck", "body", "body_remainder", "hair"].includes(part.spec?.group) ? 1 : 0;
}

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
      const from = visibleVariantMembers(spec, fade.from);
      const to = visibleVariantMembers(spec, fade.to);
      if (amount >= 1) alpha *= to.has(member) ? 1 : 0;
      else if (from.has(member) && to.has(member)) alpha *= 1;
      else if (from.has(member)) alpha *= 1 - amount;
      else if (to.has(member)) alpha *= amount;
      else alpha = 0;
    } else {
      alpha *= spec && visibleVariantMembers(spec, state.variantSelections[setId]).has(member) ? 1 : 0;
    }
  }
  if (motion.swap && part.expression) {
    const key = part.expression.kind === "mouth" ? "mouth" : part.expression.side;
    alpha *= motion.swap[key] ? motion.swap[key].art : 0;
  } else if (motion.swap && part.replacedBy) {
    alpha *= motion.swap[part.replacedBy].base;
  }
  // A clip relation cannot invent a missing source.  If a declared source
  // part is unavailable or fully hidden, conservatively hide its targets;
  // when the source exists, pixel-level stencil ownership remains with the
  // renderer and the target keeps its authored opacity.
  for (const mask of (state.clipMasks || [])) {
    if (!mask.targets.includes(part.spec?.name) && !mask.targets.includes(part.spec?.tag)) continue;
    const source = state.parts.find((candidate) =>
      candidate.spec?.name === mask.source || candidate.spec?.tag === mask.source);
    if (!source || source.visible === false) { alpha = 0; break; }
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

function strandSpringDelta(part, vertexIndex, motion) {
  const specs = part.spec?.strand_topology?.specs;
  const outputs = motion.physics?.strand;
  if (!Array.isArray(specs) || !outputs) return 0;
  let delta = 0;
  for (const spec of specs) {
    const output = outputs[spec.strand_id];
    if (!output) continue;
    for (const column of spec.columns || []) {
      const weight = Number(column.weights?.[String(vertexIndex)] || 0);
      delta += weight * Number(output.value || 0);
    }
  }
  return delta;
}

function geometryOperations(part) {
  // Legacy manifests have no operation list.  Their canonical order is kept
  // as a compatibility adapter; declarative v0.2 manifests use the exact list
  // assembled by phase dispatch, in that order.
  const operations = state.frameOperations || [
    { kind: "eye_fold", phase: "primary" },
    { kind: "gaze", phase: "primary" },
    { kind: "parallax_turn", phase: "primary" },
    { kind: "shell_turn", phase: "primary" },
    { kind: "weighted_rotation", phase: "primary" },
    { kind: "continuous_field", phase: "primary" },
    { kind: "local_soft_field", phase: "secondary" },
  ];
  return operations.filter((operation) => {
    if (!phaseEnabled(operation.phase || "primary")) return false;
    const side = operation.targets?.side;
    // Composer Assembly variants can keep both eyes in one member image.
    // Such an unsuffixed eye part has no side, so a bilateral eye_fold must
    // still reach it; split l/r parts continue to honor their side filter.
    return operation.kind !== "eye_fold" || !side || part.eyeSide == null || side === part.eyeSide;
  });
}

export function deform(part, now, motion) {
  const { rest, live } = part.mesh;
  const anchors = state.manifest.anchors || {};
  const pivot = anchors.neck_pivot;
  const span = Math.max(state.canvasW, state.canvasH);
  const parallax = span * (TURN_BASE + TURN_SPAN * (1 - part.spec.depth));
  const tilt = pivot ? motion.tiltRad : 0;
  const operations = geometryOperations(part);
  // How far the *drawn* eye closes. With an expression pack this is held at
  // the swap point instead of going to 1: past there the art owns the eye.
  const squash = motion.squash || motion.blink;

  for (let i = 0, v = 0; v < rest.length; i++, v += 2) {
    let x = rest[v], y = rest[v + 1];
    // Unsuffixed eye sprites need per-vertex side selection.  A single
    // bilateral blink value would otherwise use the full sprite bbox and
    // collapse the eyes toward an unrelated face/body boundary.
    const eyeMidpoint = anchors.eye_left && anchors.eye_right
      ? (anchors.eye_left[0] + anchors.eye_right[0]) / 2 : null;
    const vertexSide = part.eyeSide || (part.isEye && eyeMidpoint != null
      ? (rest[v] < eyeMidpoint ? "l" : "r") : null);
    const blink = vertexSide === "l" ? squash.l
                : vertexSide === "r" ? squash.r
                : Math.max(squash.l, squash.r);
    const w = effectiveWeight(part, i, motion.overrides);
    let pendingDx = 0, pendingDy = 0;
    const flushDelta = () => {
      x += pendingDx * w; y += pendingDy * w;
      pendingDx = 0; pendingDy = 0;
    };

    for (const operation of operations) {
      switch (operation.kind) {
        case "body_sway": {
          const sway = motion.bodySwayPosition || motion.bodySway || [0, 0];
          const influence = bodySwayInfluence(part);
          if (influence) { x += Number(sway[0] || 0) * influence; y += Number(sway[1] || 0) * influence; }
          break;
        }
        case "eye_fold": {
          if (part.isEye && blink > 0) {
            const floor = part.isLid ? motion.lidThickness : 0;
            const opening = vertexSide && part.eyeOpenings?.[vertexSide]
              ? part.eyeOpenings[vertexSide] : null;
            const openTop = opening ? opening[1] : part.openTop;
            const openBottom = opening ? opening[3] : part.openBottom;
            const lid = openTop + motion.lidRatio * (openBottom - openTop);
            y = lid + (y - lid) * (1 - blink * (1 - floor));
          }
          break;
        }
        case "gaze": {
          const gaze = gazeDelta(part, motion);
          if (gaze[0] !== 0 || gaze[1] !== 0) { x += gaze[0]; y += gaze[1]; }
          break;
        }
        case "parallax_turn":
          pendingDx = motion.turnX * parallax;
          pendingDy = motion.turnY * parallax * TURN_Y_SCALE;
          break;
        case "shell_turn":
          if (motion.shell > 0 && part.shell) {
            const d = shellDelta(part.shell, x, y, motion.yaw, motion.pitch);
            pendingDx += motion.shell * (d[0] - pendingDx);
            pendingDy += motion.shell * (d[1] - pendingDy);
          }
          flushDelta();
          break;
        case "weighted_rotation":
          flushDelta();
          if (tilt !== 0 && w !== 0) {
            const a = tilt * w, cos = Math.cos(a), sin = Math.sin(a);
            const dx = x - pivot[0], dy = y - pivot[1];
            x = pivot[0] + dx * cos - dy * sin;
            y = pivot[1] + dx * sin + dy * cos;
          }
          break;
        case "continuous_field": {
          flushDelta();
          if (motion.breath !== 0) {
            const ramp = breathRamp(y);
            if (ramp > 0) {
              y -= motion.breath * motion.breathAmp * ramp;
              if (part.spec.group === "body" && motion.chestX !== 0) {
                x = state.chestCx + (x - state.chestCx) * (1 + motion.breath * motion.chestX * ramp);
              }
            }
          }
          break;
        }
        case "local_soft_field": {
          flushDelta();
          if (part.softMorph && motion.softMorph.enabled) {
            const sm = motion.softMorph;
            // P2 torso physics feeds the authored local field; it never adds
            // a second uniform topwear translation. This preserves lobe,
            // neckline, center, and occluder locks already encoded in weights.
            const torso = motion.physics?.torso;
            let leftPhysics = isSoftMorphTag(part.spec.tag)
              ? Number(torso?.left?.value ?? torso?.value ?? 0) : 0;
            let rightPhysics = isSoftMorphTag(part.spec.tag)
              ? Number(torso?.right?.value ?? torso?.value ?? 0) : 0;
            const qaAsym = Number(state.motionQA?.asymmetry ?? 1);
            const qaMean = (leftPhysics + rightPhysics) * 0.5;
            leftPhysics = qaMean + (leftPhysics - qaMean) * qaAsym;
            rightPhysics = qaMean + (rightPhysics - qaMean) * qaAsym;
            const leftVelocity = isSoftMorphTag(part.spec.tag)
              ? Number(torso?.left?.velocity ?? torso?.velocity ?? 0) : 0;
            const rightVelocity = isSoftMorphTag(part.spec.tag)
              ? Number(torso?.right?.velocity ?? torso?.velocity ?? 0) : 0;
            const settleGain = Number(torso?.settleGain ?? 0.08)
              * Number(state.motionQA?.settleMultiplier ?? 1);
            const baseAmount = sm.strength * sm.morph;
            const physicalPx = torso?.model === "inertial_relative_v2";
            const leftAmount = physicalPx ? baseAmount : baseAmount + leftPhysics;
            const rightAmount = physicalPx ? baseAmount : baseAmount + rightPhysics;
            if (leftAmount !== 0 || rightAmount !== 0
                || (physicalPx && (leftPhysics !== 0 || rightPhysics !== 0))) {
              const wl = part.softMorph.left[i], wr = part.softMorph.right[i];
              if (wl > 0 || wr > 0) {
                const lobeWeight = Math.max(wl, wr);
                const totalWeight = wl + wr;
                x += sm.horizontalPx * (rightAmount * wr - leftAmount * wl);
                if (physicalPx) {
                  const horizontalGain = Number(sm.physicsDistribution?.horizontal_gain ?? 0.45);
                  const verticalGain = Number(sm.physicsDistribution?.vertical_gain ?? 1);
                  x += horizontalGain * (rightPhysics * wr - leftPhysics * wl);
                  const qVolume = totalWeight > 0
                    ? (leftPhysics * wl + rightPhysics * wr) / totalWeight : 0;
                  const qVelocity = totalWeight > 0
                    ? (leftVelocity * wl + rightVelocity * wr) / totalWeight : 0;
                  y += (qVolume * verticalGain
                    + qVelocity * Number(torso?.settleTimeScaleS ?? 0.03))
                    * lobeWeight * Number(part.softMorph.lowerBias[i] ?? 0);
                }
                // Preserve the legacy max-weight result when both sides are
                // equal, while allowing independent lobe spring amplitudes.
                const weighted = totalWeight > 0
                  ? (leftAmount * wl + rightAmount * wr) / totalWeight : 0;
                const weightedVelocity = totalWeight > 0
                  ? (leftVelocity * wl + rightVelocity * wr) / totalWeight : 0;
                if (!physicalPx) {
                  y += sm.verticalPx * (weighted + weightedVelocity * settleGain)
                    * lobeWeight * part.softMorph.lowerBias[i];
                }
              }
            }
          }
          break;
        }
        case "strand_spring": {
          if (["front hair", "back hair", "hair_secondary", "hair"].includes(part.spec.tag)) {
            y += strandSpringDelta(part, i, motion);
          }
          break;
        }
        default:
          break;
      }
    }
    flushDelta();
    live[v] = x; live[v + 1] = y;
  }
}

/**
 * Pick stable QA probes from the compiled topwear geometry.  The probes are
 * derived from the authored soft-field weights rather than from a synthetic
 * vertex or a spring scalar: this is the same mesh/weight data that the
 * renderer deforms.  A primary probe is the weighted lobe-centre vertex, a
 * lower probe is the nearest lower lobe vertex, and the lock probe is the
 * closest vertex owned by neither lobe.
 */
export function selectChestProbes(part) {
  const rest = part?.mesh?.rest;
  const left = part?.softMorph?.left;
  const right = part?.softMorph?.right;
  const lowerBias = part?.softMorph?.lowerBias;
  if (!rest || !left || !right || rest.length < 2) return null;
  const count = rest.length / 2;
  const centroid = (weights) => {
    let x = 0, y = 0, total = 0;
    for (let i = 0; i < count; i++) {
      const w = Math.max(0, Number(weights[i] || 0));
      x += rest[i * 2] * w; y += rest[i * 2 + 1] * w; total += w;
    }
    return total > 0 ? [x / total, y / total] : null;
  };
  const centres = { left: centroid(left), right: centroid(right) };
  const pick = (weights, centre, lower = false) => {
    if (!centre) return null;
    let best = null;
    for (let i = 0; i < count; i++) {
      const w = Number(weights[i] || 0);
      if (!(w > 1e-5)) continue;
      const y = rest[i * 2 + 1];
      if (lower && y < centre[1]) continue;
      const distance = Math.hypot(rest[i * 2] - centre[0], y - centre[1]);
      const candidate = { index: i, distance, weight: w,
        lower: Number(lowerBias?.[i] || 0) };
      if (!best || candidate.distance < best.distance
          || (candidate.distance === best.distance && candidate.weight > best.weight)) best = candidate;
    }
    return best?.index ?? null;
  };
  const leftPrimary = pick(left, centres.left);
  const rightPrimary = pick(right, centres.right);
  const leftLower = pick(left, centres.left, true);
  const rightLower = pick(right, centres.right, true);
  const mid = centres.left && centres.right
    ? [(centres.left[0] + centres.right[0]) * 0.5, (centres.left[1] + centres.right[1]) * 0.5]
    : centres.left || centres.right;
  let lock = null, lockDistance = Infinity;
  if (mid) for (let i = 0; i < count; i++) {
    if (Number(left[i] || 0) > 1e-5 || Number(right[i] || 0) > 1e-5) continue;
    const distance = Math.hypot(rest[i * 2] - mid[0], rest[i * 2 + 1] - mid[1]);
    if (distance < lockDistance) { lockDistance = distance; lock = i; }
  }
  return { leftPrimary, rightPrimary, leftLower, rightLower, lock,
    centres, count };
}

export function measureProbeDisplacement(part, index) {
  if (!part?.mesh?.rest || !part?.mesh?.live || !Number.isInteger(index)
      || index < 0 || index * 2 + 1 >= part.mesh.rest.length) return 0;
  const x = index * 2;
  return Math.hypot(part.mesh.live[x] - part.mesh.rest[x],
    part.mesh.live[x + 1] - part.mesh.rest[x + 1]);
}

/** Apply declarative N-way seam relations after all parts have been deformed. */
export function applyBoundaryStitches(parts = state.parts,
                                      constraints = state.manifest?.constraints || []) {
  const byName = new Map(parts.map((part) => [part.spec?.name || part.name, part]));
  const dirty = new Set();
  for (const constraint of constraints) {
    if (constraint.kind !== "boundary_stitch") continue;
    const tolerance = Math.max(0, Number(constraint.tolerance_px ?? 0));
    for (const group of constraint.groups || []) {
      const members = (group.members || []).map((member) => ({
        member, part: byName.get(member.part),
      })).filter(({ member, part }) => part?.mesh?.live && Number.isInteger(member.vertex)
        && member.vertex >= 0 && member.vertex * 2 + 1 < part.mesh.live.length);
      if (members.length < 2) continue;
      const points = members.map(({ member, part }) => [
        part.mesh.live[member.vertex * 2], part.mesh.live[member.vertex * 2 + 1],
      ]);
      let maxDistance = 0;
      for (const point of points) for (const other of points) {
        maxDistance = Math.max(maxDistance, Math.hypot(point[0] - other[0], point[1] - other[1]));
      }
      if (maxDistance <= tolerance) continue;
      const weights = members.map(({ member }) => Math.max(0, Number(member.weight ?? 1)));
      const total = weights.reduce((sum, value) => sum + value, 0);
      if (!(total > 0)) continue;
      const target = [0, 0];
      points.forEach((point, index) => {
        target[0] += point[0] * weights[index] / total;
        target[1] += point[1] * weights[index] / total;
      });
      for (const { member, part } of members) {
        const xIndex = member.vertex * 2, yIndex = xIndex + 1;
        if (part.mesh.live[xIndex] !== target[0] || part.mesh.live[yIndex] !== target[1]) {
          part.mesh.live[xIndex] = target[0];
          part.mesh.live[yIndex] = target[1];
          dirty.add(part);
        }
      }
    }
  }
  return dirty;
}

function motionGeometryKey(motion) {
  const physics = motion.physics || {};
  const torso = physics.torso || {};
  const strand = Object.fromEntries(Object.entries(physics.strand || {})
    .map(([id, value]) => [id, value?.value ?? 0]));
  return JSON.stringify({
    turnX: motion.turnX, turnY: motion.turnY, tiltRad: motion.tiltRad,
    shell: motion.shell, blink: motion.blink, squash: motion.squash,
    mouthOpen: motion.mouthOpen, breath: motion.breath, breathAmp: motion.breathAmp,
    lidRatio: motion.lidRatio, lidThickness: motion.lidThickness, chestX: motion.chestX,
    softMorph: motion.softMorph, physics: {
      torso: [torso.value ?? 0, torso.left?.value ?? null, torso.right?.value ?? null],
      strand,
    }, bodySwayPosition: motion.bodySwayPosition, overrides: motion.overrides,
  });
}

export function frame(now) {
  const gl = state.gl, loc = state.loc;
  const frameStart = performance.now();
  const t = (now - state.t0) / 1000;
  const dt = Math.min(0.1, (now - (state.lastFrame || now)) / 1000);
  state.lastFrame = now;
  const autoIdle = !!document.getElementById("autoIdle")?.checked;
  state.bodySwayEnabled = !!document.getElementById("bodySway")?.checked && autoIdle;
  if (autoIdle) {
    // Two incommensurable periods so the loop never visibly repeats, and the
    // turn held well inside where it starts to cost something.
    const turn = state.manifest.motion.head_turn;
    const limit = Math.min(turn.max_x, IDLE_TURN);
    state.turnX = (Math.sin(t * 0.37) * 0.73 + Math.sin(t * 0.13) * 0.27) * limit;
    state.turnY = Math.sin(t * 0.29 + 1.1) * 0.45 * Math.min(turn.max_y, IDLE_TURN);
    state.tiltDeg = Math.sin(t * 0.23 + 0.6) * state.manifest.motion.head_tilt.max_deg;
    updateIdleControls(now);
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
  const mouthVariant = variantSetForFeature("mouth");
  if ((state.art.mouth || mouthVariant) && document.getElementById("doTalk").checked) {
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

  if (useArt) {
    // A Composer closed-eye donor is a real authored state, not a generated
    // eyelid. It takes ownership only after the same swap threshold used by
    // the legacy expression path. Unsuffixed bilateral donors are switched
    // only for a bilateral blink; a wink keeps the conservative geometry path.
    const eyeVariant = variantSetForFeature("eye");
    if (eyeVariant && blink.l >= SWAP_HI && blink.r >= SWAP_HI) {
      applyVariantLabel("eye", "closed");
    } else if (eyeVariant && blink.l === 0 && blink.r === 0) {
      applyVariantLabel("eye", "open");
    }
    if (mouthVariant && document.getElementById("doTalk").checked) {
      applyVariantLabel("mouth", state.mouthOpen >= SWAP_HI ? "open" : "closed");
    }
  }

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
    bodySway: state.manifest.motion.body_sway || {},
    bodySwayPosition: state.bodySwayEnabled
      ? bodySwayPosition(t, state.manifest.motion.body_sway || {}) : [0, 0],
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
      physicsDistribution: state.manifest.motion.upper_torso_soft_morph?.physics_distribution || {},
    },
    overrides: {
      ghost: document.getElementById("ghost").checked,
      neck: document.getElementById("neckMode").value,
      collar: state.collarOverride,
    },
  };
  const physicsStart = performance.now();
  motion.physics = advancePhysics(now, {
    breath: motion.breath,
    angleY: motion.turnY,
    strandTarget: motion.turnY,
  });
  // Once a fixed tick has run, use the measured root position (including any
  // QA body pulse) for the primary deformer. Before the first tick, retain the
  // render-time sway sample so opening a physics-enabled run does not snap.
  if (state.physicsDrivers && state.physicsLastNow != null)
    motion.bodySwayPosition = [state.bodyMotion.x, state.bodyMotion.y];
  state.profiler.physicsMs = performance.now() - physicsStart;

  // v0.2's manifest phase list is the runtime ordering contract.  The
  // deformation math below remains the legacy-compatible render backend, but
  // it is now reached only after every declared phase has been evaluated.
  evaluateAllPhases(now, { motion });

  gl.viewport(0, 0, state.canvasW, state.canvasH);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);

  const wire = document.getElementById("wire").checked;
  const geometryKey = motionGeometryKey(motion);
  const drawParts = [];
  let activeVertices = 0, totalVertices = 0;
  const deformStart = performance.now();
  for (const p of state.parts) {
    if (!p.visible) continue;
    const opacity = opacityOf(p, motion);
    if (opacity <= 0.002) continue;
    totalVertices += p.mesh.rest.length / 2;
    const partKey = `${geometryKey}|${opacity}`;
    p.dirty = p.lastDeformKey !== partKey;
    if (p.dirty) {
      deform(p, now, motion);
      p.lastDeformKey = partKey;
      activeVertices += p.mesh.rest.length / 2;
    }
    drawParts.push({ part: p, opacity });
  }
  state.profiler.deformMs = performance.now() - deformStart;
  const stitchStart = performance.now();
  const stitchDirty = applyBoundaryStitches(state.parts);
  state.profiler.stitchMs = performance.now() - stitchStart;
  for (const part of stitchDirty) { part.dirty = true; }
  // Calibration reports displacement of the compiled topwear probes, not the
  // torso spring scalar.  This keeps the UI honest when authored lobe weights
  // attenuate the physical output or a lock correctly remains stationary.
  const calibrationEl = document.getElementById("chestCalibration");
  if (calibrationEl && state.calibrationRequested) {
    const topwear = state.parts.find((part) => isSoftMorphTag(part.spec?.tag)
      && part.mesh?.rest && part.mesh?.live && part.softMorph);
    const probes = selectChestProbes(topwear);
    if (probes && probes.leftPrimary != null && probes.rightPrimary != null) {
      calibrationEl.textContent = `Requested: ${state.calibrationRequested.toFixed(2)}px · `
        + `Measured L: ${measureProbeDisplacement(topwear, probes.leftPrimary).toFixed(2)}px · `
        + `Measured R: ${measureProbeDisplacement(topwear, probes.rightPrimary).toFixed(2)}px`;
    } else {
      calibrationEl.textContent = `Requested: ${state.calibrationRequested.toFixed(2)}px · `
        + "Measured: compiled topwear probes unavailable";
    }
  }
  const uploadStart = performance.now();
  for (const { part: p, opacity } of drawParts) {
    gl.bindBuffer(gl.ARRAY_BUFFER, p.buf.pos);
    if (p.dirty) gl.bufferSubData(gl.ARRAY_BUFFER, 0, p.mesh.live);
    gl.enableVertexAttribArray(loc.pos);
    gl.vertexAttribPointer(loc.pos, 2, gl.FLOAT, false, 0, 0);

    gl.bindBuffer(gl.ARRAY_BUFFER, p.buf.uv);
    gl.enableVertexAttribArray(loc.uv);
    gl.vertexAttribPointer(loc.uv, 2, gl.FLOAT, false, 0, 0);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, p.tex);
    gl.uniform1i(loc.tex, 0);
    if (p.clipMaskSource) {
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, p.clipMaskSource.tex);
      gl.uniform1i(loc.mask, 1);
      const box = p.clipMaskSource.spec.xyxy;
      gl.uniform4f(loc.maskBox, box[0], box[1], box[2], box[3]);
      gl.uniform1f(loc.maskEnabled, 1);
    } else {
      gl.uniform1f(loc.maskEnabled, 0);
    }

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
  state.profiler.uploadMs = performance.now() - uploadStart;
  updateProfiler(now, performance.now() - frameStart, activeVertices, totalVertices);
  const torsoGraph = motion.physics?.torso || {};
  state.motionGraph.push({ body: state.bodyMotion.y, left: torsoGraph.left?.value ?? 0,
    right: torsoGraph.right?.value ?? 0 });
  if (state.motionGraph.length > 300) state.motionGraph.shift();
  drawMotionGraph();
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

function updateQaBadge() {
  const badge = document.getElementById("qaBadge");
  if (!badge) return;
  const active = document.getElementById("doSoftMorph")?.checked
    && (Number(document.getElementById("softStrength")?.value || 0) > 0
      || Number(document.getElementById("softHoriz")?.value || 0) > 0
      || Number(document.getElementById("softVert")?.value || 0) > 0);
  badge.hidden = !active;
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
  updateQaBadge();
});
document.getElementById("softHoriz").addEventListener("input", () => {
  document.getElementById("softHorizv").textContent =
    parseFloat(document.getElementById("softHoriz").value).toFixed(1) + "px";
  updateQaBadge();
});
document.getElementById("softVert").addEventListener("input", () => {
  document.getElementById("softVertv").textContent =
    parseFloat(document.getElementById("softVert").value).toFixed(1) + "px";
  updateQaBadge();
});
document.getElementById("doSoftMorph").addEventListener("change", updateQaBadge);

function calibrateChest(requestedPx) {
  const driver = state.physicsDrivers?.torso;
  if (!driver?.setRelativeDisplacement) {
    const el = document.getElementById("chestCalibration");
    if (el) el.textContent = "Chest px calibration requires inertial_relative_v2";
    return;
  }
  state.calibrationRequested = requestedPx;
  const soft = document.getElementById("doSoftMorph");
  if (soft) soft.checked = true;
  state.physicsOutputs.torso = driver.setRelativeDisplacement(requestedPx);
}
document.getElementById("chest1px").addEventListener("click", () => calibrateChest(1));
document.getElementById("chest2px").addEventListener("click", () => calibrateChest(2));
document.getElementById("chest4px").addEventListener("click", () => calibrateChest(4));

document.getElementById("chestInertia").addEventListener("change", (event) => {
  state.motionQA.inertia = event.target.checked;
});
document.getElementById("asymmetry").addEventListener("input", (event) => {
  state.motionQA.asymmetry = Number(event.target.value);
  document.getElementById("asymmetryv").textContent = state.motionQA.asymmetry.toFixed(2);
});
document.getElementById("kickX").addEventListener("click", () => { state.bodyPulse.vx += 36; });
document.getElementById("kickY").addEventListener("click", () => { state.bodyPulse.vy += 48; });
document.getElementById("chestImpulseY").addEventListener("click", () => {
  state.motionQA.chestImpulseY += 3;
});
document.getElementById("stopBody").addEventListener("click", () => {
  state.bodySwayEnabled = false;
  const toggle = document.getElementById("bodySway"); if (toggle) toggle.checked = false;
  state.bodyPulse.vx = 0; state.bodyPulse.vy = 0;
  state.motionQA.chestImpulseX = 0; state.motionQA.chestImpulseY = 0;
});
document.getElementById("breathOnly").addEventListener("click", () => {
  state.motionQA.inertia = false; state.motionQA.inertiaOnly = false;
  document.getElementById("chestInertia").checked = false;
});
document.getElementById("inertiaOnly").addEventListener("click", () => {
  state.motionQA.inertia = true; state.motionQA.inertiaOnly = true;
  document.getElementById("chestInertia").checked = true;
});
document.getElementById("resetMotion").addEventListener("click", () => {
  state.motionQA = { inertia: true, inertiaOnly: false, asymmetry: 1, inertiaMultiplier: 1,
    settleMultiplier: 1, chestImpulseX: 0, chestImpulseY: 0 };
  const toggle = document.getElementById("bodySway"); if (toggle) toggle.checked = true;
  resetPhysics();
});

document.getElementById("blinkNow").addEventListener("click",
  () => startBlink(performance.now(), ["l", "r"]));
document.getElementById("winkL").addEventListener("click",
  () => startBlink(performance.now(), ["l"]));
document.getElementById("winkR").addEventListener("click",
  () => startBlink(performance.now(), ["r"]));
