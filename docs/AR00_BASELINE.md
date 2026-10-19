# AR00 baseline and regression inventory

Baseline source revision: `f1b393e79e5b89a0a7cc1f28b706cb15980b8af6`.

This inventory separates repeatable synthetic checks from portrait art that
still needs a fixed, approved fixture. It does not treat a generated example
or a structural check as evidence of visual quality on real art.

## Available fixtures

| Fixture | Current use | Evidence boundary |
|---|---|---|
| `preview/qa_compiled_topwear.mjs` + `preview/qa_chest_p3.mjs` | Cage/keyform deformation, neutral restoration, authoring override isolation | Synthetic topwear only |
| `preview/fixtures/p2-parameter-manifest.json` | Parameter panel and manifest input shape | Parameter UI contract only |
| `tests/test_project.py` helper manifest and RGBA arrays | Project round trip, source revision, authoring binding and generated-base separation | Synthetic project data only |
| `preview/check_project_persistence.mjs` in-memory file-system model | Save failure, save-time edits, and dirty state | File API behavior is mocked |

The repository does not currently contain approved, fixed real-art captures for
front portrait, asymmetric/three-quarter portrait, glasses/long hair, donor and
no-donor expressions, or separated full-body parts. Those fixtures remain
pending with source permission and provenance. No generative image run is part
of this baseline.

## Contracts pinned by the current checks

- Generated base data remains unchanged when authoring overrides are resolved.
- Neutral pose restores exact rest geometry in the synthetic cage fixture.
- One key hold, one numeric commit, or one pointer gesture is one Undo item.
- Escape, pointer cancellation, and a no-op do not create an Undo item.
- QA-only probes do not enter authoring persistence.
- An interrupted generation is ignored until its completion record and root
  commit pointer validate; checksum errors are reported rather than defaulted.
- Reduced motion follows the OS in `system`, and explicit `reduce`/`full`
  preferences continue to override later OS changes.

## Evidence still pending

- Real portrait fixtures with recorded source hash, permission/provenance, and
  before/after captures.
- Browser verification at 100/125/150% and narrow viewport sizes, including
  actual focus movement when switching modes.
- Python test-suite execution in an environment with the declared test and
  image-processing dependencies.
- Process interruption tests against the browser's real File System Access
  implementation and the supported operating systems.

## Current implementation run

On 2026-10-19, the following Node checks passed: UI mode, Edit lifecycle,
authoring history, project persistence, full-body inspector, mouth form,
physics, frame-rate parity, rig controller, expression lifecycle, mesh quality,
R2 authoring, accessibility, and project-generation validation. Python
`compileall` and a direct project-generation save/reload smoke check also
passed. The `pytest` suite could not start because `pytest` is not installed;
normal package import also requires OpenCV (`cv2`), which is absent in this
environment. No browser or real-art visual review was run.
