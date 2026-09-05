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
| `body_sway` synthesis | ACTIVE | deterministic mixed-frequency pixel-space waveform; no per-frame randomness | primary deformer + fixed-tick motion parity |
| body_sway amplitudes | EXPERIMENTAL | compiler QA seeds 1.8px/1.2px | motion graph and rest-fidelity checks |
| body_sway periods | EXPERIMENTAL | compiler QA seeds 7.3s/5.9s; keep 5.5–9.0s | 30/60/120 FPS parity and idle loop review |
| `upper_torso_driver.model` | ACTIVE | new compiler output uses `inertial_relative_v2`; P2.2 manifests remain `inertial_relative_v1`, missing model remains `legacy_target_v1` | explicit model field and legacy-load regression |
| physical spring state in px | ACTIVE | v2 q/v are px and px/s; no hidden stiffness-to-morph scaling | 1/2/4px response probes |
| `inertial_relative_v2` semantics | ACTIVE | frequency/damping-ratio spring with explicit pixel equilibrium and external acceleration | unit validation and runtime parity |
| velocity relative-lag target | ACTIVE | body velocity × lag seconds becomes a bounded relative px target; acceleration remains a small directional kick | idle/Body Kick follow-through and pixel response QA |
| torso lag envelope | EXPERIMENTAL | x 0.12s, y 1.4s; idle cap 5.0px, kick cap 12.0px (raised from 0.25s/0.8px/2.0px so idle sway and Body Kick read as a visible bust jiggle instead of sub-pixel motion) | runtime motion review and geometry gates |
| natural frequency / damping defaults | EXPERIMENTAL | profile seeds soft 1.8Hz/.75, firm 2.4Hz/.55, springy 2.2Hz/.35 | calibration harness and settle envelope |
| geometry distribution gains | EXPERIMENTAL | physical q maps via horizontal .45 / vertical 1.0 defaults | chest geometry parity and lock probes |
| 1/2/4px QA calibration | ACTIVE QA CONTRACT | measured primary probe must remain within ±15% | `check_physical_response.mjs` |
| compiled topwear QA probes | ACTIVE QA CONTRACT | probes are selected from the compiled mesh's authored lobe/lock weights; no one-vertex surrogate | `check_physical_response.mjs`, `check_chest_geometry_parity.mjs` |
| body-kick follow-through gate | ACTIVE QA CONTRACT | body-stop interval requires ≥0.15px chest follow-through and final ≤0.05px settle | `check_body_kick_pipeline.mjs` |
| runtime geometry FPS parity | ACTIVE QA CONTRACT | the real Body Kick pipeline must keep final probe coordinates within 0.02px at 30/60/120 FPS | `check_motion_framerate_parity.mjs` |
| inertia gains / velocity drag | EXPERIMENTAL | explicit X/Y coefficients; acceleration is external force, never equilibrium | inertial kick and breath-only regressions |
| L/R material asymmetry | EXPERIMENTAL | tiny deterministic stiffness/damping/mass scales when omitted by a new inertial manifest | independent lobe output and bounded displacement clamps |
| settle_gain | EXPERIMENTAL | lower-lobe vertical response uses spring velocity × settle gain | lock-preservation and bounded settle tests |
| hard-morph QA slider maximum | ACTIVE | 24px horizontal / 12px vertical; QA-only override | canonical manifest remains unchanged |
| authored lobe adaptive refinement | ACTIVE | 18px cell only inside Composer-authored lobe union; outer topwear grid unchanged | topology hash, lock preservation, rest-reference parity |
| lock-zone geometry basis | ACTIVE | `center_lock`/`neckline_lock`/center transition are always fractions of the topwear crop's own width/height, never of the canvas -- only lobe center/radius use the canvas-normalized basis when `coordinate_space: canvas_normalized` | `buildSoftMorphWeights`; regression: a `canvas_normalized` region whose lobes sit closer to the body midline than the transition band no longer crushes lobe weight everywhere (previously capped near 0.35 max weight on affected assets, e.g. A002) |
| fixed-tick catch-up cap | ACTIVE | at most 4 physics ticks per render frame | prevents spiral-of-death; framerate parity check |
| inertial safety clamps | ACTIVE | force ±4 (legacy v1 model), relative displacement ±`max_displacement_px` (v2 default now 16px, raised from 4px for a visible jiggle), lobe velocity ±12; input acceleration/impulse are bounded | deterministic clamp diagnostics and rollback |

## Status vocabulary

- `ACTIVE`: shipped default or required safety rule, covered by regression.
- `EXPERIMENTAL`: opt-in or tunable heuristic; results must remain observable.
- `REJECTED`: tested and intentionally not used.
- `REPLACED`: superseded by a named rule; retained for historical traceability.

P2 drivers are connected to the manifest/runtime path but remain opt-in until
production corpus tuning is frozen.
