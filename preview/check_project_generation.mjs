import assert from "node:assert/strict";
import {
  PROJECT_GENERATION_FORMAT, PROJECT_GENERATION_POINTER, PROJECT_GENERATION_VERSION,
  createProjectGenerationRecord, readProjectGeneration,
} from "./project-generation.mjs";

const textFile = (text) => ({
  async text() { return text; },
  async arrayBuffer() { return new TextEncoder().encode(text).buffer; },
});
const generationId = "g-20261019-abc123";
const committedFiles = new Map([
  ["project.json", "{\"format\":\"portrait-rig-project\",\"version\":1}\n"],
  ["source/assembly_reference.json", "{\"kind\":\"rig\"}\n"],
  ["generated/portrait_rig_manifest.json", "{\"parts\":[]}\n"],
  ["authoring/deformers.json", "{\"upper_torso\":{}}\n"],
  ["authoring/meta.json", "{\"version\":1}\n"],
  ["portrait_rig_manifest.json", "{\"parts\":[]}\n"],
]);
const record = await createProjectGenerationRecord(generationId, committedFiles, "1792386000000000000");
assert.equal(record.format, PROJECT_GENERATION_FORMAT);
assert.equal(record.version, PROJECT_GENERATION_VERSION);

const root = "Character.rigproject/";
const files = [
  { path: `${root}${PROJECT_GENERATION_POINTER}`, value: textFile(JSON.stringify(record)) },
  { path: `${root}project_generations/${generationId}/complete.json`, value: textFile(JSON.stringify(record)) },
  ...[...committedFiles].map(([path, text]) => ({
    path: `${root}project_generations/${generationId}/${path}`, value: textFile(text),
  })),
];
const loaded = await readProjectGeneration(files, `${root}${PROJECT_GENERATION_POINTER}`);
assert.equal(loaded.rootPrefix, root);
assert.equal(loaded.generationPrefix, `${root}project_generations/${generationId}/`);
assert.equal(loaded.files.size, committedFiles.size);

const corrupted = files.map((entry) => entry.path.endsWith("authoring/deformers.json")
  ? { ...entry, value: textFile("{}\n") } : entry);
await assert.rejects(() => readProjectGeneration(corrupted, `${root}${PROJECT_GENERATION_POINTER}`),
  /checksum mismatch/);
const interrupted = files.filter((entry) => !entry.path.endsWith("complete.json"));
await assert.rejects(() => readProjectGeneration(interrupted, `${root}${PROJECT_GENERATION_POINTER}`),
  /incomplete/);
const badPointer = files.map((entry) => entry.path.endsWith(PROJECT_GENERATION_POINTER)
  ? { ...entry, value: textFile(JSON.stringify({ ...record, generation: "../escape" })) } : entry);
await assert.rejects(() => readProjectGeneration(badPointer, `${root}${PROJECT_GENERATION_POINTER}`),
  /malformed/);

console.log("Project generation checks passed (commit marker, checksums, interrupted and corrupt generations)");
