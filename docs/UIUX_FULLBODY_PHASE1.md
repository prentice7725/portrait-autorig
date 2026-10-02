# UIUX improvement — full-body-aware phase 1

Implementation follows the approved 2026-10-02 UIUX v0.2 proposal without
changing the manifest schema or weakening the portrait compiler contract.

## Delivered

- Project dirty status includes mouth edits and unsaved persistence changes.
  Undo/redo also mark persistence dirty. QA-only probes do not themselves mark
  authored data dirty or become overrides through Project Save.
- Project, chest and mouth Save buttons share the project-save entry point;
  Ctrl/Cmd+S also uses that entry point.
- A folder save is successful only after all five files close successfully.
  Failure leaves the draft dirty and never silently falls back to a download.
  Edits during a save remain dirty; overlapping saves are ignored. The captured
  folder handle prevents subsequent files being written to another opened
  project's directory.
- Without a writable folder, authoring.json is downloaded and explicitly
  reported as downloaded, not saved to the project folder. Dirty state remains.
- Eyes and Mouth have separate contextual inspector groups.
- Actual manifest parts appear in a read-only part list. Names and semantic tags
  are preserved; no segmentation or anatomical-left/right inference is invented.
  Unsupported static contexts are disabled. A single unclassified full-body
  part remains a single part; arm/leg entries do not gain fake joint controls.
- Small-screen Edit retains its part selector; the top bar can wrap.

## Validation and boundaries

`node preview/check_project_persistence.mjs` exercises real runtime listeners
with mocked browser/file APIs: mouth dirty state, downloads, partial-write
failure, successful saves, concurrent mouth/calibration edits and QA isolation.
`node preview/check_fullbody_inspector.mjs` covers real-part inventory,
unclassified tall-image capability handling and independent eye/mouth contexts.
Run these alongside all existing `preview/check_*.mjs` and Python tests.

Folder writes are sequential, not an atomic multi-file transaction. A disk
failure can leave a partial folder update; the visible failure and dirty draft
require retry. There is no rollback or claim that a download has been imported.

Current portrait head/face compiler requirements remain unchanged. This phase
does not implement full-body skeletons, arm/leg articulation, IK or walking.
Real-browser visual verification is still needed in the supported browsers;
Node checks do not certify browser layout or filesystem permission prompts.
