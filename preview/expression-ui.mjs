/* P6.2 manifest-driven expression catalog adapter.
 *
 * This module owns only the Preview buttons. Expression meaning remains in
 * the resolved manifest and the controller/runtime lifecycle; a rig without
 * expression_presets gets no empty or misleading expression section.
 */

"use strict";

export const EXPRESSION_UI_VERSION = "P6.2";

function labelFor(id, preset) {
  const metadata = preset?.metadata || {};
  return String(metadata.label || metadata.name || preset?.label || id)
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function expressionCatalog(manifest) {
  const presets = manifest?.expression_presets;
  if (!presets || typeof presets !== "object" || Array.isArray(presets)) return [];
  return Object.entries(presets)
    .filter(([, preset]) => preset && typeof preset === "object"
      && preset.variants && typeof preset.variants === "object")
    .map(([id, preset]) => ({
      id: String(id), label: labelFor(id, preset),
      description: preset.metadata?.description || preset.description || "",
      order: Number(preset.metadata?.order ?? preset.order ?? Number.MAX_SAFE_INTEGER),
    }))
    .sort((a, b) => (Number.isFinite(a.order) ? a.order : Number.MAX_SAFE_INTEGER)
      - (Number.isFinite(b.order) ? b.order : Number.MAX_SAFE_INTEGER)
      || a.id.localeCompare(b.id));
}

function emit(type, detail = {}) {
  if (typeof window === "undefined" || typeof CustomEvent === "undefined") return;
  window.dispatchEvent(new CustomEvent(type, { detail }));
}

export function renderExpressionCatalog(manifest, document) {
  const root = document?.getElementById?.("expressionCatalog");
  const buttons = document?.getElementById?.("expressionButtons");
  const release = document?.getElementById?.("releaseExpression");
  const status = document?.getElementById?.("expressionStatus");
  if (!root || !buttons) return [];
  const entries = expressionCatalog(manifest);
  buttons.replaceChildren?.();
  root.hidden = entries.length === 0;
  root.style.display = entries.length === 0 ? "none" : "";
  root.setAttribute("aria-hidden", String(entries.length === 0));
  if (entries.length) root.removeAttribute("aria-hidden");
  if (release) release.hidden = entries.length === 0;
  if (status) status.textContent = entries.length ? "Neutral" : "No expressions in this rig";
  for (const entry of entries) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = entry.label;
    button.dataset.expressionId = entry.id;
    button.setAttribute("aria-pressed", "false");
    if (entry.description) button.title = entry.description;
    button.addEventListener("click", () => emit("rigstudio:setexpression", { id: entry.id }));
    buttons.appendChild(button);
  }
  if (release && !release.dataset.expressionBound) {
    release.dataset.expressionBound = "true";
    release.addEventListener("click", () => emit("rigstudio:releaseexpression"));
  }
  return entries;
}

export function bindExpressionUi({ document, window } = {}) {
  const targetWindow = window || globalThis.window;
  if (!document || !targetWindow?.addEventListener) return;
  targetWindow.addEventListener("rigstudio:manifestready", (event) => {
    renderExpressionCatalog(event.detail?.manifest || null, document);
  });
  targetWindow.addEventListener("rigstudio:expressionchange", (event) => {
    const active = event.detail?.id || null;
    for (const button of document.querySelectorAll?.("[data-expression-id]") || [])
      button.setAttribute("aria-pressed", String(button.dataset.expressionId === active));
    const status = document.getElementById?.("expressionStatus");
    if (status) status.textContent = active ? `Active: ${active}` : "Neutral";
  });
  targetWindow.addEventListener("rigstudio:expressionerror", (event) => {
    const status = document.getElementById?.("expressionStatus");
    if (status) status.textContent = `Expression unavailable: ${event.detail?.message || "invalid preset"}`;
  });
}

if (typeof document !== "undefined" && typeof window !== "undefined")
  bindExpressionUi({ document, window });
