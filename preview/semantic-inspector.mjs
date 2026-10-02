/*
 * P4 semantic tree + contextual inspector.
 *
 * This module owns only Edit information architecture. Existing R2/R3
 * controls stay in their original DOM blocks, so their runtime listeners and
 * save paths remain untouched while irrelevant contexts are hidden.
 */

const CONTEXTS = Object.freeze({
  chest: {
    label: "Chest",
    description: "Author the generated chest shape and calibrate its physics.",
  },
  eyes: {
    label: "Eyes",
    description: "Inspect eyelid geometry and gaze.",
  },
  mouth: {
    label: "Mouth",
    description: "Author the layer-free mouth form and its keyforms.",
  },
  hair: {
    label: "Hair",
    description: "Inspect detected hair zones, roots, tips, and supported layers.",
  },
  raw: {
    label: "Raw parts",
    description: "Advanced read-only manifest inspection. Runtime part toggles remain in QA.",
  },
});

const tree = document.getElementById("semanticTree");
const editPanel = document.getElementById("editPanel");
const editIntro = editPanel?.querySelector(".mode-intro");
const buttons = [...(tree?.querySelectorAll("[data-context]") || [])];
const groups = [...(editPanel?.querySelectorAll(".mode-group[data-context]") || [])];
const rawGroup = groups.find((group) => group.dataset.context === "raw");
let selectedContext = "chest";
let rawSummary = null;
let partTree = null;

// Preserve producer semantics: never infer anatomical sides from image positions.
export function manifestPartEntries(manifest) {
  return (Array.isArray(manifest?.parts) ? manifest.parts : []).map((part, index) => ({
    index, name: String(part.name || "unnamed part"), tag: String(part.tag || "untyped"),
  }));
}

export function manifestContextCapabilities(manifest) {
  const entries = manifestPartEntries(manifest);
  return {
    chest: Boolean(manifest?.motion?.upper_torso_parametric_deformer) || entries.some(entry => /^(upper_torso|torso|chest|bust|topwear)$/.test(entry.tag)),
    eyes: entries.some(entry => /^(eye($|_)|eyewhite|eyelid|iris|lash)/.test(entry.tag)),
    mouth: Boolean(manifest?.motion?.mouth_form?.enabled),
    hair: entries.some(entry => /hair/.test(entry.tag)),
    raw: true,
  };
}

function renderPartTree(manifest) {
  partTree?.remove();
  if (!tree) return;
  partTree = document.createElement("div");
  partTree.className = "tree-group";
  const heading = document.createElement("h2");
  heading.textContent = "실제 이미지 부위";
  partTree.appendChild(heading);
  for (const entry of manifestPartEntries(manifest)) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${entry.name} · ${entry.tag}`;
    button.addEventListener("click", () => {
      setContext("raw");
      if (summary) summary.textContent = `${entry.name} · ${entry.tag} — 읽기 전용. 전신 팔다리 관절/IK 리깅은 아직 지원하지 않습니다.`;
    });
    partTree.appendChild(button);
  }
  tree.appendChild(partTree);
  const supported = manifestContextCapabilities(manifest);
  for (const button of buttons) {
    button.disabled = !supported[button.dataset.context];
    button.title = button.disabled ? "이 프로젝트에서 편집 가능한 기능이 없습니다" : "";
  }
  if (!supported[selectedContext]) setContext("raw");
}

function createInspectorSummary() {
  if (!editPanel || !editIntro) return null;
  const summary = document.createElement("div");
  summary.id = "editInspectorSummary";
  summary.className = "inspector-summary";
  summary.setAttribute("aria-live", "polite");
  editIntro.after(summary);
  return summary;
}

const summary = createInspectorSummary();

function renderRawSummary(manifest = null) {
  if (!rawGroup) return;
  rawSummary?.remove();
  rawSummary = document.createElement("div");
  rawSummary.id = "editRawPartsSummary";
  rawSummary.className = "raw-parts-summary";
  const parts = Array.isArray(manifest?.parts) ? manifest.parts : [];
  const meta = document.createElement("p");
  meta.className = "meta";
  meta.textContent = parts.length
    ? `${parts.length} manifest parts · read-only advanced view`
    : "No manifest parts loaded";
  rawSummary.appendChild(meta);
  if (parts.length) {
    const list = document.createElement("ul");
    list.className = "raw-parts-list";
    for (const part of parts) {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = String(part.name || "unnamed part");
      const tag = document.createElement("span");
      tag.className = "meta";
      tag.textContent = String(part.tag || "untyped");
      item.append(name, tag);
      list.appendChild(item);
    }
    rawSummary.appendChild(list);
  }
  rawGroup.appendChild(rawSummary);
}

function setContext(context) {
  const next = CONTEXTS[context] ? context : "chest";
  selectedContext = next;
  for (const button of buttons) {
    const selected = button.dataset.context === next;
    button.setAttribute("aria-current", String(selected));
  }
  for (const group of groups) group.hidden = group.dataset.context !== next;
  const copy = CONTEXTS[next];
  if (summary) {
    summary.innerHTML = "";
    const title = document.createElement("strong");
    title.textContent = copy.label;
    const description = document.createElement("span");
    description.textContent = copy.description;
    summary.append(title, description);
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("rigstudio:contextchange", {
      detail: { context: next },
    }));
  }
}

for (const button of buttons) {
  button.addEventListener("click", () => setContext(button.dataset.context));
}

if (typeof window !== "undefined") {
  window.addEventListener("rigstudio:manifestready", (event) => {
    renderRawSummary(event.detail?.manifest || null);
    renderPartTree(event.detail?.manifest || null);
  });
  window.addEventListener("rigstudio:manifestclear", () => {
    renderRawSummary(null);
    renderPartTree(null);
  });
}

renderRawSummary(null);
setContext(selectedContext);

export { CONTEXTS, setContext };
