/*
 * P2 manifest-driven Preview parameter surface.
 *
 * This module owns presentation only.  A slider emits one
 * `rigstudio:setparameter` event; runtime.mjs owns clamping, state updates,
 * and the legacy DOM adapter.  The parameter descriptor is never duplicated
 * in index.html.
 */

export const PARAMETER_UI = Object.freeze({
  ParamAngleX: { label: "Head X", group: "Head", capability: "head_turn", legacyId: "turnX" },
  ParamAngleY: { label: "Head Y", group: "Head", capability: "head_turn", legacyId: "turnY" },
  ParamAngleZ: { label: "Head Z", group: "Head", capability: "head_turn", legacyId: "tilt" },
  ParamEyeLOpen: { label: "Left Eye", group: "Face", capability: "blink_l", advanced: true },
  ParamEyeROpen: { label: "Right Eye", group: "Face", capability: "blink_r", advanced: true },
  ParamEyeBallX: { label: "Gaze X", group: "Gaze", capability: "gaze", legacyId: "gazeX" },
  ParamEyeBallY: { label: "Gaze Y", group: "Gaze", capability: "gaze", legacyId: "gazeY" },
  ParamMouthOpenY: { label: "Mouth", group: "Face", capability: "mouth_open", legacyId: "mouthOpen" },
  ParamMouthForm: { label: "Mouth Form", group: "Face", advanced: true },
  ParamBreath: { label: "Breath", group: "Body", hideLegacyId: "breathAmp" },
  ParamBustX: { label: "Bust X", group: "Body", capability: "upper_torso_parametric", advanced: true },
  ParamBustY: { label: "Bust Y", group: "Body", capability: "upper_torso_parametric", advanced: true },
});

const LEGACY_PARAMETER_IDS = new Set(
  Object.values(PARAMETER_UI).map((metadata) => metadata.legacyId).filter(Boolean),
);

function normalizeCapability(value) {
  const state = String(value || "ready").toLowerCase();
  return ["ready", "degraded", "disabled", "unsupported"].includes(state) ? state : "ready";
}

export function fallbackLabel(id) {
  const value = String(id || "Parameter").replace(/^Param/, "");
  const spaced = value.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").trim();
  return spaced || "Parameter";
}

function referencedParameters(manifest) {
  const refs = new Set();
  for (const deformer of manifest?.deformers || []) {
    for (const id of deformer.parameters || []) refs.add(id);
    if (deformer.parameter) refs.add(deformer.parameter);
  }
  for (const driver of manifest?.drivers || []) {
    for (const input of driver.inputs || []) if (input?.parameter) refs.add(input.parameter);
  }
  return refs;
}

function validDescriptor(raw) {
  const id = String(raw?.id || "").trim();
  const min = Number(raw?.min);
  const max = Number(raw?.max);
  const fallback = Number(raw?.default);
  if (!id || !Number.isFinite(min) || !Number.isFinite(max) || !(max > min)) return null;
  const defaultValue = Number.isFinite(fallback) ? Math.max(min, Math.min(max, fallback)) : min;
  const step = Number(raw?.step);
  return {
    id, min, max, default: defaultValue,
    step: Number.isFinite(step) && step > 0 ? step : null,
  };
}

/** Return the deterministic, capability-filtered controls for a manifest. */
export function buildParameterModel(manifest) {
  const refs = referencedParameters(manifest);
  const capabilities = manifest?.capabilities || {};
  const seen = new Set();
  const items = [];
  for (const raw of manifest?.parameters || []) {
    const descriptor = validDescriptor(raw);
    if (!descriptor || seen.has(descriptor.id)) continue;
    seen.add(descriptor.id);
    const metadata = PARAMETER_UI[descriptor.id] || {
      label: fallbackLabel(descriptor.id), group: "Advanced", advanced: true,
    };
    // An explicitly declared parameter must still be connected to a runtime
    // deformer/driver or a known compatibility adapter.  This keeps stale
    // registry entries such as an unused Mouth Form descriptor out of Preview.
    if (!refs.has(descriptor.id) && !LEGACY_PARAMETER_IDS.has(metadata.legacyId)) continue;
    const capability = metadata.capability || null;
    const capabilityState = capability ? normalizeCapability(capabilities[capability]) : "ready";
    if (["disabled", "unsupported"].includes(capabilityState)) continue;
    items.push({ ...descriptor, ...metadata, capabilityState });
  }
  return items;
}

function controlBlock(id) {
  const element = document.getElementById(id);
  return element?.closest("label") || element || null;
}

function setLegacyVisibility(id, hidden) {
  const block = controlBlock(id);
  if (block) block.hidden = hidden;
}

function slug(id) {
  return String(id).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function formatValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0";
  const absolute = Math.abs(number);
  const places = absolute >= 10 ? 1 : 2;
  return number.toFixed(places).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
}

