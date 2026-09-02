# portrait-autorig

`Production-ready Portrait Bundle → derived rig parts + animated portrait rig`

This repository consumes the versioned file contract produced by
[`seethrough-portrait`](https://github.com/prentice7725/seethrough-portrait).
It has no runtime or Python dependency on See-Through, torch, or diffusers.

## Desktop GUI (recommended)

On Windows, clone/install the project and then double-click:

```text
portrait_autorig_gui.pyw
```

The launcher exposes the production workflow as two explicit steps:

1. **RIG 만들기** — compile the main production Portrait Bundle into a Rig Bundle.
2. **표정 도너 조합** — attach eye/mouth expression donors to that finished Rig Bundle.

The rig builder supports:

- single Portrait Bundle builds
- batch builds for a folder of `*.portrait` bundles
- automatic output paths (`A001.portrait` → sibling `A001.rig`)
- optional recursive batch discovery
- legacy input compatibility
- optional back-hair motion softening
- progress, per-portrait preflight/rest-fidelity status, and build logs
- opening the generated output folder directly

The expression composer supports multiple states in one pass. Built-in editable
state presets are `eye_closed`, `wink_left`, `wink_right`, `mouth_open`, and
`mouth_a/i/u/e/o`.

Two donor modes are available:

- **Generated image donor (fast):** select full-frame PNG/WebP/JPEG donors. Only
  the semantic eye or mouth region is recovered; identity, hair, body, and all
  untouched pixels continue to come from the main rig.
- **Decomposed donor Rig (precise):** select an already compiled donor rig for
  each state. The workflow merges all requested donor states first and writes
  the expression block once, so one donor cannot overwrite a previously added
  state.

After installing the package, the same launcher is registered as the
`portrait-autorig-gui` GUI script. GUI code is intentionally kept above reusable
workflow functions (`workflow.py` and `expression_workflow.py`) so later game
deployment can call the exact same validated build path without duplicating
compiler logic.

## Command line (automation / fallback)

The existing command-line interface remains available for scripts and CI:

```powershell
python -m portrait_autorig path\to\A001.portrait path\to\A001.rig
```

For a pre-v1 flat run directory:

```powershell
python -m portrait_autorig path\to\legacy-run path\to\A001.rig --legacy
```

Export a compiled Rig Bundle to Spine:

```powershell
python -m portrait_autorig.spine path\to\A001.rig path\to\spine-project
```

Portrait Bundle input is required to declare
`canonical_stage=production_repaired`. The normal compiler never repairs its
input. The `--legacy` adapter carries a frozen compatibility repair solely for
old runs.

Compilation records a separate `rig_preflight` result in the Rig Bundle
manifest. `READY` means native rig-critical semantics are usable,
`READY_WITH_DERIVATION` means a conservative rig-only semantic was recovered,
`DEGRADED` means the static portrait remains valid but one or more animation
capabilities are unavailable, and `INCOMPATIBLE` means core `head`/`face`
semantics are missing. This does not alter or re-grade Portrait Bundle static
validity.

When `eyewhite` is absent, the compiler may derive bilateral sclera in the rig
working copy by comparing `original`, `head`, and `face` inside iris-anchored
eye regions. The fallback commits only when both sides pass its confidence
checks, removes the accepted coverage from the working `head` to prevent double
drawing, and records provenance under `derived_semantics.eyewhite`. Canonical
Portrait Bundle files are never changed.

The compiler also rebuilds the canonical reference directly from the bundle's
manifest layers, renders the cropped rig at zero motion, and records their
comparison under `rest_fidelity` (`mae`, alpha error, bad-pixel ratio,
percentiles, maximum error, and changed visibility). Remainder subdivisions
keep the canonical back-plane draw order even when their motion owner changes,
and faint alpha edges are retained during cropping. A `fail` result aborts the
compile; a missing semantic derivation that changes the rest pose is rolled
back and reported as `DEGRADED`.

Open [`preview/index.html`](preview/index.html) in a browser and select the Rig
Bundle directory to test head turn, tilt, breath, blink, and gaze.

The original feasibility study and measured motion limits are preserved in
[`docs/PORTRAIT_AUTO_RIG_FEASIBILITY_v0.1.md`](docs/PORTRAIT_AUTO_RIG_FEASIBILITY_v0.1.md).
