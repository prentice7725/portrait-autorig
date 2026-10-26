# AR05 Expression Contract

AR05 reuses the existing `ParamMouthForm` → `mouth_form` corrective and the
existing expression lifecycle. Smile and frown remain parameter poses (for
example `ParamMouthForm: 0.72` and `-0.72`); an authored preset may also select
one or more existing variant sets. `ParamMouthOpenY`, head motion, blink, and
gaze continue through their existing inputs and deformer order.

The local compile path validates preset parameter IDs and ranges, resolves
variant members, and writes both payloads to `expression_presets`. It retains
labels and descriptions authored beside the payload by moving them into
`metadata`. Preview validates all selected variant bindings before changing
parameters. When an expression releases a parameter it restores the prior
value, owner, and parameter override, so transient expression values do not
become the next pose's baseline.

## Contract boundary

`portrait-assembly-v0.2.schema.json` remains the byte-for-byte schema pinned to
the Composer commit. That upstream schema currently describes variant-only
expression presets. The AutoRig compiler accepts parameter and hybrid presets,
but producing those presets in an Assembly Bundle requires the Composer schema
and producer to add the same `parameters` map contract. Keep that coordinated
producer change explicit; do not silently edit the vendored schema copy.

No approved fixed portrait or donor fixture is present in this workspace.
Synthetic geometry checks can cover exact neutral rest, influence bounds,
finite deformation, and mesh inversion, but cannot establish cheek, lip,
glasses, or donor-transition visual quality. EyeSmile and BrowForm remain
optional capabilities and are not added without such a fixture and suitable
source material.