function defaultStep(item) {
  if (item.step) return item.step;
  const span = item.max - item.min;
  return span <= 2 ? 0.01 : span <= 20 ? 0.1 : 1;
}

function createControl(item, values) {
  const label = document.createElement("label");
  label.className = "parameter-control";
  label.dataset.parameterId = item.id;
  const inputId = `parameter-${slug(item.id)}`;
  label.htmlFor = inputId;

  const title = document.createElement("span");
  title.className = "parameter-title";
  title.textContent = item.label;
  const value = document.createElement("span");
  value.className = "val parameter-value";
  value.dataset.parameterValue = item.id;
  value.textContent = formatValue(values[item.id] ?? item.default);
  label.append(title, value);

  const input = document.createElement("input");
  input.type = "range";
  input.id = inputId;
  input.name = item.id;
  input.min = String(item.min);
  input.max = String(item.max);
  input.step = String(defaultStep(item));
  input.value = String(values[item.id] ?? item.default);
  input.setAttribute("aria-label", item.label);
  input.addEventListener("input", () => {
    value.textContent = formatValue(input.value);
    window.dispatchEvent(new CustomEvent("rigstudio:setparameter", {
      detail: { id: item.id, value: Number(input.value), source: "manual" },
    }));
  });
  label.appendChild(input);

  if (item.capabilityState === "degraded") {
    const warning = document.createElement("span");
    warning.className = "parameter-warning";
    warning.textContent = "Limited support";
    warning.title = "This rig exposes the parameter with reduced capability.";
    label.appendChild(warning);
  }
  return label;
}

function renderParameterPanel(manifest, values = {}) {
  const previewPanel = document.getElementById("previewPanel");
  if (!previewPanel) return;
  const old = document.getElementById("parameterPanel");
  old?.remove();
  const items = buildParameterModel(manifest);
  if (!items.length) return;
  for (const metadata of Object.values(PARAMETER_UI)) {
    if (metadata.legacyId) setLegacyVisibility(metadata.legacyId, false);
    if (metadata.hideLegacyId) setLegacyVisibility(metadata.hideLegacyId, false);
  }
  for (const item of items) {
    if (item.legacyId) setLegacyVisibility(item.legacyId, true);
    if (item.hideLegacyId) setLegacyVisibility(item.hideLegacyId, true);
  }

  const panel = document.createElement("div");
  panel.id = "parameterPanel";
  panel.className = "parameter-panel";
  panel.setAttribute("aria-label", "Runtime parameters");
  const heading = document.createElement("h2");
  heading.textContent = "Parameters";
  panel.appendChild(heading);

  const groups = new Map();
  for (const item of items) {
    if (!groups.has(item.group)) groups.set(item.group, []);
    groups.get(item.group).push(item);
  }
  for (const [name, groupItems] of groups) {
    const section = document.createElement("section");
    section.className = "parameter-group";
    const title = document.createElement("h3");
    title.textContent = name;
    section.appendChild(title);
    const regular = groupItems.filter((item) => !item.advanced);
    const advanced = groupItems.filter((item) => item.advanced);
    for (const item of regular) section.appendChild(createControl(item, values));
    if (advanced.length) {
      const details = document.createElement("details");
      details.className = "parameter-advanced";
      const summary = document.createElement("summary");
      summary.textContent = "Advanced";
      details.appendChild(summary);
      for (const item of advanced) details.appendChild(createControl(item, values));
      section.appendChild(details);
    }
    panel.appendChild(section);
  }
  const intro = previewPanel.querySelector(".mode-intro");
  if (intro) intro.after(panel);
  else previewPanel.prepend(panel);
}

function restoreLegacySurface() {
  document.getElementById("parameterPanel")?.remove();
  for (const metadata of Object.values(PARAMETER_UI)) {
    if (metadata.legacyId) setLegacyVisibility(metadata.legacyId, false);
    if (metadata.hideLegacyId) setLegacyVisibility(metadata.hideLegacyId, false);
  }
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  let currentManifest = null;
  window.addEventListener("rigstudio:manifestready", (event) => {
    currentManifest = event.detail?.manifest || null;
    renderParameterPanel(currentManifest, event.detail?.parameters || {});
  });
  window.addEventListener("rigstudio:parameterchange", (event) => {
    const { id, value } = event.detail || {};
    if (!id || !currentManifest) return;
    for (const input of document.querySelectorAll(`[data-parameter-id="${id}"] input`)) {
      input.value = String(value);
    }
    for (const output of document.querySelectorAll(`[data-parameter-value="${id}"]`)) {
      output.textContent = formatValue(value);
    }
  });
  window.addEventListener("rigstudio:manifestclear", () => {
    currentManifest = null;
    restoreLegacySurface();
  });
}
