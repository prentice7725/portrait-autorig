"use strict";

export const PROJECT_GENERATION_FORMAT = "portrait-rig-project-generation";
export const PROJECT_GENERATION_VERSION = 1;
export const PROJECT_GENERATION_POINTER = "project-generation.json";

async function bytesOf(value) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (typeof value === "string") return new TextEncoder().encode(value);
  if (value?.arrayBuffer) return new Uint8Array(await value.arrayBuffer());
  if (value?.text) return new TextEncoder().encode(await value.text());
  throw new TypeError("project generation file must be text, bytes, or a File");
}

export async function sha256Hex(value) {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle?.digest) throw new Error("SHA-256 is unavailable in this browser context");
  const digest = await subtle.digest("SHA-256", await bytesOf(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function createProjectGenerationRecord(generation, files, createdAtNs = null) {
  const checksums = {};
  for (const [path, contents] of files) {
    if (!path || path.startsWith("/") || /^[A-Za-z]:/.test(path)
        || path.split("/").some((piece) => !piece || piece === "." || piece === ".."))
      throw new Error(`unsafe project generation path: ${path}`);
    checksums[path] = await sha256Hex(contents);
  }
  return {
    format: PROJECT_GENERATION_FORMAT,
    version: PROJECT_GENERATION_VERSION,
    generation: String(generation),
    created_at_ns: String(createdAtNs ?? `${Date.now()}000000`),
    files: checksums,
  };
}

function sameRecord(left, right) {
  if (["format", "version", "generation", "created_at_ns"].some((key) => left?.[key] !== right?.[key]))
    return false;
  const leftFiles = left?.files || {}, rightFiles = right?.files || {};
  const leftKeys = Object.keys(leftFiles).sort(), rightKeys = Object.keys(rightFiles).sort();
  return leftKeys.length === rightKeys.length
    && leftKeys.every((key, index) => key === rightKeys[index] && leftFiles[key] === rightFiles[key]);
}

export async function readProjectGeneration(files, pointerPath = PROJECT_GENERATION_POINTER) {
  const byPath = new Map(files.map((file) => [String(file.path), file.value]));
  const pointerValue = byPath.get(pointerPath);
  if (!pointerValue) throw new Error("project generation pointer is missing");
  let record;
  try { record = JSON.parse(await pointerValue.text()); }
  catch (error) { throw new Error(`project generation pointer is invalid: ${error.message}`); }
  if (record?.format !== PROJECT_GENERATION_FORMAT
      || record.version !== PROJECT_GENERATION_VERSION
      || !/^[A-Za-z0-9_-]+$/.test(String(record.generation || ""))
      || !record.files || typeof record.files !== "object" || Array.isArray(record.files))
    throw new Error("unsupported or malformed project generation pointer");
  for (const required of ["project.json", "source/assembly_reference.json",
    "generated/portrait_rig_manifest.json", "authoring/meta.json", "portrait_rig_manifest.json"])
    if (!Object.hasOwn(record.files, required)) throw new Error(`project generation is missing ${required}`);

  const rootPrefix = pointerPath.slice(0, -PROJECT_GENERATION_POINTER.length);
  const generationPrefix = `${rootPrefix}project_generations/${record.generation}/`;
  const completePath = `${generationPrefix}complete.json`;
  const completeValue = byPath.get(completePath);
  if (!completeValue) throw new Error(`project generation is incomplete: ${record.generation}`);
  let complete;
  try { complete = JSON.parse(await completeValue.text()); }
  catch (error) { throw new Error(`project generation marker is invalid: ${error.message}`); }
  if (!sameRecord(record, complete)) throw new Error("project generation pointer and completion marker disagree");

  const generationFiles = new Map();
  for (const [relative, expectedDigest] of Object.entries(record.files)) {
    if (!relative || relative.startsWith("/") || /^[A-Za-z]:/.test(relative)
        || relative.split("/").some((piece) => !piece || piece === "." || piece === ".."))
      throw new Error(`unsafe path in project generation record: ${relative}`);
    const value = byPath.get(`${generationPrefix}${relative}`);
    if (!value) throw new Error(`project generation file is missing: ${relative}`);
    const actualDigest = await sha256Hex(value);
    if (actualDigest !== expectedDigest) throw new Error(`project generation checksum mismatch: ${relative}`);
    generationFiles.set(relative, value);
  }
  return { record, rootPrefix, generationPrefix, files: generationFiles };
}
