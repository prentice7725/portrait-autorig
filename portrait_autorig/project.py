"""Editable Rig Project persistence.

The compiler's historical ``*_rig_manifest.json`` output remains the runtime
compatible view of a rig.  This module adds the R1 authoring source around it:
the generated base is immutable-by-convention, while editor corrections live
in separate JSON files and are resolved on load/save.

The module intentionally knows only the Assembly/Rig bundle contracts.  It
does not import Composer internals and it does not change the runtime manifest
schema.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping

import numpy as np
from PIL import Image

from .physics import INPUT_MODES, UpperTorsoSecondaryDriver

RIG_PROJECT_FORMAT = "portrait-rig-project"
RIG_PROJECT_VERSION = 1
AUTHORING_VERSION = 1
CHEST_DEFORMER_ID = "upper_torso"
CHEST_KEYFORM_NAMES = ("neutral", "bust_x_neg", "bust_x_pos", "bust_y_neg", "bust_y_pos")
CHEST_EDITABLE_KEYFORM_NAMES = ("bust_x_neg", "bust_x_pos", "bust_y_neg", "bust_y_pos")

_AUTHORING_FILES = (
    "deformers.json",
    "physics.json",
    "parameter_ranges.json",
    "keyform_overrides.json",
    "cage_overrides.json",
    "hair_overrides.json",
    "constraints.json",
)
_AUTHORING_META_FILE = "meta.json"
_GENERATION_FORMAT = "portrait-rig-project-generation"
_GENERATION_VERSION = 1
_GENERATION_POINTER = "project-generation.json"


def _json_copy(value: Any) -> Any:
    """Copy JSON-shaped data without allowing callers to mutate project state."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _write_bytes_atomic(path, data)


def _fsync_directory(path: Path) -> None:
    """Best-effort directory flush; Windows does not expose this uniformly."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Replace one file atomically on the same filesystem and flush its data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge JSON objects; lists are authored atomically."""
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = _json_copy(value)
    return base


def source_revision(source: str | os.PathLike[str]) -> str:
    """Return a deterministic revision for a source bundle or rig directory.

    All regular files are included, with normalized relative names and content
    digests.  This covers Assembly metadata, instance images, reference.png,
    and an existing rig's generated manifest/images without inventing
    character-specific values or relying on mtimes.
    """
    root = Path(source).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"source directory does not exist: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        # A project may point at a source directory that also contains a
        # disposable cache.  Cache files are never source truth.
        if (relative == "cache" or relative.startswith("cache/")
                or relative == "project.json"
                or relative.startswith(("source/", "authoring/", "generated/", "qa/"))):
            continue
        content_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_digest.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _source_kind(source: Path) -> str:
    if (source / "project.json").is_file():
        return "rig_project"
    manifest_path = source / "manifest.json"
    if manifest_path.is_file():
        value = _read_json(manifest_path).get("format")
        if value == "portrait-assembly":
            return "assembly"
        if value == "portrait-bundle":
            return "portrait"
    if list(source.glob("*_rig_manifest.json")):
        return "rig"
    raise ValueError(f"unsupported Assembly/Rig source: {source}")


def _default_authoring() -> dict[str, Any]:
    return {
        "version": AUTHORING_VERSION,
        "source_revision": "",
        "deformers": {},
        "physics": {},
        "parameter_ranges": {},
        "keyform_overrides": {},
        "cage_overrides": {},
        "hair_overrides": {},
        "constraints": {},
    }


def _normalise_authoring(value: Mapping[str, Any] | None, revision: str) -> dict[str, Any]:
    authoring = _default_authoring()
    if value:
        _deep_merge(authoring, value)
    authoring["version"] = AUTHORING_VERSION
    # The authoring revision is informational.  It is updated on save so an
    # old correction set remains visible even when the source later changes.
    authoring["source_revision"] = str(authoring.get("source_revision") or revision)
    return authoring


def _empty_editor_state() -> dict[str, Any]:
    return {"current_pose": {}, "selected_deformer": None}


@dataclass
class RigProject:
    """In-memory editable project and its resolved runtime manifest."""

    root: Path
    project: dict[str, Any]
    source: dict[str, Any]
    generated_manifest: dict[str, Any]
    generated_images: dict[str, np.ndarray] = field(default_factory=dict)
    authoring: dict[str, Any] = field(default_factory=_default_authoring)
    editor_state: dict[str, Any] = field(default_factory=_empty_editor_state)
    revision_report: dict[str, Any] = field(default_factory=dict)
    resolved_manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def source_revision_status(self) -> str:
        return str(self.revision_report.get("status", "UNKNOWN"))

    @property
    def generated_base(self) -> dict[str, Any]:
        return self.generated_manifest

    def resolve(self) -> dict[str, Any]:
        self.resolved_manifest, report = resolve_rig(
            self.generated_manifest, self.authoring
        )
        self.revision_report = {
            **self.revision_report,
            "binding_status": report["status"],
            "bindings": report["bindings"],
        }
        return self.resolved_manifest

    def save(self) -> Path:
        return save_rig_project(self)

    def set_deformer_override(self, deformer_id: str, override: Mapping[str, Any]) -> None:
        set_deformer_override(self, deformer_id, override)

    def reset_current_deformer_to_auto(self, deformer_id: str) -> None:
        reset_current_deformer_to_auto(self, deformer_id)

    def reset_deformer_to_auto(self, deformer_id: str) -> None:
        reset_current_deformer_to_auto(self, deformer_id)

    def reset_entire_rig_to_auto(self) -> None:
        reset_entire_rig_to_auto(self)

    def set_chest_cage_bounds(self, bounds: list[float] | tuple[float, ...]) -> None:
        set_chest_cage_bounds(self, bounds)

    def set_chest_cage_points(
        self, points: list[list[float]] | tuple[tuple[float, float], ...]
    ) -> None:
        set_chest_cage_points(self, points)

    def set_chest_keyform(
        self, pose: str, points: list[list[float]] | tuple[tuple[float, float], ...]
    ) -> None:
        set_chest_keyform(self, pose, points)

    def set_chest_physics(self, override: Mapping[str, Any]) -> None:
        set_chest_physics(self, override)

    def set_chest_parameter_range(self, ranges: Mapping[str, Any]) -> None:
        set_chest_parameter_range(self, ranges)

    def reset_chest_physics_to_auto(self) -> None:
        reset_chest_physics_to_auto(self)

    def reset_chest_to_auto(self) -> None:
        reset_chest_to_auto(self)


