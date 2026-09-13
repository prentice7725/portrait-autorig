/*
 * Rig Studio P1 shell.
 *
 * This module only owns information architecture: it moves the existing
 * controls into Preview/Edit/QA surfaces and toggles visibility.  Runtime
 * deformation and all legacy control ids remain in runtime.mjs so the current
 * QA harness keeps one event path.
 */

const panel = document.getElementById("panel");
const topStatus = document.getElementById("topStatus");

const modePanels = Object.fromEntries(["preview", "edit", "qa"].map((mode) => {
  const section = document.createElement("section");
  section.className = "mode-panel";
  section.dataset.modePanel = mode;
  section.id = `${mode}Panel`;
  panel.appendChild(section);
  return [mode, section];
}));

function intro(mode, title, description) {
  const element = document.createElement("div");
  element.className = "mode-intro";
  element.innerHTML = `<strong>${title}</strong><span>${description}</span>`;
  if (mode === "edit") {
    const status = document.createElement("span");
    status.id = "editLifecycleStatus";
    status.className = "mode-status";
    status.setAttribute("aria-live", "polite");
    status.textContent = "Edit pose inactive";
    element.appendChild(status);
  }
  modePanels[mode].appendChild(element);
}

intro("preview", "미리보기", "게임 크기 런타임에서 캐릭터 동작을 확인합니다.");
intro("edit", "편집", "안정된 authoring pose에서 generated base를 보정합니다.");
intro("qa", "검증", "런타임, 물리, geometry와 regression 결과를 확인합니다.");

function blockFor(id) {
  const element = document.getElementById(id);
  if (!element) return null;
  if (element.matches("input, select")) return element.closest("label") || element;
  if (element.matches("button")) return element.closest(".row") || element;
  return element;
}

function move(id, target) {
  const block = blockFor(id);
  if (!block || block.closest(".mode-panel")) return;
  target.appendChild(block);
}

const groups = {
  preview: [
    { title: "Runtime", ids: ["autoIdle", "doBlink", "doBreathe", "breathAmp"] },
    { title: "Expression", ids: ["packmeta", "expressionCatalog", "audioTest", "mouthOpen"] },
    { title: "Gaze", ids: ["gazeX", "gazeY", "followCursor", "followCursorHint"] },
    { title: "Head", ids: ["turnX", "turnY", "tilt"] },
  ],
  edit: [
    { title: "Hair", label: "헤어", ids: ["r5HairMeta", "showR5HairZones", "showR5HairRoots", "r5HairLayer"] },
    { title: "Chest Physics", label: "가슴 물리", ids: ["r3Meta", "r3Preset", "r3ApplyPreset", "r3Frequency", "r3Damping", "r3RangeX", "r3RangeY", "r3LagX", "r3LagY", "r3MaxDisplacement", "r3Save", "r3Reset"] },
    { title: "Chest Shape", label: "가슴 형태", ids: ["bustYMinus", "bustNeutral", "bustYPlus", "bustXMinus", "bustXPlus", "showP3Cage", "r2Meta", "r2Pose", "r2EditTarget", "r2EditMode", "r2Save", "r2Reset", "r2Download"] },
    { title: "Eyes", label: "눈", ids: ["lidLine", "lidThick", "winkL", "winkR", "blinkNow"] },
    { title: "Raw Parts (Advanced)", label: "원본 파츠 (고급)", ids: [] },
  ],
  qa: [
    { title: "Runtime QA", label: "런타임 QA", ids: ["profiler", "bodySway", "chestInertia", "asymmetry", "kickX", "kickY", "chestImpulseY", "stopBody", "breathOnly", "inertiaOnly", "resetMotion", "resetQa", "motionGraph"] },
    { title: "Chest Diagnostics", label: "가슴 진단", ids: ["softMeta", "chestCalibration", "chest1px", "chest2px", "chest4px", "doSoftMorph", "softStrength", "softHoriz", "softVert", "softRegion"] },
    { title: "Chest Basis", label: "가슴 basis", ids: ["chestBasisMeta", "poseQPlus4", "poseQMinus4", "poseVPlus12", "poseVMinus12", "sideBoth", "sideLeft", "sideRight", "gainVolume", "gainCarrier", "gainSag", "gainFollow", "gainShearX", "gainShearY", "gainCompression", "resetShapeQA", "showChestBasis", "chestBasisSelect", "chestTrajectory"] },
    { title: "Parametric Warp Diagnostics", label: "파라메트릭 변형 진단", ids: ["p3Meta", "qaTurnX", "qaTurnY", "qaBlinkNow", "showP3Heatmap", "showP3Influenced", "showP3Locks", "showP3Occluders"] },
    { title: "Expression Diagnostics", label: "표정 진단", ids: ["useArt", "doTalk"] },
    { title: "Experiments", label: "실험", ids: ["shell", "ghost", "neckMode", "collar", "wire"] },
    { title: "Parts / Manifest", label: "파츠 / Manifest", ids: ["parts"] },
  ],
};

