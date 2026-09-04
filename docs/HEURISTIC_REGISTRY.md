# AutoRig Heuristic Registry

This registry separates authored contracts from AutoRig implementation choices.
Changing an `ACTIVE` value requires a regression update; `EXPERIMENTAL` values
must not silently become defaults.

| Heuristic | Status | Current rule / value | Evidence and guard |
| --- | --- | --- | --- |
| `contour_candidate_tags` | EXPERIMENTAL | face/neck/hair/eyelash/eyebrow candidates are opt-in through `contour_tags` | Mesh QA compares contour against the grid baseline |
| `island_policy=separate` | ACTIVE | disconnected alpha components are triangulated independently | `connect_nearest` is the only explicit bridge mode; `reject` hard-fails the contour candidate |
| motion-aware density | ACTIVE | fine for eyes/gradients/local soft fields, medium for head turn surfaces, coarse otherwise | density tests and frozen topology hashes |
| tip prominence | EXPERIMENTAL | bottom-boundary prominence relative to component median; configurable threshold | `detect_tips()` returns score and deterministic ordering |
| tip minimum separation | EXPERIMENTAL | default 12 px | prevents anti-aliased neighboring pixels becoming separate tips |
| curtain column count | EXPERIMENTAL | default 5 columns | partition QA requires every vertex's weights to sum to 1 |
| coarse gaze fallback | ACTIVE | independent iris is preferred; coarse eye fallback is degraded | rig preflight reports degraded capability when independent iris is absent |
| derived eyewhite fallback | ACTIVE | only when canonical `eyewhite` is missing and rest-fidelity/confidence checks pass | provenance is recorded; failed derivation leaves the canonical head untouched |
| clip-mask crop UV | ACTIVE | source alpha is sampled from the source part's canvas `xyxy` crop | outside-source pixels are zeroed in the fragment shader |
| boundary stitch tolerance | ACTIVE | skip correction when member spread is within `tolerance_px` | avoids changing a matching rest pose; N-way weighted average otherwise |
| P2 spring integrator | ACTIVE | semi-implicit Euler at `update_hz=60` | fixed-step parity and non-finite rollback tests |
| strand phase offset | EXPERIMENTAL | deterministic SHA-256-derived offset, ±0.01 | stable per `strand_id`; no global randomness |
| torso response profiles | EXPERIMENTAL | `soft`, `firm_bounce`, `springy` material presets | explicit profile selection; no default manifest activation yet |

## Status vocabulary

- `ACTIVE`: shipped default or required safety rule, covered by regression.
- `EXPERIMENTAL`: opt-in or tunable heuristic; results must remain observable.
- `REJECTED`: tested and intentionally not used.
- `REPLACED`: superseded by a named rule; retained for historical traceability.

P2 drivers remain opt-in until they are connected to the manifest/runtime path.
