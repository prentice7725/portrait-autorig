/*
 * P7 QA isolation seam.
 *
 * QA calibration is a runtime overlay. It stays outside the authored
 * R1/R2/R3 buckets until the user presses an explicit Save action.
 */

function cloneJson(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

export function createQaState() {
  return { r3: { physics: {}, ranges: {} } };
}

export function hasR3QaOverrides(qa) {
  return Object.keys(qa?.r3?.physics || {}).length > 0
    || Object.keys(qa?.r3?.ranges || {}).length > 0;
}

function copyFiniteNumbers(target, source) {
  for (const [key, value] of Object.entries(source || {})) {
    if (Number.isFinite(Number(value))) target[key] = Number(value);
  }
}

/** Apply only the transient R3 QA layer to a resolved runtime manifest. */
export function applyR3QaOverrides(manifest, qa) {
  const resolved = cloneJson(manifest);
  if (!hasR3QaOverrides(qa)) return resolved;

  const physics = qa.r3.physics || {};
  const driver = resolved.physics?.upper_torso_driver;
  if (driver && typeof driver === "object") copyFiniteNumbers(driver, physics);

  const ranges = qa.r3.ranges || {};
  const p3 = resolved.motion?.upper_torso_parametric_deformer;
  if (p3) {
    p3.ranges_px ||= {};
    copyFiniteNumbers(p3.ranges_px, ranges);
  }

  // v0.2 manifests carry the P3 declaration in both compatibility views.
  // Keep the transient overlay aligned with the same target so the normal
  // motionFromDeformers projection cannot discard a QA range change.
  for (const deformer of resolved.deformers || []) {
    if (deformer.kind !== "chest_parametric_deformer") continue;
    const config = deformer.config || (deformer.config = {});
    if (p3 && (!config.target_instance || !p3.target_instance
      || config.target_instance === p3.target_instance)
      && (!config.target_part || !p3.target_part || config.target_part === p3.target_part)) {
      config.ranges_px ||= {};
      copyFiniteNumbers(config.ranges_px, ranges);
    }
  }
  return resolved;
}
