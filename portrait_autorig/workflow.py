from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .assembly import load_assembly_bundle
from .bundle import load_portrait_bundle
from .compiler import compile_assembly_bundle, compile_bundle, compile_legacy_run


@dataclass(frozen=True)
class BuildResult:
    input_path: Path
    output_path: Path
    manifest_path: Path
    preflight_status: str
    rest_fidelity_status: str


def portrait_name(path: Path) -> str:
    name = path.name
    if name.endswith(".portrait"):
        return name[: -len(".portrait")]
    return name


def default_output_path(input_path: Path) -> Path:
    return input_path.parent / f"{portrait_name(input_path)}.rig"


def default_batch_output_path(input_dir: Path) -> Path:
    return input_dir / "rigs"


def discover_portrait_bundles(input_dir: Path, *, recursive: bool = False) -> list[Path]:
    pattern = "**/*.portrait" if recursive else "*.portrait"
    return sorted(path for path in input_dir.glob(pattern) if path.is_dir())


def bundle_kind(input_path: Path) -> str:
    """Validate a single Bundle by its contents and return its compiler kind.

    Directory names are deliberately ignored.  Composer Assembly Bundles and
    Portrait Bundles can therefore use arbitrary names (including names for
    future full-body characters); the manifest format selects the reader.
    """
    manifest_path = input_path / "manifest.json"
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError("manifest.json이 없습니다.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest.json을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json은 JSON object여야 합니다.")

    format_name = manifest.get("format")
    if format_name == "portrait-bundle":
        load_portrait_bundle(input_path)
        return "portrait"
    if format_name == "portrait-assembly":
        load_assembly_bundle(input_path)
        return "assembly"
    raise ValueError(f"지원하지 않는 Bundle format입니다: {format_name!r}")


def _manifest_status(manifest_path: Path) -> tuple[str, str]:
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    preflight = manifest.get("rig_preflight", {}).get("status", "UNKNOWN")
    fidelity = manifest.get("rest_fidelity", {}).get("status", "unknown")
    return str(preflight), str(fidelity)


def compile_portrait(
    input_path: Path,
    output_path: Path | None = None,
    *,
    legacy: bool = False,
    soften_back_hair: bool = False,
) -> BuildResult:
    input_path = input_path.expanduser().resolve()
    output_path = (output_path or default_output_path(input_path)).expanduser().resolve()
    gradient = ("back hair",) if soften_back_hair else ()
    compile_fn = compile_legacy_run if legacy else compile_bundle
    manifest = Path(
        compile_fn(str(input_path), str(output_path), gradient_tags=gradient)
    ).resolve()
    preflight, fidelity = _manifest_status(manifest)
    return BuildResult(
        input_path=input_path,
        output_path=output_path,
        manifest_path=manifest,
        preflight_status=preflight,
        rest_fidelity_status=fidelity,
    )


def compile_bundle_input(
    input_path: Path,
    output_path: Path | None = None,
    *,
    legacy: bool = False,
    soften_back_hair: bool = False,
) -> BuildResult:
    """Compile a single canonical Portrait or Composer Assembly Bundle."""
    if legacy:
        return compile_portrait(input_path, output_path, legacy=True,
                                soften_back_hair=soften_back_hair)
    input_path = input_path.expanduser().resolve()
    output_path = (output_path or default_output_path(input_path)).expanduser().resolve()
    kind = bundle_kind(input_path)
    gradient = ("back hair",) if soften_back_hair else ()
    compile_fn = compile_assembly_bundle if kind == "assembly" else compile_bundle
    manifest = Path(
        compile_fn(str(input_path), str(output_path), gradient_tags=gradient)
    ).resolve()
    preflight, fidelity = _manifest_status(manifest)
    return BuildResult(
        input_path=input_path,
        output_path=output_path,
        manifest_path=manifest,
        preflight_status=preflight,
        rest_fidelity_status=fidelity,
    )


def compile_batch(
    input_dir: Path,
    output_root: Path | None = None,
    *,
    recursive: bool = False,
    legacy: bool = False,
    soften_back_hair: bool = False,
    on_progress: Callable[[int, int, Path, BuildResult | None, Exception | None], None] | None = None,
) -> list[BuildResult]:
    input_dir = input_dir.expanduser().resolve()
    output_root = (output_root or default_batch_output_path(input_dir)).expanduser().resolve()
    inputs = discover_portrait_bundles(input_dir, recursive=recursive)
    if not inputs:
        raise ValueError(f"No .portrait bundles found in {input_dir}")

    output_root.mkdir(parents=True, exist_ok=True)
    results: list[BuildResult] = []
    failures: list[tuple[Path, Exception]] = []
    total = len(inputs)

    for index, input_path in enumerate(inputs, start=1):
        output_path = output_root / f"{portrait_name(input_path)}.rig"
        try:
            result = compile_portrait(
                input_path,
                output_path,
                legacy=legacy,
                soften_back_hair=soften_back_hair,
            )
            results.append(result)
            if on_progress:
                on_progress(index, total, input_path, result, None)
        except Exception as exc:  # batch keeps going so one bad portrait does not block the set
            failures.append((input_path, exc))
            if on_progress:
                on_progress(index, total, input_path, None, exc)

    if failures:
        detail = "; ".join(f"{path.name}: {error}" for path, error in failures)
        raise RuntimeError(f"{len(failures)}/{total} portrait builds failed: {detail}")
    return results
