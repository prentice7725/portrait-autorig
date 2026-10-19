# AR07 Mesh Safety Contract

Grid remains the default mesh and the runtime fallback. Contour meshes remain
opt-in. The contour compiler now separates connected components from source
alpha before dilation, keeps source holes available during topology checks,
rejects faces that cover resolvable concave gaps or holes, validates rounded
coordinates and triangle area, and declines the contour mesh if it cannot
cover every opaque source pixel. A declined contour mesh falls back to grid.

The preview validates contour coordinates and triangle indices before making
WebGL unsigned-short buffers. Invalid or degenerate contour data falls back
to grid; a grid that exceeds the index limit fails clearly instead of
silently wrapping indices.

`preview/check_mesh_quality.mjs` reports the existing inversion, area ratio,
edge stretch, and UV anisotropy for the current pose sweep. When part PNGs are
available it also reports rest alpha coverage, uncovered alpha-boundary
pixels, internal transparent area covered by the mesh, and invalid or
degenerate rest triangles. Coverage is reported separately from deformation:
the rest alpha is not compared to live-space geometry after a pose.

There is no approved fixed real portrait fixture in this workspace. The
reports can expose synthetic or supplied-fixture defects, but this change
does not claim improved real-art distortion or visual equivalence between
grid and contour meshes without that evidence.
