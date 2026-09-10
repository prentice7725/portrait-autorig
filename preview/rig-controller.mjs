/*
 * P5 preview controller.
 *
 * The controller is intentionally DOM-free until bindDom() is called. It
 * owns preview input arbitration (parameters, idle, blink, gaze, expression,
 * breath) and the Edit suspend/resume state machine. Runtime supplies the
 * resulting frame intent to the renderer; the legacy DOM ids are an adapter,
 * not the controller's source of truth.
 */

"use strict";

export const RIG_CONTROLLER_VERSION = "P5.0";
export const CURSOR_FOLLOW_VERSION = "P6.1";
export const EXPRESSION_LIFECYCLE_VERSION = "P6.2";
export const LIPSYNC_VERSION = "P6.3";
export const MANUAL_RELEASE_GRACE_MS = 350;

const CURSOR_HEAD_SHARE = Object.freeze({ x: 0.20, y: 0.15 });

const EDIT_CONTROL_IDS = [
  "autoIdle", "bodySway", "chestInertia", "doBlink", "doBreathe", "doTalk",
  "useArt", "gazeX", "gazeY", "mouthOpen", "breathAmp", "turnX", "turnY",
  "tilt", "shell", "r2EditMode",
];

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function numberOr(value, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

export function createRigController({ runtimeState = {}, random = () => Math.random() } = {}) {
  let manifest = null;
  let boundDocument = null;
  let boundWindow = null;
  let editSnapshot = null;
  let idleUiLast = -Infinity;
  let lastNow = 0;
  let cursorFollowEnabled = false;
  let cursorPosition = { x: 0, y: 0, inside: false };
  let activeExpression = null;
  let onExpressionChange = null;
  let lipSyncEnabled = false;
  let lipSyncRms = 0;
  const manualClaims = new Map();
  const manualGraceUntil = new Map();
  const controls = new Map();

  function ownershipKey(id) {
    if (["gazeX", "gazeY", "ParamEyeBallX", "ParamEyeBallY"].includes(id)) return "gaze";
    if (["turnX", "turnY", "ParamAngleX", "ParamAngleY"].includes(id)) return "head";
    return id;
  }

  function isManual(key, now = lastNow) {
    return Number(manualClaims.get(key) || 0) > 0 || Number(manualGraceUntil.get(key) || 0) > now;
  }

  function beginManual(id) {
    const key = ownershipKey(id);
    manualClaims.set(key, Number(manualClaims.get(key) || 0) + 1);
    manualGraceUntil.delete(key);
    if (key === "head") {
      runtimeState.turnX = readValue("turnX", runtimeState.turnX);
      runtimeState.turnY = readValue("turnY", runtimeState.turnY);
    }
    if (key === "gaze") {
      runtimeState.gazeTargets = [readValue("gazeX", runtimeState.gazeTargets?.[0]),
        readValue("gazeY", runtimeState.gazeTargets?.[1])];
    }
  }

  function endManual(id, now = lastNow) {
    const key = ownershipKey(id);
    const count = Number(manualClaims.get(key) || 0) - 1;
    if (count > 0) return;
    manualClaims.delete(key);
    manualGraceUntil.set(key, now + MANUAL_RELEASE_GRACE_MS);
  }

  function noteManualActivity(id, now = lastNow) {
    const key = ownershipKey(id);
    if (key === "gaze" || key === "head")
      manualGraceUntil.set(key, now + MANUAL_RELEASE_GRACE_MS);
  }

  function normalizePointer(clientX, clientY, rect) {
    const width = Math.max(1, Number(rect?.width) || 1);
    const height = Math.max(1, Number(rect?.height) || 1);
    const left = Number(rect?.left) || 0;
    const top = Number(rect?.top) || 0;
    return {
      x: Math.max(-1, Math.min(1, ((Number(clientX) - left) / width) * 2 - 1)),
      y: Math.max(-1, Math.min(1, ((Number(clientY) - top) / height) * 2 - 1)),
    };
  }

  function setCursorGazeEnabled(enabled) {
    cursorFollowEnabled = !!enabled;
    runtimeState.cursorFollowEnabled = cursorFollowEnabled;
    if (!cursorFollowEnabled) cursorPosition = { x: 0, y: 0, inside: false };
    writeControl("followCursor", cursorFollowEnabled);
    return cursorFollowEnabled;
  }

  function lookAt(x, y, inside = true) {
    cursorPosition = {
      x: Math.max(-1, Math.min(1, numberOr(x))),
      y: Math.max(-1, Math.min(1, numberOr(y))),
      inside: !!inside,
    };
    return { ...cursorPosition };
  }

  function releaseCursor() {
    cursorPosition = { x: 0, y: 0, inside: false };
    return { ...cursorPosition };
  }

  function expressionCatalog() {
    const presets = currentManifest()?.expression_presets;
    if (!presets || typeof presets !== "object" || Array.isArray(presets)) return [];
    return Object.entries(presets)
      .filter(([, preset]) => preset && typeof preset === "object"
        && preset.variants && typeof preset.variants === "object")
      .map(([id, preset]) => ({ id, ...preset }))
      .sort((a, b) => {
        const orderA = Number(a.metadata?.order ?? a.order ?? Number.MAX_SAFE_INTEGER);
        const orderB = Number(b.metadata?.order ?? b.order ?? Number.MAX_SAFE_INTEGER);
        return (Number.isFinite(orderA) ? orderA : Number.MAX_SAFE_INTEGER)
          - (Number.isFinite(orderB) ? orderB : Number.MAX_SAFE_INTEGER)
          || a.id.localeCompare(b.id);
      });
  }

  function setExpression(id) {
    const entry = expressionCatalog().find((preset) => preset.id === String(id));
    if (!entry) throw new Error(`unknown ExpressionPreset: ${id}`);
    activeExpression = entry.id;
    onExpressionChange?.(activeExpression);
    dispatch("rigstudio:expressionchange", { id: activeExpression, source: "manual" });
    return activeExpression;
  }

  function releaseExpression() {
    activeExpression = null;
    onExpressionChange?.(null);
    dispatch("rigstudio:expressionchange", { id: null, source: "release" });
    return null;
  }

  function setLipSyncEnabled(enabled) {
    lipSyncEnabled = !!enabled;
    runtimeState.lipSyncEnabled = lipSyncEnabled;
    if (!lipSyncEnabled) {
      lipSyncRms = 0;
      runtimeState.lipSyncRms = 0;
      runtimeState.mouthOpen = 0;
      writeControl("mouthOpen", 0);
    }
    writeControl("lipSyncEnabled", lipSyncEnabled);
    return lipSyncEnabled;
  }

  function setLipSyncRms(value) {
    if (!lipSyncEnabled) return 0;
    const numeric = Number(value);
    if (Number.isNaN(numeric)) return lipSyncRms;
    lipSyncRms = Number.isFinite(numeric) ? numeric : (numeric > 0 ? 1 : 0);
    lipSyncRms = Math.max(0, Math.min(1, lipSyncRms));
    runtimeState.lipSyncRms = lipSyncRms;
    return lipSyncRms;
  }

  function currentManifest() {
    return manifest || runtimeState.manifest || null;
  }

  function element(id) {
    return boundDocument?.getElementById?.(id) || controls.get(id) || null;
  }

  function readValue(id, fallback = 0) {
    const value = element(id)?.value;
    return numberOr(value, fallback);
  }

  function isChecked(id, fallback = false) {
    const control = element(id);
    return typeof control?.checked === "boolean" ? control.checked : fallback;
  }

  function writeControl(id, value) {
    const control = element(id);
    if (!control) return;
    if (typeof value === "boolean") control.checked = value;
    else control.value = String(value);
  }

  function configure(nextManifest, options = {}) {
    manifest = nextManifest || null;
    onExpressionChange = options.onExpressionChange || null;
    editSnapshot = null;
    idleUiLast = -Infinity;
    cursorFollowEnabled = false;
    runtimeState.cursorFollowEnabled = false;
    cursorPosition = { x: 0, y: 0, inside: false };
    activeExpression = null;
    lipSyncEnabled = false;
    lipSyncRms = 0;
    runtimeState.lipSyncEnabled = false;
    runtimeState.lipSyncRms = 0;
    manualClaims.clear();
    manualGraceUntil.clear();
  }

  function reset() {
    manifest = null;
    editSnapshot = null;
    idleUiLast = -Infinity;
    cursorFollowEnabled = false;
    runtimeState.cursorFollowEnabled = false;
    cursorPosition = { x: 0, y: 0, inside: false };
    activeExpression = null;
    lipSyncEnabled = false;
    lipSyncRms = 0;
    runtimeState.lipSyncEnabled = false;
    runtimeState.lipSyncRms = 0;
    manualClaims.clear();
    manualGraceUntil.clear();
    controls.clear();
  }

  function setParameter(id, value, source = "manual") {
    if (source === "manual") {
      const clock = typeof performance !== "undefined" && Number.isFinite(performance.now?.())
        ? performance.now() : lastNow;
      noteManualActivity(id, clock);
    }
    const descriptor = (currentManifest()?.parameters || []).find((item) => item?.id === id);
    let numeric = numberOr(value, numberOr(descriptor?.default, 0));
    if (descriptor) numeric = Math.max(descriptor.min, Math.min(descriptor.max, numeric));
    runtimeState.parameters ||= {};
    runtimeState.parameterOverrides ||= {};
    runtimeState.parameters[id] = numeric;
    if (id === "ParamAngleX") runtimeState.turnX = numeric;
    if (id === "ParamAngleY") runtimeState.turnY = numeric;
    if (id === "ParamAngleZ") runtimeState.tiltDeg = numeric;
    if (id === "ParamEyeBallX") { runtimeState.gazeTargets ||= [0, 0]; runtimeState.gazeTargets[0] = numeric; }
    if (id === "ParamEyeBallY") { runtimeState.gazeTargets ||= [0, 0]; runtimeState.gazeTargets[1] = numeric; }
    if (id === "ParamMouthOpenY") runtimeState.mouthOpen = numeric;
    if (["ParamBreath", "ParamEyeLOpen", "ParamEyeROpen"].includes(id))
      runtimeState.parameterOverrides[id] = numeric;
    const legacyId = {
      ParamAngleX: "turnX", ParamAngleY: "turnY", ParamAngleZ: "tilt",
      ParamEyeBallX: "gazeX", ParamEyeBallY: "gazeY", ParamMouthOpenY: "mouthOpen",
    }[id];
    if (legacyId) writeControl(legacyId, numeric);
    return numeric;
  }

  function parameterValue(id, motion = {}) {
    const overrides = runtimeState.parameterOverrides || {};
    const parameters = runtimeState.parameters || {};
    if (overrides[id] != null) return numberOr(overrides[id]);
    if (motion.parameters && motion.parameters[id] != null) return numberOr(motion.parameters[id]);
    if (id === "ParamAngleX") return numberOr(motion.turnX, numberOr(runtimeState.turnX));
    if (id === "ParamAngleY") return numberOr(motion.turnY, numberOr(runtimeState.turnY));
    if (id === "ParamAngleZ") return numberOr(motion.tiltRad);
    if (id === "ParamEyeLOpen" && motion.blink) return 1 - numberOr(motion.blink.l);
    if (id === "ParamEyeROpen" && motion.blink) return 1 - numberOr(motion.blink.r);
    if (id === "ParamMouthOpenY" && motion.mouthOpen != null) return numberOr(motion.mouthOpen);
    if (id === "ParamBreath" && motion.breath != null) return numberOr(motion.breath);
    if (id === "ParamEyeBallX") return numberOr(motion.gazeX, numberOr(parameters[id]));
    if (id === "ParamEyeBallY") return numberOr(motion.gazeY, numberOr(parameters[id]));
    return numberOr(parameters[id]);
  }

  function scheduleBlink(now) {
    const interval = currentManifest()?.motion?.blink?.interval_s || [2.5, 5.5];
    runtimeState.blinkTimer = now + (numberOr(interval[0], 2.5)
      + random() * (numberOr(interval[1], 5.5) - numberOr(interval[0], 2.5))) * 1000;
  }

  function startBlink(now, sides) {
    const cfg = currentManifest()?.motion?.blink || {};
    runtimeState.blinkPhase = {
      start: now, sides,
      close: numberOr(cfg.close_s, 0.09) * 1000,
      hold: numberOr(cfg.hold_s, 0.07) * 1000,
      open: numberOr(cfg.open_s, 0.14) * 1000,
    };
  }

  function blinkAmount(now) {
    const phase = runtimeState.blinkPhase;
    if (!phase) return { l: 0, r: 0 };
    const elapsed = now - phase.start;
    let amount;
    if (elapsed < phase.close) amount = elapsed / phase.close;
    else if (elapsed < phase.close + phase.hold) amount = 1;
    else if (elapsed < phase.close + phase.hold + phase.open)
      amount = 1 - (elapsed - phase.close - phase.hold) / phase.open;
    else {
      runtimeState.blinkPhase = null;
      return { l: 0, r: 0 };
    }
    return {
      l: phase.sides.includes("l") ? amount : 0,
      r: phase.sides.includes("r") ? amount : 0,
    };
  }

  function updateIdleControls(now) {
    if (now - idleUiLast < 100) return;
    idleUiLast = now;
    for (const [id, value, digits] of [["turnX", runtimeState.turnX, 2],
      ["turnY", runtimeState.turnY, 2], ["tilt", runtimeState.tiltDeg, 1]]) {
      const slider = element(id);
      if (slider) slider.value = value;
      const label = element(`${id}v`);
      if (label) label.textContent = Number(value).toFixed(digits) + (id === "tilt" ? "°" : "");
    }
  }

  function tick(now, { t = 0, dt = 0, mouthAvailable = false, mouthVariant = false } = {}) {
    lastNow = numberOr(now, lastNow);
    const editActive = !!runtimeState.editSession?.active;
    const autoIdle = !editActive && isChecked("autoIdle");
    const motion = currentManifest()?.motion || {};
    const manualHead = isManual("head", now);
    if (autoIdle && !manualHead) {
      const turn = motion.head_turn || { max_x: 0, max_y: 0 };
      const limit = Math.min(numberOr(turn.max_x), 0.3);
      runtimeState.turnX = (Math.sin(t * 0.37) * 0.73 + Math.sin(t * 0.13) * 0.27) * limit;
      runtimeState.turnY = Math.sin(t * 0.29 + 1.1) * 0.45 * Math.min(numberOr(turn.max_y), 0.3);
      runtimeState.tiltDeg = Math.sin(t * 0.23 + 0.6) * numberOr(motion.head_tilt?.max_deg);
      updateIdleControls(now);
    }
    if (!autoIdle) {
      runtimeState.turnX = readValue("turnX", runtimeState.turnX);
      runtimeState.turnY = readValue("turnY", runtimeState.turnY);
    }
    runtimeState.bodySwayEnabled = !editActive && isChecked("bodySway") && autoIdle;

    if (!editActive && isChecked("doBlink")) {
      if (!runtimeState.blinkTimer) scheduleBlink(now);
      if (!runtimeState.blinkPhase && now >= runtimeState.blinkTimer) {
        startBlink(now, ["l", "r"]);
        scheduleBlink(now);
        if (random() < 0.2) runtimeState.blinkTimer = now + 260;
      }
    }

    const hasMouth = mouthAvailable || mouthVariant;
    const lipSyncActive = !editActive && lipSyncEnabled && hasMouth;
    const talkEnabled = !editActive && !lipSyncActive && hasMouth && isChecked("doTalk");
    if (lipSyncActive) {
      runtimeState.mouthOpen = lipSyncRms;
      writeControl("mouthOpen", lipSyncRms);
    } else if (talkEnabled) {
      if (now >= runtimeState.talkUntil) {
        runtimeState.talkTarget = runtimeState.talkTarget > 0.5 ? 0 : 0.55 + random() * 0.45;
        runtimeState.talkUntil = now + (runtimeState.talkTarget > 0.5
          ? 90 + random() * 110 : 70 + random() * 160);
      }
      runtimeState.mouthOpen += (runtimeState.talkTarget - runtimeState.mouthOpen)
        * Math.min(1, dt * 18);
    } else {
      runtimeState.mouthOpen = readValue("mouthOpen", runtimeState.mouthOpen);
    }

    const cursorActive = !editActive && cursorFollowEnabled && cursorPosition.inside;
    const cursorOwnsGaze = cursorActive && !isManual("gaze", now);
    let outputTurnX = runtimeState.turnX;
    let outputTurnY = runtimeState.turnY;
    if (cursorActive && !manualHead) {
      outputTurnX = cursorPosition.x * CURSOR_HEAD_SHARE.x;
      outputTurnY = cursorPosition.y * CURSOR_HEAD_SHARE.y;
    }
    const animatedBlink = blinkAmount(now);
    const overrides = runtimeState.parameterOverrides || {};
    const blink = {
      l: overrides.ParamEyeLOpen != null ? 1 - numberOr(overrides.ParamEyeLOpen) : animatedBlink.l,
      r: overrides.ParamEyeROpen != null ? 1 - numberOr(overrides.ParamEyeROpen) : animatedBlink.r,
    };
    const automaticBreath = !editActive && isChecked("doBreathe")
      ? Math.sin(t * 2 * Math.PI / numberOr(motion.breathing?.period_s, 4.8)) : 0;
    const breath = overrides.ParamBreath != null ? numberOr(overrides.ParamBreath) : automaticBreath;
    return {
      editActive,
      autoIdle,
      bodySwayEnabled: runtimeState.bodySwayEnabled,
      turnX: outputTurnX,
      turnY: outputTurnY,
      tiltDeg: runtimeState.tiltDeg,
      gazeX: cursorOwnsGaze ? cursorPosition.x : readValue("gazeX", numberOr(runtimeState.gazeTargets?.[0])),
      gazeY: cursorOwnsGaze ? cursorPosition.y : readValue("gazeY", numberOr(runtimeState.gazeTargets?.[1])),
      cursorActive: cursorOwnsGaze || (cursorActive && !manualHead),
      cursorPosition: { ...cursorPosition },
      expressionId: activeExpression,
      lipSyncActive,
      lipSyncRms,
      mouthOpen: runtimeState.mouthOpen,
      blink,
      breath,
      useArt: isChecked("useArt"),
      talkEnabled,
    };
  }

  function controlSnapshot() {
    const values = {};
    for (const id of EDIT_CONTROL_IDS) {
      const control = element(id);
      if (!control) continue;
      values[id] = {
        checked: typeof control.checked === "boolean" ? control.checked : undefined,
        value: control.value,
      };
    }
    return values;
  }

  function restoreControls(values = {}) {
    for (const [id, saved] of Object.entries(values)) {
      if (typeof saved.checked === "boolean") writeControl(id, saved.checked);
      if (saved.value != null) writeControl(id, saved.value);
    }
  }

  function enterEdit(now = 0) {
    if (runtimeState.editSession?.active) return runtimeState.editSession;
    editSnapshot = {
      controls: controlSnapshot(),
      turnX: runtimeState.turnX, turnY: runtimeState.turnY, tiltDeg: runtimeState.tiltDeg,
      shell: runtimeState.shell, mouthOpen: runtimeState.mouthOpen,
      talkUntil: runtimeState.talkUntil, talkTarget: runtimeState.talkTarget,
      blink: clone(runtimeState.blink), blinkTimer: runtimeState.blinkTimer,
      blinkPhase: clone(runtimeState.blinkPhase), gazeTargets: clone(runtimeState.gazeTargets),
      parameters: clone(runtimeState.parameters), parameterOverrides: clone(runtimeState.parameterOverrides),
      motionQA: clone(runtimeState.motionQA), collarOverride: runtimeState.collarOverride,
      displayPreset: runtimeState.displayPreset, r2EditMode: runtimeState.r2?.editMode,
      lipSyncEnabled, lipSyncRms,
    };
    runtimeState.editSession = { active: true, enteredAt: now, snapshot: editSnapshot, physicsSuspended: true };
    runtimeState.turnX = runtimeState.turnY = runtimeState.tiltDeg = runtimeState.shell = 0;
    runtimeState.mouthOpen = runtimeState.talkUntil = runtimeState.talkTarget = 0;
    runtimeState.blink = { l: 0, r: 0 };
    runtimeState.blinkTimer = 0;
    runtimeState.blinkPhase = null;
    runtimeState.gazeTargets = [0, 0];
    const defaults = {};
    for (const descriptor of currentManifest()?.parameters || []) defaults[descriptor.id] = numberOr(descriptor.default);
    runtimeState.parameters = defaults;
    runtimeState.parameterOverrides = {};
    runtimeState.motionQA = {
      ...runtimeState.motionQA, inertia: false, inertiaOnly: false, asymmetry: 1,
      shapeGain: null, side: "both", chestImpulseX: 0, chestImpulseY: 0,
      poseActive: false, poseQ: 0, poseV: 0, p3Pose: null,
    };
    runtimeState.bodySwayEnabled = false;
    for (const id of ["autoIdle", "bodySway", "chestInertia", "doBlink", "doBreathe", "doTalk"])
      writeControl(id, false);
    for (const [id, value] of [["turnX", 0], ["turnY", 0], ["tilt", 0], ["gazeX", 0],
      ["gazeY", 0], ["mouthOpen", 0], ["shell", 0]]) writeControl(id, value);
    writeControl("r2EditMode", true);
    return runtimeState.editSession;
  }

  function exitEdit() {
    if (!runtimeState.editSession?.active) return null;
    const snapshot = editSnapshot || runtimeState.editSession.snapshot || {};
    runtimeState.turnX = snapshot.turnX ?? 0;
    runtimeState.turnY = snapshot.turnY ?? 0;
    runtimeState.tiltDeg = snapshot.tiltDeg ?? 0;
    runtimeState.shell = snapshot.shell ?? 0;
    runtimeState.mouthOpen = snapshot.mouthOpen ?? 0;
    runtimeState.talkUntil = snapshot.talkUntil ?? 0;
    runtimeState.talkTarget = snapshot.talkTarget ?? 0;
    runtimeState.blink = clone(snapshot.blink) || { l: 0, r: 0 };
    runtimeState.blinkTimer = snapshot.blinkTimer || 0;
    runtimeState.blinkPhase = clone(snapshot.blinkPhase) || null;
    runtimeState.gazeTargets = clone(snapshot.gazeTargets) || [];
    runtimeState.parameters = clone(snapshot.parameters) || {};
    runtimeState.parameterOverrides = clone(snapshot.parameterOverrides) || {};
    runtimeState.motionQA = clone(snapshot.motionQA) || runtimeState.motionQA;
    runtimeState.collarOverride = snapshot.collarOverride ?? null;
    runtimeState.displayPreset = snapshot.displayPreset || runtimeState.displayPreset;
    lipSyncEnabled = !!snapshot.lipSyncEnabled;
    lipSyncRms = numberOr(snapshot.lipSyncRms);
    runtimeState.lipSyncEnabled = lipSyncEnabled;
    runtimeState.lipSyncRms = lipSyncRms;
    restoreControls(snapshot.controls);
    runtimeState.editSession = { active: false, enteredAt: runtimeState.editSession.enteredAt,
      snapshot: null, physicsSuspended: false };
    editSnapshot = null;
    runtimeState.bodySwayEnabled = false;
    return snapshot;
  }

  function syncSlider(id) {
    const value = readValue(id);
    if (id === "turnX") runtimeState.turnX = value;
    if (id === "turnY") runtimeState.turnY = value;
    if (id === "tilt") runtimeState.tiltDeg = value;
    if (id === "gazeX") setParameter("ParamEyeBallX", value);
    if (id === "gazeY") setParameter("ParamEyeBallY", value);
    const label = element(`${id}v`);
    if (label) label.textContent = value.toFixed(id === "tilt" ? 1 : 2) + (id === "tilt" ? "°" : "");
    return value;
  }

  function setSlider(id, value) {
    writeControl(id, value);
    return syncSlider(id);
  }

  function bindManualPointer(id) {
    const control = element(id);
    if (!control?.addEventListener) return;
    control.addEventListener("pointerdown", () => beginManual(id));
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"])
      control.addEventListener(type, () => endManual(id, lastNow));
    control.addEventListener("keydown", () => beginManual(id));
    for (const type of ["keyup", "blur"])
      control.addEventListener(type, () => endManual(id, lastNow));
  }

  // Test/host seam: callers without a DOM can provide the same small control
  // records that bindDom() would read from native inputs.
  function setControl(id, value) {
    const existing = controls.get(id) || {};
    if (typeof value === "boolean") existing.checked = value;
    else existing.value = String(value);
    controls.set(id, existing);
  }

  function dispatch(type, detail) {
    if (boundWindow?.dispatchEvent && typeof CustomEvent !== "undefined")
      boundWindow.dispatchEvent(new CustomEvent(type, { detail }));
  }

  function bindDom({ document, window, onModeChange = () => {} } = {}) {
    boundDocument = document || null;
    boundWindow = window || null;
    for (const id of EDIT_CONTROL_IDS) {
      const control = boundDocument?.getElementById?.(id);
      if (control) controls.set(id, control);
    }
    for (const id of ["gazeX", "gazeY"]) element(id)?.addEventListener("input", () => syncSlider(id));
    for (const id of ["turnX", "turnY", "tilt"]) {
      element(id)?.addEventListener("input", () => {
        writeControl("autoIdle", false);
        syncSlider(id);
      });
    }
    for (const id of ["gazeX", "gazeY", "turnX", "turnY"]) bindManualPointer(id);
    element("followCursor")?.addEventListener("change", (event) => {
      setCursorGazeEnabled(!!event.currentTarget.checked);
    });
    const cursorSurface = element("canvasWrap") || element("gl");
    cursorSurface?.addEventListener("pointermove", (event) => {
      if (!cursorFollowEnabled) return;
      const rect = cursorSurface.getBoundingClientRect?.();
      if (rect) lookAt(...Object.values(normalizePointer(event.clientX, event.clientY, rect)));
    });
    cursorSurface?.addEventListener("pointerleave", () => releaseCursor());
    element("mouthOpen")?.addEventListener("input", () => {
      writeControl("doTalk", false);
      runtimeState.mouthOpen = readValue("mouthOpen", 0);
      const label = element("mouthOpenv");
      if (label) label.textContent = runtimeState.mouthOpen.toFixed(2);
    });
    element("blinkNow")?.addEventListener("click", () => startBlink(performance.now(), ["l", "r"]));
    element("winkL")?.addEventListener("click", () => startBlink(performance.now(), ["l"]));
    element("winkR")?.addEventListener("click", () => startBlink(performance.now(), ["r"]));
    boundWindow?.addEventListener?.("rigstudio:setparameter", (event) => {
      const { id, value, source = "manual" } = event.detail || {};
      if (!id) return;
      const numeric = setParameter(id, value, source);
      if (["ParamAngleX", "ParamAngleY", "ParamAngleZ"].includes(id)) writeControl("autoIdle", false);
      if (id === "ParamMouthOpenY") writeControl("doTalk", false);
      dispatch("rigstudio:parameterchange", { id, value: numeric, source });
    });
    boundWindow?.addEventListener?.("rigstudio:modechange", (event) => onModeChange(event.detail?.mode));
    boundWindow?.addEventListener?.("rigstudio:setexpression", (event) => {
      try {
        setExpression(event.detail?.id);
      } catch (error) {
        dispatch("rigstudio:expressionerror", { message: error.message });
      }
    });
    boundWindow?.addEventListener?.("rigstudio:releaseexpression", () => releaseExpression());
    element("lipSyncEnabled")?.addEventListener("change", (event) => {
      setLipSyncEnabled(!!event.currentTarget.checked);
    });
    boundWindow?.addEventListener?.("rigstudio:lipsync:enabled", (event) => {
      setLipSyncEnabled(event.detail?.enabled !== false);
    });
    boundWindow?.addEventListener?.("rigstudio:lipsync:rms", (event) => {
      setLipSyncRms(event.detail?.rms);
    });
    boundWindow?.addEventListener?.("rigstudio:lipsync:stop", () => setLipSyncEnabled(false));
  }

  return {
    configure, reset, setParameter, parameterValue, scheduleBlink, startBlink, blinkAmount,
    tick, enterEdit, exitEdit, syncSlider, setSlider, setControl, bindDom,
    beginManual, endManual, noteManualActivity, setCursorGazeEnabled, lookAt, releaseCursor,
    normalizePointer,
    expressionCatalog, setExpression, releaseExpression,
    setLipSyncEnabled, setLipSyncRms,
    get lipSyncEnabled() { return lipSyncEnabled; },
    get lipSyncRms() { return lipSyncRms; },
    get activeExpression() { return activeExpression; },
    get cursorFollowEnabled() { return cursorFollowEnabled; },
    get editActive() { return !!runtimeState.editSession?.active; },
  };
}
