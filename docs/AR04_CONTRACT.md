# AR04: Assembly intent and recompile binding contract

Status: implemented in the AutoRig consumer. The vendored Composer Assembly
v0.2 schema remains pinned and unchanged.

## Identity

AutoRig preserves each Assembly instance ID, source image dimensions, semantic,
visibility, variant membership, and instance transform while reading the bundle.
For flattened semantic parts, `source_instance_id` is emitted only when exactly
one visible, non-variant instance contributes to that semantic part. Hidden or
variant instances do not claim the identity of an ordinary compiled part.

Authoring binding priority is `source_instance_id`, `target_instance`,
`target_part`, then `target_tag`. The first non-empty selector is decisive. A
missing or ambiguous match is reported as unresolved; resolution does not fall
through to a weaker selector. Any additional stored selectors must agree with
the same generated part. New chest shape edits also record the part's topology
hash; a changed topology leaves those edits unresolved for review.

The resolved runtime operation must carry a selector compatible with the
selected part. A tag beside a stable instance ID cannot broaden an edit to
other generated parts. `revision_report.bindings` records binding and
application outcomes, including orphaned legacy buckets.

## RigIntent coordinates

Assembly v0.2 regions without an explicit `coordinate_space` are interpreted as
normalized in their target instance image. AutoRig maps their lobe centers and
axis-aligned radii through the same scale, clockwise rotation, and translation
used to place the image, then stores canvas-normalized runtime geometry. An
explicit `canvas_normalized` region is already in canvas coordinates. The
current consumer cannot represent a rotated ellipse, so rotation maps its
axis-aligned bounds and records the transform in
`source.rig_intent_resolution`.

Semantic-only torso targets resolve only when one visible ordinary instance
matches. If multiple torso instances would be flattened into the current single
semantic surface, or multiple regions compete for that surface, compilation
fails with an ambiguity error instead of choosing by map order. Missing target
IDs are marked unresolved and are not used as a semantic fallback. The source
RigIntent payload is preserved verbatim in `source.rig_intent`; resolution
results are recorded separately.

Safety preflight converts canvas-normalized lobes into the compiled torso alpha
bounds before measuring coverage. Runtime geometry remains canvas-normalized,
so alpha cropping does not shift the authored target.

## Source revision and scope

`source_revision` remains the existing SHA-256 over normalized relative paths
and file contents. It is not replaced by per-file generation checksums. Input
revision changes are reported separately from binding results. Composer-emitted
variant/expression data continues through the existing variant compiler and
its `variant_bindings` report.

This contract does not add instance-level rigging for multiple same-semantic
instances. Such input requires a future consumer representation before an
instance-specific deformation can be applied safely.
