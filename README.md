# portrait-autorig

`Production-ready Portrait Bundle → derived rig parts + animated portrait rig`

This repository consumes the versioned file contract produced by
[`seethrough-portrait`](https://github.com/prentice7725/seethrough-portrait).
It has no runtime or Python dependency on See-Through, torch, or diffusers.

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

Open [`preview/index.html`](preview/index.html) in a browser and select the Rig
Bundle directory to test head turn, tilt, breath, blink, and gaze.

The original feasibility study and measured motion limits are preserved in
[`docs/PORTRAIT_AUTO_RIG_FEASIBILITY_v0.1.md`](docs/PORTRAIT_AUTO_RIG_FEASIBILITY_v0.1.md).
