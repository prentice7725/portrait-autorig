/* Rig Studio motion and display preferences. */

"use strict";

export const RIG_STUDIO_A11Y_VERSION = "A11Y-1.1";
export const UI_SCALE_OPTIONS = Object.freeze([100, 125, 150]);
export const MOTION_PREFERENCES = Object.freeze(["system", "reduce", "full"]);
const MOTION_STORAGE_KEY = "portrait-autorig.motion-preference";
const SCALE_STORAGE_KEY = "portrait-autorig.ui-scale";

export function normalizeUiScale(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return UI_SCALE_OPTIONS[0];
  return UI_SCALE_OPTIONS.reduce((nearest, candidate) =>
    Math.abs(candidate - numeric) < Math.abs(nearest - numeric) ? candidate : nearest,
  UI_SCALE_OPTIONS[0]);
}

export function keyboardNudge(key, step = 1, multiplier = 1) {
  const distance = Math.abs(Number(step)) * Math.abs(Number(multiplier));
  if (!Number.isFinite(distance) || distance <= 0) return null;
  switch (String(key)) {
    case "ArrowLeft": return [-distance, 0];
    case "ArrowRight": return [distance, 0];
    case "ArrowUp": return [0, -distance];
    case "ArrowDown": return [0, distance];
    default: return null;
  }
}

export function isTextEntryTarget(target) {
  const selector = "input, textarea, select, [contenteditable]:not([contenteditable=\"false\"]), [role=\"textbox\"]";
  return !!(target?.closest?.(selector) || target?.matches?.(selector));
}

function storageGet(windowRef, key) {
  try { return windowRef?.localStorage?.getItem(key) ?? null; }
  catch { return null; }
}

function storageSet(windowRef, key, value) {
  try { windowRef?.localStorage?.setItem(key, value); }
  catch { /* Preferences remain active for this session when storage is unavailable. */ }
}

function dispatch(windowRef, name, detail) {
  if (!windowRef?.dispatchEvent) return;
  const EventCtor = windowRef.CustomEvent || globalThis.CustomEvent;
  if (typeof EventCtor === "function") windowRef.dispatchEvent(new EventCtor(name, { detail }));
}

export function initAccessibility(documentRef = globalThis.document, windowRef = globalThis.window) {
  if (!documentRef?.documentElement) return null;
  const root = documentRef.documentElement;
  const motionSelect = documentRef.getElementById?.("motionPreference");
  const motionStatus = documentRef.getElementById?.("motionStatus");
  const scaleSelect = documentRef.getElementById?.("uiScale");
  const scaleStatus = documentRef.getElementById?.("uiScaleStatus");
  const media = windowRef?.matchMedia?.("(prefers-reduced-motion: reduce)") || null;
  const storedMotion = storageGet(windowRef, MOTION_STORAGE_KEY);
  let preference = MOTION_PREFERENCES.includes(storedMotion) ? storedMotion : "system";
  let effectiveReduced = null;

  function effectiveFor(nextPreference) {
    return nextPreference === "reduce" || (nextPreference === "system" && !!media?.matches);
  }

  function announceMotion(nextPreference, enabled) {
    if (!motionStatus) return;
    const source = nextPreference === "system" ? "OS 설정" : nextPreference === "reduce" ? "감소" : "전체";
    motionStatus.textContent = `동작: ${source} · ${enabled ? "감소 적용" : "전체 재생"}`;
    motionStatus.dataset.state = enabled ? "active" : "inactive";
  }

  function setMotionPreference(value, source = "user", announce = true) {
    const next = MOTION_PREFERENCES.includes(String(value)) ? String(value) : "system";
    const preferenceChanged = next !== preference;
    preference = next;
    root.dataset.motionPreference = next;
    root.dataset.reduceMotion = String(effectiveFor(next));
    if (motionSelect) motionSelect.value = next;
    if (source === "user") storageSet(windowRef, MOTION_STORAGE_KEY, next);
    const enabled = effectiveFor(next);
    const changed = enabled !== effectiveReduced;
    effectiveReduced = enabled;
    if (announce) announceMotion(next, enabled);
    if (changed || preferenceChanged) dispatch(windowRef, "rigstudio:reducedmotionchange", {
      enabled, preference: next, source,
    });
    return { preference: next, enabled };
  }

  setMotionPreference(preference, "system", false);
  motionSelect?.addEventListener?.("change", (event) =>
    setMotionPreference(event.currentTarget.value, "user"));
  const onMediaChange = () => {
    if (preference === "system") setMotionPreference("system", "system");
  };
  if (media?.addEventListener) media.addEventListener("change", onMediaChange);
  else media?.addListener?.(onMediaChange);
  announceMotion(preference, effectiveReduced);

  function setUiScale(value, source = "user", announce = true) {
    const next = normalizeUiScale(value);
    root.dataset.uiScale = String(next);
    documentRef.body?.setAttribute?.("data-ui-scale", String(next));
    root.style?.setProperty?.("--rig-studio-ui-scale", String(next / 100));
    if (scaleSelect) scaleSelect.value = String(next);
    if (scaleStatus && announce) scaleStatus.textContent = `UI 크기: ${next}%`;
    if (source === "user") storageSet(windowRef, SCALE_STORAGE_KEY, String(next));
    dispatch(windowRef, "rigstudio:uiscalechange", { scale: next, source });
    return next;
  }

  const storedScale = storageGet(windowRef, SCALE_STORAGE_KEY);
  setUiScale(storedScale || scaleSelect?.value || 100, "system", false);
  scaleSelect?.addEventListener?.("change", (event) => setUiScale(event.currentTarget.value));
  if (scaleStatus) scaleStatus.textContent = `UI 크기: ${normalizeUiScale(root.dataset.uiScale || 100)}%`;

  return Object.freeze({
    setMotionPreference,
    setUiScale,
    get motionPreference() { return preference; },
    get reducedMotion() { return effectiveReduced; },
    media,
  });
}

if (typeof document !== "undefined") initAccessibility();
