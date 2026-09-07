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
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

RIG_PROJECT_FORMAT = "portrait-rig-project"
RIG_PROJECT_VERSION = 1
AUTHORING_VERSION = 1
CHEST_DEFORMER_ID = "upper_torso"
CHEST_KEYFORM_NAMES = ("neutral", "bust_x_neg", "bust_x_pos", "bust_y_neg", "bust_y_pos")

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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


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
        candidates.append({
            "source_instance_id": part.get("source_instance_id"),
            "target_instance": part.get("source_instance_id") or part.get("name"),
            "target_part": part.get("name"),
            "target_tag": part.get("tag"),
        })
    return candidates


def resolve_binding(manifest: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve an authoring target using the locked R1 priority order."""
    candidates = _binding_candidates(manifest)
    for field_name in ("source_instance_id", "target_instance", "target_part", "target_tag"):
        value = override.get(field_name)
        if not isinstance(value, str) or not value:
            continue
        matches = [candidate for candidate in candidates if candidate.get(field_name) == value]
        if len(matches) == 1:
            return {"status": "BOUND", "strategy": field_name, "target": matches[0]}
        if len(matches) > 1:
            return {"status": "AMBIGUOUS", "strategy": field_name, "matches": matches}
    return {"status": "UNRESOLVED", "reason": "no safe target binding"}


def _apply_deformer_override(manifest: dict[str, Any], override: Mapping[str, Any],
                             binding: Mapping[str, Any]) -> None:
    target = binding.get("target") or {}
    target_instance = target.get("target_instance")
    target_part = target.get("target_part")
    target_tag = target.get("target_tag")
    motion = manifest.get("motion")
    if not isinstance(motion, dict):
        return
    specs: list[dict[str, Any]] = []
    for value in motion.values():
        if isinstance(value, dict):
            specs.append(value)
    for spec in specs:
        spec_target = spec.get("target_instance")
        if (target_instance and spec_target == target_instance
                or target_part and spec.get("target_part") == target_part
                or target_tag and spec.get("target_tag") == target_tag):
            for override_key, spec_key in (
                ("cage_override", "cage"),
                ("keyform_overrides", "keyforms"),
                ("range_override", "ranges_px"),
            ):
                value = override.get(override_key)
                if isinstance(value, Mapping):
                    if not isinstance(spec.get(spec_key), dict):
                        spec[spec_key] = {}
                    _deep_merge(spec[spec_key], value)
            if isinstance(override.get("patch"), Mapping):
                _deep_merge(spec, override["patch"])

    for deformer in manifest.get("deformers", []):
        if not isinstance(deformer, dict):
            continue
        deformer_target = deformer.get("targets") or {}
        config = deformer.get("config")
        if not isinstance(config, dict):
            continue
        if (target_instance and deformer_target.get("instance") == target_instance
                or target_part and deformer_target.get("part") == target_part
                or target_tag and deformer_target.get("tag") == target_tag):
            if isinstance(override.get("patch"), Mapping):
                _deep_merge(config, override["patch"])


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
        report_entries[str(deformer_id)] = binding
        if binding.get("status") == "BOUND":
            _apply_deformer_override(resolved, override, binding)

    if authoring_data.get("physics") and isinstance(authoring_data.get("physics"), Mapping):
        if not isinstance(resolved.get("physics"), dict):
            resolved["physics"] = {}
        _deep_merge(resolved["physics"], authoring_data["physics"])
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
                    _apply_deformer_override(resolved, entry, binding)

    statuses = {item.get("status") for item in report_entries.values()}
    overall = "MATCH" if not statuses or statuses == {"BOUND"} else "REVIEW_REQUIRED"
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
    for key in ("target_instance", "target_part", "target_tag"):
        value = spec.get(key)
        if isinstance(value, str) and value:
            binding[key] = value
    if not binding:
        raise ValueError("P3 chest deformer has no stable authoring target")
    return binding


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
    override.update(_chest_binding(project))
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
    override.update(_chest_binding(project))
    cage = dict(override.get("cage_override") or {})
    cage["rest_points"] = normalised
    override["cage_override"] = cage
    project.authoring["deformers"][CHEST_DEFORMER_ID] = override
    project.resolve()


def set_chest_keyform(project: RigProject, pose: str,
                      points: list[list[float]] | tuple[tuple[float, float], ...]) -> None:
    """Persist one complete P3 keyform correction without touching physics."""
    if pose not in CHEST_KEYFORM_NAMES:
        raise ValueError(f"unsupported chest keyform: {pose!r}")
    normalised = _finite_pairs(points, 24, f"chest keyform {pose}")
    override = dict(project.authoring.setdefault("deformers", {}).get(CHEST_DEFORMER_ID) or {})
    override.update(_chest_binding(project))
    keyforms = dict(override.get("keyform_overrides") or {})
    keyforms[pose] = normalised
    override["keyform_overrides"] = keyforms
    project.authoring["deformers"][CHEST_DEFORMER_ID] = override
    project.resolve()


def reset_chest_to_auto(project: RigProject) -> None:
    """Reset only the authored P3 chest shape to the generated base."""
    reset_current_deformer_to_auto(project, CHEST_DEFORMER_ID)


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


def save_rig_project(project: RigProject) -> Path:
    """Persist a project and its resolved runtime-compatible manifest."""
    root = Path(project.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project.root = root
    source_revision_value = str(project.source.get("source_revision", ""))
    project.authoring = _normalise_authoring(project.authoring, source_revision_value)
    project.resolve()

    _write_json(root / "project.json", project.project)
    _write_json(root / "source" / "assembly_reference.json", project.source)
    _write_json(root / "generated" / "portrait_rig_manifest.json", project.generated_manifest)
    _write_json(root / "qa" / "status.json", {
        "status": project.project.get("qa", {}).get("status", "UNREVIEWED"),
        "source_revision": project.revision_report,
    })
    for filename in _AUTHORING_FILES:
        key = filename[:-5]
        _write_json(root / "authoring" / filename, project.authoring.get(key) or {})
    _write_json(root / "authoring" / _AUTHORING_META_FILE, {
        "version": AUTHORING_VERSION,
        "source_revision": project.authoring.get("source_revision", ""),
    })

    generated_image_root = root / "generated" / "rig" / "images"
    runtime_image_root = root / "rig" / "images"
    generated_image_root.mkdir(parents=True, exist_ok=True)
    runtime_image_root.mkdir(parents=True, exist_ok=True)
    # The images are the generated base; authoring corrections currently alter
    # manifest data only, so both views can share the same immutable pixels.
    for name, image in project.generated_images.items():
        # Existing generated image files are retained when loading a project.
        Image.fromarray(image, mode="RGBA").save(generated_image_root / f"{name}.png")
        Image.fromarray(image, mode="RGBA").save(runtime_image_root / f"{name}.png")

    manifest_path = root / "portrait_rig_manifest.json"
    _write_json(manifest_path, project.resolved_manifest)
    # Keep legacy/custom base names usable when a caller opens a project whose
    # original manifest was not portrait_rig_manifest.json.
    return manifest_path


def load_rig_project(directory: str | os.PathLike[str]) -> RigProject:
    """Load an editable project and report source revision/binding drift."""
    root = Path(directory).expanduser().resolve()
    project_data = _read_json(root / "project.json")
    if project_data.get("format") != RIG_PROJECT_FORMAT:
        raise ValueError(f"not a Rig Project: {root}")
    if int(project_data.get("version", 0)) != RIG_PROJECT_VERSION:
        raise ValueError(f"unsupported Rig Project version: {project_data.get('version')!r}")
    source = _read_json(root / "source" / "assembly_reference.json")
    generated_path = root / str((project_data.get("generated_base") or {}).get(
        "manifest", "generated/portrait_rig_manifest.json"))
    generated = _read_json(generated_path)
    generated_image_root = root / "generated" / "rig" / "images"
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
        generated_images = _load_generated_images(root, generated)
    authoring = _default_authoring()
    authoring_root = root / str((project_data.get("authoring") or {}).get("root", "authoring"))
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
    if (root / "project.json").is_file():
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
    if (root / "project.json").is_file() or list(root.glob("*_rig_manifest.json")):
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
    "set_chest_cage_bounds", "set_chest_cage_points", "set_chest_keyform",
    "reset_chest_to_auto",
]