def _find_manifest(root: Path) -> Path:
    canonical = root / "portrait_rig_manifest.json"
    if canonical.is_file():
        return canonical
    manifests = sorted(root.glob("*_rig_manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"no rig manifest in {root}")
    return max(manifests, key=lambda path: path.stat().st_mtime_ns)


def _load_generated_images(root: Path, manifest: Mapping[str, Any]) -> dict[str, np.ndarray]:
    images: dict[str, np.ndarray] = {}
    image_root = root / "rig" / "images"
    for part in manifest.get("parts", []):
        name = part.get("name")
        if not isinstance(name, str):
            continue
        path = image_root / f"{name}.png"
        if path.is_file():
            with Image.open(path) as image:
                images[name] = np.array(image.convert("RGBA"), dtype=np.uint8)
    return images


def _make_revision_report(source: Mapping[str, Any]) -> dict[str, Any]:
    expected = str(source.get("source_revision", ""))
    location = source.get("path")
    if not expected or not isinstance(location, str):
        return {"status": "UNKNOWN", "expected": expected, "current": None,
                "reason": "source revision is not available"}
    path = Path(location)
    if not path.is_dir():
        return {"status": "MISSING", "expected": expected, "current": None,
                "reason": "source path is unavailable"}
    current = source_revision(path)
    return {
        "status": "MATCH" if current == expected else "MISMATCH",
        "expected": expected,
        "current": current,
        "reason": "" if current == expected else "source files changed",
    }


def _binding_candidates(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for part in manifest.get("parts", []):
        if not isinstance(part, Mapping):
            continue
        mesh = part.get("mesh") if isinstance(part.get("mesh"), Mapping) else {}
        candidates.append({
            "source_instance_id": part.get("source_instance_id"),
            "target_instance": part.get("source_instance_id") or part.get("name"),
            "target_part": part.get("name"),
            "target_tag": part.get("tag"),
            "target_topology_hash": part.get("topology_hash") or mesh.get("topology_hash"),
        })
    return candidates


def resolve_binding(manifest: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve one authoring target without falling through a stale identity.

    Lower-priority aliases are useful for legacy overrides that never stored a
    stronger identity. Once an override stores a stronger identity, a miss or
    contradiction must remain unresolved instead of rebinding by part/tag.
    """
    candidates = _binding_candidates(manifest)
    for field_name in ("source_instance_id", "target_instance", "target_part", "target_tag"):
        value = override.get(field_name)
        if not isinstance(value, str) or not value:
            continue
        matches = [candidate for candidate in candidates if candidate.get(field_name) == value]
        if len(matches) > 1:
            return {"status": "AMBIGUOUS", "strategy": field_name, "matches": matches}
        if not matches:
            return {"status": "UNRESOLVED", "strategy": field_name,
                    "reason": f"{field_name} no longer matches a generated part",
                    "value": value}
        target = matches[0]
        conflicts = {
            key: override[key]
            for key in ("source_instance_id", "target_instance", "target_part", "target_tag")
            if key != field_name and isinstance(override.get(key), str)
            and override.get(key) and target.get(key) != override.get(key)
        }
        if conflicts:
            return {"status": "UNRESOLVED", "strategy": field_name,
                    "reason": "stored binding fields identify different generated parts",
                    "target": target, "conflicts": conflicts}
        topology_hash = override.get("target_topology_hash")
        if (isinstance(topology_hash, str) and topology_hash
                and target.get("target_topology_hash") != topology_hash):
            return {"status": "UNRESOLVED", "strategy": field_name,
                    "reason": "target topology changed since this correction was authored",
                    "target": target, "expected_topology_hash": topology_hash}
        return {"status": "BOUND", "strategy": field_name, "target": target}
    return {"status": "UNRESOLVED", "reason": "no safe target binding"}


def _matches_bound_target(value: Mapping[str, Any], target: Mapping[str, Any],
                          strategy: str, *, deformer_target: bool = False) -> bool:
    """Match generated data to the one part selected by ``resolve_binding``.

    A generated entry with a stronger selector cannot be broadened by a tag
    carried alongside it. We only use a part/tag selector when that was the
    strongest selector present on the authored override.
    """
    instance_key, part_key, tag_key = (
        ("instance", "part", "tag") if deformer_target
        else ("target_instance", "target_part", "target_tag")
    )
    instance = value.get(instance_key)
    if isinstance(instance, str) and instance:
        return instance == target.get("target_instance")
    part = value.get(part_key)
    if isinstance(part, str) and part:
        return strategy in {"target_part", "target_tag"} and part == target.get("target_part")
    tag = value.get(tag_key)
    return (strategy == "target_tag" and isinstance(tag, str) and bool(tag)
            and tag == target.get("target_tag"))


def _apply_deformer_override(manifest: dict[str, Any], override: Mapping[str, Any],
                             binding: Mapping[str, Any]) -> int:
    target = binding.get("target") or {}
    strategy = str(binding.get("strategy", ""))
    motion = manifest.get("motion")
    if not isinstance(motion, dict):
        return 0
    specs: list[dict[str, Any]] = []
    for value in motion.values():
        if isinstance(value, dict):
            specs.append(value)
    matched_specs: list[dict[str, Any]] = []
    for spec in specs:
        if _matches_bound_target(spec, target, strategy):
            matched_specs.append(spec)
            base_rest_points = _json_copy((spec.get("cage") or {}).get("rest_points"))
            for override_key, spec_key in (
                ("cage_override", "cage"),
                ("keyform_overrides", "keyforms"),
                ("range_override", "ranges_px"),
            ):
                value = override.get(override_key)
                if isinstance(value, Mapping):
                    if override_key == "keyform_overrides" and spec.get("version") == 1:
                        value = {key: item for key, item in value.items() if key != "neutral"}
                    if not isinstance(spec.get(spec_key), dict):
                        spec[spec_key] = {}
                    _deep_merge(spec[spec_key], value)
            if isinstance(override.get("patch"), Mapping):
                _deep_merge(spec, override["patch"])
            current_rest_points = _json_copy((spec.get("cage") or {}).get("rest_points"))
            if (isinstance(base_rest_points, list) and isinstance(current_rest_points, list)
                    and len(base_rest_points) == len(current_rest_points)
                    and all(isinstance(point, list) and len(point) == 2
                            for point in base_rest_points + current_rest_points)):
                deltas = [
                    [round(float(current[0]) - float(base[0]), 6),
                     round(float(current[1]) - float(base[1]), 6)]
                    for base, current in zip(base_rest_points, current_rest_points)
                ]
                if any(abs(value) > 1e-9 for point in deltas for value in point):
                    spec.setdefault("cage", {})["rest_point_deltas"] = deltas
                else:
                    spec.setdefault("cage", {}).pop("rest_point_deltas", None)

    application_count = len(matched_specs)
    for deformer in manifest.get("deformers", []):
        if not isinstance(deformer, dict):
            continue
        deformer_target = deformer.get("targets") or {}
        config = deformer.get("config")
        if not isinstance(config, dict):
            continue
        if _matches_bound_target(deformer_target, target, strategy, deformer_target=True):
            application_count += 1
            if isinstance(override.get("patch"), Mapping):
                _deep_merge(config, override["patch"])
            if deformer.get("kind") == "chest_parametric_deformer":
                matching_spec = next((spec for spec in matched_specs
                                      if _matches_bound_target(spec, target, strategy)), None)
                if matching_spec is not None:
                    deformer["config"] = _json_copy(matching_spec)
    return application_count


def resolve_rig(generated_manifest: Mapping[str, Any],
                authoring: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``generated base + safe authoring overrides`` and a binding report."""
    resolved = _json_copy(generated_manifest)
    authoring_data = _normalise_authoring(authoring, "")
    entries = authoring_data.get("deformers") or {}
    report_entries: dict[str, Any] = {}
    for deformer_id, override in entries.items():
        if not isinstance(override, Mapping):
            report_entries[str(deformer_id)] = {"status": "UNRESOLVED", "reason": "override must be an object"}
            continue
        binding = resolve_binding(resolved, override)
        if binding.get("status") == "BOUND":
            applied = _apply_deformer_override(resolved, override, binding)
            binding["application_status"] = "APPLIED" if applied else "NO_GENERATED_TARGET"
        report_entries[str(deformer_id)] = binding

    if authoring_data.get("physics") and isinstance(authoring_data.get("physics"), Mapping):
        if not isinstance(resolved.get("physics"), dict):
            resolved["physics"] = {}
        # Authoring calls the editable chest bucket ``upper_torso`` while
        # the runtime manifest keeps its historical driver key.
        for key, value in authoring_data["physics"].items():
            target_key = "upper_torso_driver" if key == "upper_torso" else key
            if isinstance(value, Mapping) and isinstance(resolved["physics"].get(target_key), dict):
                _deep_merge(resolved["physics"][target_key], value)
            else:
                resolved["physics"][target_key] = _json_copy(value)
    if (authoring_data.get("parameter_ranges")
            and isinstance(authoring_data.get("parameter_ranges"), Mapping)):
        if not isinstance(resolved.get("parameter_ranges"), dict):
            resolved["parameter_ranges"] = {}
        _deep_merge(resolved["parameter_ranges"], authoring_data["parameter_ranges"])
    # These top-level buckets are intentionally applied only to matching
    # deformer keys.  Unknown future authoring data remains persisted but is
    # not guessed into the runtime contract.
    for bucket_name, override_key in (("keyform_overrides", "keyform_overrides"),
                                      ("cage_overrides", "cage_override"),
                                      ("hair_overrides", "patch")):
        bucket = authoring_data.get(bucket_name) or {}
        if isinstance(bucket, Mapping):
            for deformer_id, patch in bucket.items():
                if not isinstance(patch, Mapping):
                    continue
                entry = dict(patch)
                if override_key != "patch":
                    entry = {override_key: entry}
                target = {"target_part": deformer_id, "target_tag": deformer_id}
                binding = resolve_binding(resolved, target)
                if binding.get("status") == "BOUND":
                    applied = _apply_deformer_override(resolved, entry, binding)
                    binding["application_status"] = "APPLIED" if applied else "NO_GENERATED_TARGET"
                report_entries[f"{bucket_name}:{deformer_id}"] = binding

    review_required = any(
        item.get("status") != "BOUND"
        or item.get("application_status") != "APPLIED"
        for item in report_entries.values()
    )
    overall = "REVIEW_REQUIRED" if review_required else "MATCH"
    return resolved, {"status": overall, "bindings": report_entries}


def set_deformer_override(project: RigProject, deformer_id: str,
                          override: Mapping[str, Any]) -> None:
    if not isinstance(override, Mapping):
        raise TypeError("deformer override must be an object")
    value = _json_copy(override)
    if not any(isinstance(value.get(key), str) and value[key]
               for key in ("source_instance_id", "target_instance", "target_part", "target_tag")):
        raise ValueError("deformer override requires a stable target binding")
    project.authoring.setdefault("deformers", {})[str(deformer_id)] = value
    project.resolve()


def _chest_spec(manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    motion = manifest.get("motion")
    if not isinstance(motion, Mapping):
        return None
    spec = motion.get("upper_torso_parametric_deformer")
    return spec if isinstance(spec, dict) else None


def _chest_binding(project: RigProject) -> dict[str, Any]:
    spec = _chest_spec(project.generated_manifest)
    if spec is None:
        raise ValueError("R2 chest authoring requires a P3 parametric chest deformer")
    binding = {}
    for key in ("source_instance_id", "target_instance", "target_part", "target_tag",
                "target_topology_hash"):
        value = spec.get(key)
        if isinstance(value, str) and value:
            binding[key] = value
    if not binding:
        raise ValueError("P3 chest deformer has no stable authoring target")
    return binding


def _refresh_chest_binding(override: dict[str, Any], binding: Mapping[str, Any]) -> None:
    selector_keys = ("source_instance_id", "target_instance", "target_part", "target_tag")
    conflicts = {
        key: override[key]
        for key in selector_keys
        if override.get(key) and binding.get(key) and override[key] != binding[key]
    }
    old_topology = override.get("target_topology_hash")
    new_topology = binding.get("target_topology_hash")
    if conflicts:
        raise ValueError(
            "existing chest correction is bound to a different generated target; "
            "reset or review it before editing"
        )
    if old_topology and old_topology != new_topology:
        raise ValueError(
            "existing chest correction uses an older topology; reset or review it before editing"
        )
    override.update(binding)


def _finite_pairs(value: Any, expected: int, label: str) -> list[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != expected:
        raise ValueError(f"{label} must contain exactly {expected} points")
    points: list[list[float]] = []
    for point in value:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"{label} points must be [x, y] pairs")
        x, y = float(point[0]), float(point[1])
        if not np.isfinite(x) or not np.isfinite(y):
            raise ValueError(f"{label} points must be finite")
        points.append([x, y])
    return points


def set_chest_cage_bounds(project: RigProject,
                          bounds: list[float] | tuple[float, ...]) -> None:
    """Persist an R2 correction for the P3 cage bounds."""
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError("chest cage bounds must be [x1, y1, x2, y2]")
    values = [float(value) for value in bounds]
    if not all(np.isfinite(value) for value in values):
        raise ValueError("chest cage bounds must be finite")
    if values[2] <= values[0] or values[3] <= values[1]:
        raise ValueError("chest cage bounds must have positive width and height")
    override = dict(project.authoring.setdefault("deformers", {}).get(CHEST_DEFORMER_ID) or {})
    _refresh_chest_binding(override, _chest_binding(project))
    cage = dict(override.get("cage_override") or {})
    cage["bounds"] = values
    override["cage_override"] = cage
    project.authoring["deformers"][CHEST_DEFORMER_ID] = override
    project.resolve()


def set_chest_cage_points(project: RigProject,
                          points: list[list[float]] | tuple[tuple[float, float], ...]) -> None:
    """Persist all 24 P3 rest cage control points as an R2 correction."""
    normalised = _finite_pairs(points, 24, "chest cage points")
    override = dict(project.authoring.setdefault("deformers", {}).get(CHEST_DEFORMER_ID) or {})
    _refresh_chest_binding(override, _chest_binding(project))
    cage = dict(override.get("cage_override") or {})
    cage["rest_points"] = normalised
    override["cage_override"] = cage
    project.authoring["deformers"][CHEST_DEFORMER_ID] = override
    project.resolve()


def set_chest_keyform(project: RigProject, pose: str,
                      points: list[list[float]] | tuple[tuple[float, float], ...]) -> None:
    """Persist one complete P3 keyform correction without touching physics."""
    if pose not in CHEST_EDITABLE_KEYFORM_NAMES:
        raise ValueError(f"unsupported chest keyform: {pose!r}")
    normalised = _finite_pairs(points, 24, f"chest keyform {pose}")
    override = dict(project.authoring.setdefault("deformers", {}).get(CHEST_DEFORMER_ID) or {})
    _refresh_chest_binding(override, _chest_binding(project))
    keyforms = dict(override.get("keyform_overrides") or {})
    keyforms[pose] = normalised
    override["keyform_overrides"] = keyforms
    project.authoring["deformers"][CHEST_DEFORMER_ID] = override
    project.resolve()


_CHEST_PHYSICS_FIELDS = {
    "profile", "model", "input_mode", "natural_frequency_hz", "damping_ratio",
    "lag_seconds_x", "lag_seconds_y", "max_displacement_px", "max_velocity_px_s",
    "idle_lag_max_px", "kick_lag_max_px", "enabled",
}


def set_chest_physics(project: RigProject, override: Mapping[str, Any]) -> None:
    """Persist explicit R3 chest timing/response calibration values."""
    if not isinstance(override, Mapping) or not override:
        raise ValueError("chest physics override must be a non-empty object")
    unknown = set(override) - _CHEST_PHYSICS_FIELDS
    if unknown:
        raise ValueError(f"unsupported chest physics fields: {sorted(unknown)}")
    values = _json_copy(override)
    positive = ("natural_frequency_hz", "max_displacement_px", "max_velocity_px_s",
                "idle_lag_max_px", "kick_lag_max_px")
    nonnegative = ("lag_seconds_x", "lag_seconds_y")
    for field in (*positive, *nonnegative, "damping_ratio"):
        if field not in values:
            continue
        try:
            number = float(values[field])
        except (TypeError, ValueError) as error:
            raise ValueError(f"chest physics {field} must be finite") from error
        if not np.isfinite(number):
            raise ValueError(f"chest physics {field} must be finite")
        if field in positive and number <= 0:
            raise ValueError(f"chest physics {field} must be positive")
        if field in nonnegative and number < 0:
            raise ValueError(f"chest physics {field} must be non-negative")
        if field == "damping_ratio" and number < 0:
            raise ValueError("chest physics damping_ratio must be non-negative")
        values[field] = number
    if "profile" in values and values["profile"] not in UpperTorsoSecondaryDriver.PROFILES:
        raise ValueError("unsupported chest physics profile")
    if "input_mode" in values and values["input_mode"] not in INPUT_MODES:
        raise ValueError("unsupported chest physics input_mode")
    if "model" in values and values["model"] not in {
        "legacy_target_v1", "inertial_relative_v1", "inertial_relative_v2"
    }:
        raise ValueError("unsupported chest physics model")
    if "enabled" in values and not isinstance(values["enabled"], bool):
        raise ValueError("chest physics enabled must be a boolean")
    project.authoring.setdefault("physics", {}).setdefault(CHEST_DEFORMER_ID, {}).update(values)
    project.resolve()


def set_chest_parameter_range(project: RigProject, ranges: Mapping[str, Any]) -> None:
    """Persist the R3 BustX/BustY-to-pixel range correction."""
    if not isinstance(ranges, Mapping):
        raise TypeError("chest parameter range must be an object")
    values: dict[str, float] = {}
    for axis in ("x", "y"):
        if axis not in ranges:
            continue
        try:
            value = float(ranges[axis])
        except (TypeError, ValueError) as error:
            raise ValueError(f"chest range {axis} must be finite") from error
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"chest range {axis} must be positive and finite")
        values[axis] = value
    if not values:
        raise ValueError("chest parameter range requires x and/or y")
    override = dict(project.authoring.setdefault("deformers", {}).get(CHEST_DEFORMER_ID) or {})
    _refresh_chest_binding(override, _chest_binding(project))
    current = dict(override.get("range_override") or {})
    current.update(values)
    override["range_override"] = current
    project.authoring["deformers"][CHEST_DEFORMER_ID] = override
    project.resolve()


def reset_chest_to_auto(project: RigProject) -> None:
    """Reset only the authored P3 chest shape to the generated base."""
    override = project.authoring.setdefault("deformers", {}).get(CHEST_DEFORMER_ID)
    if isinstance(override, dict):
        # R2 owns the shape correction and its range/cage payload.  Physics is
        # an independent R3 bucket and must survive this operation.
        project.authoring["deformers"].pop(CHEST_DEFORMER_ID, None)
    for bucket in ("keyform_overrides", "cage_overrides"):
        project.authoring.setdefault(bucket, {}).pop(CHEST_DEFORMER_ID, None)
    project.resolve()


def reset_chest_physics_to_auto(project: RigProject) -> None:
    """Reset R3 physics/ranges while retaining any R2 shape correction."""
    project.authoring.setdefault("physics", {}).pop(CHEST_DEFORMER_ID, None)
    override = project.authoring.setdefault("deformers", {}).get(CHEST_DEFORMER_ID)
    if isinstance(override, dict):
        override.pop("range_override", None)
        if not any(key in override for key in ("cage_override", "keyform_overrides", "patch")):
            project.authoring["deformers"].pop(CHEST_DEFORMER_ID, None)
    project.resolve()


def reset_current_pose(project: RigProject) -> None:
    """Reset transient pose state; authored corrections remain untouched."""
    project.editor_state["current_pose"] = {}


def reset_current_deformer_to_auto(project: RigProject, deformer_id: str) -> None:
    project.authoring.setdefault("deformers", {}).pop(str(deformer_id), None)
    project.authoring.setdefault("physics", {}).pop(str(deformer_id), None)
    for bucket in ("keyform_overrides", "cage_overrides", "hair_overrides"):
        project.authoring.setdefault(bucket, {}).pop(str(deformer_id), None)
    project.resolve()


def reset_deformer_to_auto(project: RigProject, deformer_id: str) -> None:
    """Compatibility alias for the R1 "Reset Deformer to Auto" action."""
    reset_current_deformer_to_auto(project, deformer_id)


def reset_entire_rig_to_auto(project: RigProject) -> None:
    revision = str(project.source.get("source_revision", ""))
    project.authoring = _normalise_authoring(None, revision)
    project.resolve()


def _source_reference(source: Path, kind: str, source_id: str | None = None,
                      instance_ids: list[str] | None = None) -> dict[str, Any]:
    reference: dict[str, Any] = {
        "kind": kind,
        "path": str(source.resolve()),
        "source_id": source_id or source.name,
        "source_revision": source_revision(source),
        "binding_priority": ["source_instance_id", "target_instance", "target_part", "target_tag"],
    }
    if instance_ids is not None:
        reference["source_instance_ids"] = list(instance_ids)
    return reference


def create_rig_project(output_dir: str | os.PathLike[str],
                       generated_manifest: Mapping[str, Any],
                       generated_images: Mapping[str, np.ndarray], *,
                       source: str | os.PathLike[str] | None = None,
                       source_kind: str | None = None,
                       source_id: str | None = None,
                       authoring: Mapping[str, Any] | None = None,
                       instance_ids: list[str] | None = None) -> RigProject:
    """Create an R1 project around an already compiled generated rig.

    The compiler remains responsible for AutoRig generation.  This function
    only persists the base, source reference, authoring buckets, and resolved
    compatibility manifest.
    """
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    source_path = Path(source).expanduser().resolve() if source is not None else root
    if source_kind is None:
        source_kind = _source_kind(source_path) if source is not None else "rig"
    reference = (_source_reference(source_path, source_kind, source_id, instance_ids)
                 if source is not None else {
                     "kind": source_kind, "path": str(source_path),
                     "source_id": source_id or root.name, "source_revision": "",
                     "binding_priority": ["source_instance_id", "target_instance", "target_part", "target_tag"],
                 })
    previous_authoring = authoring
    project_path = root / "project.json"
    if previous_authoring is None and project_path.is_file():
        try:
            previous_authoring = load_rig_project(root).authoring
        except (OSError, ValueError, KeyError):
            previous_authoring = None
    authoring_data = _normalise_authoring(previous_authoring, str(reference.get("source_revision", "")))
    project_data = {
        "format": RIG_PROJECT_FORMAT,
        "version": RIG_PROJECT_VERSION,
        "id": root.name,
        "source": {"reference": "source/assembly_reference.json",
                   "kind": reference["kind"], "source_id": reference["source_id"],
                   "source_revision": reference["source_revision"]},
        "generated_base": {"manifest": "generated/portrait_rig_manifest.json",
                           "images": "generated/rig/images"},
        "authoring": {"root": "authoring", "meta": "authoring/meta.json",
                      "version": AUTHORING_VERSION},
        "qa": {"status": "UNREVIEWED"},
    }
    project = RigProject(root, project_data, reference,
                         _json_copy(generated_manifest),
                         {str(name): np.asarray(image, dtype=np.uint8).copy()
                          for name, image in generated_images.items()},
                         authoring_data,
                         revision_report=_make_revision_report(reference))
    project.resolve()
    save_rig_project(project)
    return project


def _generation_payloads(project: RigProject) -> dict[str, bytes]:
    """Build a complete immutable generation, including its runtime export."""
    payloads: dict[str, bytes] = {}

    def add_json(relative: str, value: Mapping[str, Any]) -> None:
        payloads[relative] = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    add_json("project.json", project.project)
    add_json("source/assembly_reference.json", project.source)
    add_json("generated/portrait_rig_manifest.json", project.generated_manifest)
    add_json("qa/status.json", {
        "status": project.project.get("qa", {}).get("status", "UNREVIEWED"),
        "source_revision": project.revision_report,
    })
    for filename in _AUTHORING_FILES:
        key = filename[:-5]
        add_json(f"authoring/{filename}", project.authoring.get(key) or {})
    add_json(f"authoring/{_AUTHORING_META_FILE}", {
        "version": AUTHORING_VERSION,
        "source_revision": project.authoring.get("source_revision", ""),
    })
    add_json("portrait_rig_manifest.json", project.resolved_manifest)

    for name, image in project.generated_images.items():
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"unsafe generated image name: {name!r}")
        buffer = io.BytesIO()
        Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGBA").save(buffer, format="PNG")
        encoded = buffer.getvalue()
        payloads[f"generated/rig/images/{name}.png"] = encoded
        payloads[f"rig/images/{name}.png"] = encoded
    return payloads


def _write_generation(root: Path, generation_id: str,
                      payloads: Mapping[str, bytes]) -> tuple[Path, dict[str, Any]]:
    generations_root = root / "project_generations"
    generations_root.mkdir(parents=True, exist_ok=True)
    staging = generations_root / f".staging-{generation_id}"
    final = generations_root / generation_id
    if final.exists():
        raise FileExistsError(f"project generation already exists: {generation_id}")
    staging.mkdir()
    try:
        files: dict[str, str] = {}
        for relative, data in payloads.items():
            relative_value = str(relative).replace("\\", "/")
            relative_path = PurePosixPath(relative_value)
            if (relative_path.is_absolute()
                    or any(part in {"", ".", ".."} for part in relative_value.split("/"))
                    or (len(relative_value) > 1 and relative_value[1] == ":")):
                raise ValueError(f"unsafe generation path: {relative!r}")
            path = staging.joinpath(*relative_path.parts)
            _write_bytes_atomic(path, data)
            expected_digest = hashlib.sha256(data).hexdigest()
            if _sha256_file(path) != expected_digest:
                raise OSError(f"project generation write verification failed: {relative}")
            files[relative_path.as_posix()] = expected_digest
        record = {
            "format": _GENERATION_FORMAT,
            "version": _GENERATION_VERSION,
            "generation": generation_id,
            "created_at_ns": str(time.time_ns()),
            "files": files,
        }
        _write_json(staging / "complete.json", record)
        if _read_json(staging / "complete.json") != record:
            raise OSError("project generation completion marker verification failed")
        os.replace(staging, final)
        _fsync_directory(generations_root)
        return final, record
    except Exception:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _validated_generation(root: Path, generation_id: Any,
                          expected: Mapping[str, Any] | None = None) -> tuple[Path, dict[str, Any]]:
    if (not isinstance(generation_id, str) or not generation_id
            or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                   for character in generation_id)):
        raise ValueError("invalid project generation identifier")
    generation_root = root / "project_generations" / generation_id
    complete_path = generation_root / "complete.json"
    if not complete_path.is_file():
        raise ValueError(f"project generation is incomplete: {generation_id}")
    complete = _read_json(complete_path)
    if (complete.get("format") != _GENERATION_FORMAT
            or int(complete.get("version", 0)) != _GENERATION_VERSION
            or complete.get("generation") != generation_id
            or not isinstance(complete.get("files"), dict)):
        raise ValueError(f"invalid project generation record: {generation_id}")
    required_files = {
        "project.json", "source/assembly_reference.json",
        "generated/portrait_rig_manifest.json", "authoring/meta.json",
        "portrait_rig_manifest.json",
    }
    if not required_files.issubset(complete["files"]):
        raise ValueError(f"project generation is missing required files: {generation_id}")
    if expected is not None:
        for key in ("format", "version", "generation", "created_at_ns", "files"):
            if expected.get(key) != complete.get(key):
                raise ValueError(f"project generation pointer does not match complete record: {key}")
    for relative, expected_digest in complete["files"].items():
        relative_value = str(relative).replace("\\", "/")
        relative_path = PurePosixPath(relative_value)
        if (relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_value.split("/"))
                or (len(relative_value) > 1 and relative_value[1] == ":")):
            raise ValueError(f"unsafe path in project generation: {relative!r}")
        path = generation_root.joinpath(*relative_path.parts)
        try:
            path.resolve().relative_to(generation_root.resolve())
        except ValueError as error:
            raise ValueError(f"project generation path escapes its directory: {relative!r}") from error
        if not path.is_file() or _sha256_file(path) != expected_digest:
            raise ValueError(f"project generation checksum mismatch: {relative}")
    return generation_root, complete


def _project_generation(root: Path) -> tuple[Path, dict[str, Any]] | None:
    pointer_path = root / _GENERATION_POINTER
    if not pointer_path.is_file():
        return None
    pointer = _read_json(pointer_path)
    if (pointer.get("format") != _GENERATION_FORMAT
            or int(pointer.get("version", 0)) != _GENERATION_VERSION):
        raise ValueError(f"unsupported project generation contract: {pointer_path}")
    return _validated_generation(root, pointer.get("generation"), pointer)


def _publish_compatibility_exports(root: Path, generation_root: Path,
                                   record: Mapping[str, Any]) -> None:
    """Refresh legacy files individually; the runtime manifest is published last."""
    relatives = list(record.get("files", {}))
    relatives.sort(key=lambda name: (name == "portrait_rig_manifest.json", name))
    for relative in relatives:
        source = generation_root.joinpath(*PurePosixPath(relative).parts)
        destination = root.joinpath(*PurePosixPath(relative).parts)
        expected_digest = record["files"][relative]
        if destination.is_file() and _sha256_file(destination) == expected_digest:
            continue
        _write_bytes_atomic(destination, source.read_bytes())


def save_rig_project(project: RigProject) -> Path:
    """Commit one checksummed generation, then refresh legacy runtime files."""
    root = Path(project.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project.root = root
    source_revision_value = str(project.source.get("source_revision", ""))
    project.project["source"] = {
        **(project.project.get("source") or {}),
        "reference": "source/assembly_reference.json",
        "kind": project.source.get("kind", "rig"),
        "source_id": project.source.get("source_id", root.name),
        "source_revision": source_revision_value,
    }
    project.project["generated_base"] = {
        **(project.project.get("generated_base") or {}),
        "manifest": "generated/portrait_rig_manifest.json",
        "images": "generated/rig/images",
    }
    project.project["authoring"] = {
        **(project.project.get("authoring") or {}),
        "root": "authoring", "meta": "authoring/meta.json", "version": AUTHORING_VERSION,
    }
    project.authoring = _normalise_authoring(project.authoring, source_revision_value)
    project.resolve()
    generation_id = f"g-{time.time_ns()}-{uuid.uuid4().hex}"
    payloads = _generation_payloads(project)
    generation_root, record = _write_generation(root, generation_id, payloads)
    # This small pointer is the commit point. Every referenced file is already
    # flushed, checksummed, and immutable before it becomes the active save.
    _write_json(root / _GENERATION_POINTER, record)
    try:
        _publish_compatibility_exports(root, generation_root, record)
    except OSError as error:
        raise OSError(
            f"project generation {generation_id} is committed, but its legacy runtime export "
            f"could not be refreshed; reopening the project will retry recovery: {error}"
        ) from error
    return root / "portrait_rig_manifest.json"


def load_rig_project(directory: str | os.PathLike[str]) -> RigProject:
    """Load an editable project and report source revision/binding drift."""
    root = Path(directory).expanduser().resolve()
    generation = _project_generation(root)
    data_root = generation[0] if generation else root
    project_data = _read_json(data_root / "project.json")
    if project_data.get("format") != RIG_PROJECT_FORMAT:
        raise ValueError(f"not a Rig Project: {root}")
    if int(project_data.get("version", 0)) != RIG_PROJECT_VERSION:
        raise ValueError(f"unsupported Rig Project version: {project_data.get('version')!r}")
    compatibility_error = None
    if generation:
        try:
            _publish_compatibility_exports(root, generation[0], generation[1])
        except OSError as error:
            compatibility_error = str(error)
    source = _read_json(data_root / "source" / "assembly_reference.json")
    generated_path = data_root / str((project_data.get("generated_base") or {}).get(
        "manifest", "generated/portrait_rig_manifest.json"))
    generated = _read_json(generated_path)
    generated_image_root = data_root / "generated" / "rig" / "images"
    generated_images = {}
    for part in generated.get("parts", []):
        name = part.get("name") if isinstance(part, Mapping) else None
        if not isinstance(name, str):
            continue
        image_path = generated_image_root / f"{name}.png"
        if image_path.is_file():
            with Image.open(image_path) as image:
                generated_images[name] = np.array(image.convert("RGBA"), dtype=np.uint8)
    if not generated_images:
        # Projects created by an older writer may not have the generated copy
        # yet.  The legacy runtime location is a safe fallback.
        generated_images = _load_generated_images(data_root, generated)
    authoring = _default_authoring()
    authoring_root = data_root / str((project_data.get("authoring") or {}).get("root", "authoring"))
    meta_path = authoring_root / _AUTHORING_META_FILE
    if meta_path.is_file():
        meta = _read_json(meta_path)
        authoring["version"] = int(meta.get("version", AUTHORING_VERSION))
        authoring["source_revision"] = str(meta.get("source_revision", ""))
    for filename in _AUTHORING_FILES:
        path = authoring_root / filename
        if path.is_file():
            key = filename[:-5]
            value = _read_json(path)
            if key in {"deformers", "physics", "parameter_ranges", "keyform_overrides",
                       "cage_overrides", "hair_overrides", "constraints"}:
                authoring[key] = value
    reference_revision = str(source.get("source_revision", ""))
    authoring = _normalise_authoring(authoring, reference_revision)
    revision_report = _make_revision_report(source)
    if generation:
        revision_report["generation"] = generation[1].get("generation")
        revision_report["generation_status"] = "COMMITTED"
    if compatibility_error:
        revision_report["compatibility_export"] = "STALE"
        revision_report["compatibility_error"] = compatibility_error
    project = RigProject(root, project_data, source, generated, generated_images, authoring,
                         editor_state=_empty_editor_state(),
                         revision_report=revision_report)
    project.resolve()
    return project


def open_rig(path: str | os.PathLike[str],
             project_dir: str | os.PathLike[str] | None = None) -> RigProject:
    """Open a Rig Project or an existing generated Rig directory.

    Existing generated rigs are converted into a sibling ``.rigproject`` by
    default.  The generated source directory is never used as the project
    destination, so opening or saving authoring data cannot rewrite its source
    manifest.  Pass ``project_dir`` to choose another editable destination.
    """
    root = Path(path).expanduser().resolve()
    if (root / "project.json").is_file() or (root / _GENERATION_POINTER).is_file():
        return load_rig_project(root)
    manifest_path = _find_manifest(root)
    manifest = _read_json(manifest_path)
    destination = (Path(project_dir).expanduser().resolve()
                   if project_dir is not None else root.with_suffix(".rigproject"))
    if destination == root:
        raise ValueError("legacy Rig source and editable Rig Project destination must differ")
    if (destination / "project.json").is_file():
        return load_rig_project(destination)
    return create_rig_project(destination, manifest, _load_generated_images(root, manifest),
                              source=root, source_kind="rig", source_id=root.name)


def create_rig_project_from_assembly(
    assembly_dir: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    **compile_options: Any,
) -> RigProject:
    """Compile one Assembly Bundle and return its editable R1 project."""
    from .compiler import compile_assembly_bundle

    compile_assembly_bundle(str(assembly_dir), str(output_dir), **compile_options)
    return load_rig_project(output_dir)


def load_rig_source(path: str | os.PathLike[str]) -> Any:
    """Load an Assembly/Portrait source or an editable/generated Rig.

    Bundle inputs are returned by their existing contract readers.  Rig
    inputs are returned as :class:`RigProject`, so callers never need to
    inspect private file names to decide what they opened.
    """
    root = Path(path).expanduser().resolve()
    if ((root / "project.json").is_file() or (root / _GENERATION_POINTER).is_file()
            or list(root.glob("*_rig_manifest.json"))):
        return open_rig(root)
    manifest = _read_json(root / "manifest.json")
    if manifest.get("format") == "portrait-assembly":
        from .assembly import load_assembly_bundle
        return load_assembly_bundle(root)
    if manifest.get("format") == "portrait-bundle":
        from .bundle import load_portrait_bundle
        return load_portrait_bundle(root)
    raise ValueError(f"unsupported Assembly/Rig source: {root}")


__all__ = [
    "AUTHORING_VERSION", "RIG_PROJECT_FORMAT", "RIG_PROJECT_VERSION", "RigProject",
    "source_revision", "resolve_binding", "resolve_rig", "create_rig_project",
    "load_rig_project", "save_rig_project", "open_rig", "set_deformer_override",
    "create_rig_project_from_assembly", "load_rig_source",
    "reset_current_pose", "reset_current_deformer_to_auto", "reset_deformer_to_auto",
    "reset_entire_rig_to_auto", "CHEST_DEFORMER_ID", "CHEST_KEYFORM_NAMES",
    "CHEST_EDITABLE_KEYFORM_NAMES",
    "set_chest_cage_bounds", "set_chest_cage_points", "set_chest_keyform",
    "set_chest_physics", "set_chest_parameter_range", "reset_chest_physics_to_auto",
    "reset_chest_to_auto",
]
