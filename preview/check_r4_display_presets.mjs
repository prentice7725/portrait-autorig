// R4 display contract check: presets change only the presentation viewport
// and preserve the logical manifest canvas dimensions.
const controls = new Map();
const control = (id) => {
  if (!controls.has(id)) controls.set(id, { id, checked: false, value: "", textContent: "",
    innerHTML: "", style: {}, classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {}, append() {}, appendChild() {} });
  return controls.get(id);
};
globalThis.document = { getElementById: control, createElement: (tag) => control(tag), addEventListener() {} };
globalThis.performance = { now: () => 0 };
globalThis.requestAnimationFrame = () => {};
globalThis.location = { search: "" };
globalThis.fetch = async () => { throw new Error("no fetch"); };

const Runtime = await import(new URL("runtime.mjs", import.meta.url));
Runtime.state.manifest = { canvas: { width: 768, height: 1024 } };
Runtime.state.canvasW = 768;
Runtime.state.canvasH = 1024;
if (Runtime.applyDisplayPreset("game_portrait") !== "game_portrait")
  throw new Error("R4 game portrait preset was not selected");
const wrap = control("canvasWrap");
const gl = control("gl");
if (wrap.style.width !== "360px" || wrap.style.height !== "640px")
  throw new Error("game portrait target viewport is not 360x640");
if (gl.style.width !== "360px" || gl.style.height !== "480px")
  throw new Error("game portrait content was not aspect-fit");
if (Runtime.state.canvasW !== 768 || Runtime.state.canvasH !== 1024)
  throw new Error("R4 mutated logical canvas dimensions");

Runtime.applyDisplayPreset("desk_portrait");
if (wrap.style.width !== "720px" || wrap.style.height !== "1280px")
  throw new Error("desk portrait target viewport is not 720x1280");
Runtime.applyDisplayPreset("full");
if (wrap.style.width !== "768px" || wrap.style.height !== "1024px")
  throw new Error("100% preset did not restore full resolution");
console.log("R4 display preset checks passed");