for (const [mode, modeGroups] of Object.entries(groups)) {
  for (const group of modeGroups) {
    const section = document.createElement("section");
    section.className = "mode-group";
    const context = {
      Hair: "hair",
      "Chest Physics": "chest",
      "Chest Shape": "chest",
      Eyes: "eyes",
      "Raw Parts (Advanced)": "raw",
    }[group.title];
    if (context) section.dataset.context = context;
    const title = document.createElement("h2");
    title.textContent = group.label || group.title;
    section.appendChild(title);
    modePanels[mode].appendChild(section);
    for (const id of group.ids) move(id, section);
  }
}

// The original headings and prose are intentionally kept in the source as a
// migration aid, but the rebuilt surfaces provide their own concise context.
for (const child of [...panel.children]) {
  if (child.matches("h2, .hint")) child.hidden = true;
}

// Move runtime-owned shared status elements into the top bar without creating
// duplicate ids.  Runtime listeners continue to use the original ids.
for (const id of ["runmeta", "physicsWarning", "r4DisplayMeta"]) {
  const element = document.getElementById(id);
  if (element) topStatus.appendChild(element);
}
const preset = document.getElementById("r4DisplayPreset");
if (preset) topStatus.appendChild(preset.closest("label") || preset);
for (const id of ["topRunMeta", "topPhysicsWarning", "topR4DisplayMeta", "topR4DisplayPreset"]) {
  document.getElementById(id)?.closest("label")?.remove();
  document.getElementById(id)?.remove();
}

function setMode(mode) {
  const next = modePanels[mode] ? mode : "preview";
  const previous = document.body.dataset.mode || "preview";
  document.body.dataset.mode = next;
  for (const [name, section] of Object.entries(modePanels)) {
    section.classList.toggle("is-active", name === next);
  }
  for (const tab of document.querySelectorAll("[data-mode]")) {
    const selected = tab.dataset.mode === next;
    tab.setAttribute("aria-pressed", String(selected));
  }
  window.dispatchEvent(new CustomEvent("rigstudio:modechange", {
    detail: { mode: next, previousMode: previous },
  }));
}

for (const tab of document.querySelectorAll(".mode-tab")) {
  tab.addEventListener("click", () => setMode(tab.dataset.mode));
}

const runmeta = document.getElementById("runmeta");
const topProject = document.getElementById("topProject");
if (runmeta && topProject) {
  const syncProject = () => {
    const runLine = runmeta.querySelector(":scope > div:nth-child(2)")?.textContent?.trim();
    const firstLine = runmeta.querySelector(":scope > div")?.textContent?.trim();
    const value = runLine || firstLine || runmeta.textContent.trim();
    topProject.textContent = value && value !== "no run loaded"
      ? value.replace(/^run\s+/i, "") : "No project loaded";
  };
  new MutationObserver(syncProject).observe(runmeta, { childList: true, subtree: true, characterData: true });
  syncProject();
}

setMode("preview");

export { setMode };
