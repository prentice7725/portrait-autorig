"""Spine 2D skeleton export, shared by the ComfyUI `SeeThrough_ExportSpine`
node and the standalone webui.

`nodes.py` reaches this through the full ComfyUI graph, where every layer has
already been through Marigold depth estimation, so its draw order comes from
`depth_median`. The webui has no depth pass, so it orders layers by the fixed
Portrait Mode tag vocabulary instead -- see `SEMANTIC_Z_ORDER`. `draw_order`
picks between the two, which is the only thing that differs between the two
callers; the coordinate conversion and the skeleton JSON are one
implementation.
"""

from __future__ import annotations

import json
import os
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .image import crop_to_alpha
from .semantic import SEMANTIC_Z_ORDER, semantic_rank

__all__ = [
    "DEFAULT_SPINE_NAMES",
    "SEMANTIC_Z_ORDER",
    "crop_to_alpha",
    "semantic_rank",
    "draw_order",
    "fill_missing_depths",
    "apply_depth_ordering",
    "layers_to_parts",
    "rename_parts",
    "build_skeleton",
    "write_spine_project",
    "export_rig_bundle",
]

# Default tag-to-Spine name mapping. Spine slot/attachment names become file
# names under images/, so these avoid spaces.
DEFAULT_SPINE_NAMES = {
    "front hair": "front-hair", "back hair": "back-hair",
    "hairf": "front-hair", "hairb": "back-hair", "hair": "hair",
    "head": "head", "headwear": "headwear",
    "face": "face", "irides": "irides", "eyebrow": "eyebrow",
    "eyewhite": "eye-white", "eyelash": "eyelash", "eyewear": "eyewear",
    "eyes": "eyes", "eyel": "eye-left", "eyer": "eye-right",
    "browl": "eyebrow-left", "browr": "eyebrow-right",
    "eyewhitel": "eye-white-left", "eyewhiter": "eye-white-right",
    "iridesl": "irides-left", "iridesr": "irides-right",
    "eyelashl": "eyelash-left", "eyelashr": "eyelash-right",
    "eyebrowl": "eyebrow-left", "eyebrowr": "eyebrow-right",
    "ears": "ears", "earl": "ear-left", "earr": "ear-right",
    "earwear": "earwear",
    "nose": "nose", "mouth": "mouth",
    "neck": "neck", "neckwear": "neckwear",
    "topwear": "topwear", "bottomwear": "bottomwear",
    "handwear": "handwear", "handwearl": "handwear-left", "handwearr": "handwear-right",
    "legwear": "legwear", "footwear": "footwear",
    "tail": "tail", "wings": "wings", "objects": "objects",
}

def draw_order(tag2pinfo: dict[str, dict]) -> list[str]:
    """Tags back to front, i.e. in Spine `slots` array order.

    Uses `depth_median` when any layer carries one -- that is the ComfyUI
    graph, and this reproduces what `SeeThrough_ExportSpine` did before this
    module existed, down to the `1` default for a layer that somehow lacks it.
    Otherwise falls back to `SEMANTIC_Z_ORDER`, keyed on the pre-rename tag.
    """
    if any("depth_median" in pinfo for pinfo in tag2pinfo.values()):
        return sorted(tag2pinfo, key=lambda t: tag2pinfo[t].get("depth_median", 1), reverse=True)
    return sorted(
        tag2pinfo,
        key=lambda t: semantic_rank(tag2pinfo[t].get("original_tag", t)),
    )


# `nodes.py` overrides raw depth for these once it knows where `face` sits:
# facial features must land in front of the face and ears behind it, whatever
# Marigold estimated for them.
_IN_FRONT_OF_FACE = ("nose", "mouth", "eyes", "eyel", "eyer")
_BEHIND_FACE = ("earr", "earl", "ears")
# Recovered residual pixels belong behind every semantic layer; > 1.0 puts them
# past anything a normalized depth map can produce.
BODY_REMAINDER_DEPTH = 1.001


def fill_missing_depths(tag2pinfo: dict[str, dict]) -> dict[str, dict]:
    """Give a layer the depth pass could not cover a `depth_median` taken from
    where `SEMANTIC_Z_ORDER` puts it among the layers that do have one.

    The depth batch is indexed by the v2 tag list, so a v3 run leaves `head`
    uncovered by an optional producer depth map. Left alone it would fall to
    `draw_order`'s default of 1 and land at the very back -- not a decision,
    just an artifact of the default. Interpolating between its nearest covered
    semantic neighbours puts it where it belongs relative to real estimates.
    (`nodes.py` sidesteps this by dropping uncovered layers outright, which
    costs it the head layer entirely; keeping it is more useful for a rig.)
    """
    known = {t: p["depth_median"] for t, p in tag2pinfo.items() if "depth_median" in p}
    if not known:
        return tag2pinfo
    ranked = sorted(
        ((semantic_rank(tag2pinfo[t].get("original_tag", t)), d) for t, d in known.items()),
    )

    for tag, pinfo in tag2pinfo.items():
        if "depth_median" in pinfo or tag == "body_remainder":
            continue
        rank = semantic_rank(pinfo.get("original_tag", tag))
        behind = [d for r, d in ranked if r < rank]   # semantically further back
        front = [d for r, d in ranked if r > rank]    # semantically nearer
        if behind and front:
            pinfo["depth_median"] = (behind[-1] + front[0]) / 2.0
        elif behind:
            pinfo["depth_median"] = behind[-1] - 0.001
        else:
            pinfo["depth_median"] = front[0] + 0.001
    return tag2pinfo


def apply_depth_ordering(tag2pinfo: dict[str, dict]) -> dict[str, dict]:
    """Nudge `depth_median` so facial features sort sensibly, mutating and
    returning `tag2pinfo`. Mirrors the adjustment `nodes.py` makes after
    Marigold: depth around eyes and ears is unreliable at portrait scale, and
    an ear drawn over a cheek is worse than a slightly wrong ordinal."""
    if "body_remainder" in tag2pinfo:
        tag2pinfo["body_remainder"]["depth_median"] = BODY_REMAINDER_DEPTH

    face = tag2pinfo.get("face")
    if face is None or "depth_median" not in face:
        return tag2pinfo
    face_dm = face["depth_median"]

    for tag in _IN_FRONT_OF_FACE:
        pinfo = tag2pinfo.get(tag)
        if pinfo is not None and pinfo.get("depth_median", 1) > face_dm:
            pinfo["depth_median"] = face_dm - 0.001
    for tag in _BEHIND_FACE:
        if tag in tag2pinfo:
            tag2pinfo[tag]["depth_median"] = face_dm + 0.001
    return tag2pinfo


def layers_to_parts(layer_dict: dict[str, np.ndarray], *, alpha_threshold: int = 10,
                    body_remainder: np.ndarray | None = None,
                    depth_dict: dict[str, np.ndarray] | None = None) -> dict[str, dict]:
    """Turn `{tag: full-canvas RGBA}` into the `tag2pinfo` shape the export
    works on: each layer cropped to its own bounds, plus `xyxy` locating that
    crop on the canvas. Layers with nothing visible are dropped.

    `body_remainder` (the Silhouette Guard's leftover pixels) is added first
    when it has content, mirroring `nodes.py`, which pins it behind everything
    -- insertion order is what its preview compositor's alpha formula assumes.

    With `depth_dict`, each covered layer also gets a `depth_median` (taken
    over its visible pixels before cropping, as `nodes.py` does) and
    `apply_depth_ordering` is run, which switches `draw_order` from the
    semantic fallback to depth sorting. Layers the depth pass did not cover are
    slotted in by `fill_missing_depths` rather than left to sort at depth 1.
    """
    parts: dict[str, dict] = {}

    if body_remainder is not None:
        cropped = crop_to_alpha(np.asarray(body_remainder), alpha_threshold)
        if cropped is not None:
            img, xyxy = cropped
            parts["body_remainder"] = {"img": img, "xyxy": xyxy, "tag": "body_remainder",
                                       "is_recovery": True}

    for tag, img in layer_dict.items():
        if img is None:
            continue
        arr = np.asarray(img)
        if arr.ndim != 3 or arr.shape[-1] != 4:
            continue
        cropped = crop_to_alpha(arr, alpha_threshold)
        if cropped is None:
            continue
        crop_img, xyxy = cropped
        pinfo = {"img": crop_img, "xyxy": xyxy, "tag": tag}
        if depth_dict is not None and tag in depth_dict:
            visible = arr[..., -1] > alpha_threshold
            depth = np.asarray(depth_dict[tag])
            pinfo["depth_median"] = float(np.median(depth[visible])) if np.any(visible) else 1.0
        parts[tag] = pinfo

    if depth_dict is not None:
        fill_missing_depths(parts)
        apply_depth_ordering(parts)

    return parts


def rename_parts(tag2pinfo: dict[str, dict],
                 mapping: dict[str, str] | None = None) -> dict[str, dict]:
    """Re-key by Spine-friendly name, keeping the original tag on each entry so
    `draw_order` can still rank it. Equivalent to `SeeThrough_LayerRename`."""
    mapping = {**DEFAULT_SPINE_NAMES, **(mapping or {})}
    renamed: dict[str, dict] = {}
    for tag, pinfo in tag2pinfo.items():
        new_name = mapping.get(tag, tag)
        entry = dict(pinfo)
        entry["tag"] = new_name
        entry.setdefault("original_tag", tag)
        renamed[new_name] = entry
    return renamed


def build_skeleton(tag2pinfo: dict[str, dict], frame_size: tuple[int, int], *,
                   spine_version: str = "4.2.28") -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Build the Spine skeleton JSON and the images it references.

    Returns `(skeleton_dict, {png_stem: rgba_array})`. Spine's origin is the
    bottom-center of the canvas with Y up, while the layer boxes are Y-down
    from the top-left, hence the conversion below.
    """
    canvas_h, canvas_w = int(frame_size[0]), int(frame_size[1])

    slots: list[dict[str, Any]] = []
    attachments: dict[str, Any] = {}
    images: dict[str, np.ndarray] = {}

    for tag in draw_order(tag2pinfo):
        pinfo = tag2pinfo[tag]
        img = pinfo.get("img")
        if img is None:
            continue

        safe_name = tag.replace(" ", "-")
        img_h, img_w = img.shape[0], img.shape[1]
        x1, y1, x2, y2 = (int(v) for v in pinfo.get("xyxy", [0, 0, img_w, img_h]))

        # Center of this layer on the canvas, top-left origin and Y down ...
        center_x_canvas = (x1 + x2) / 2.0
        center_y_canvas = (y1 + y2) / 2.0
        # ... expressed against Spine's bottom-center origin with Y up.
        spine_x = center_x_canvas - canvas_w / 2.0
        spine_y = canvas_h - center_y_canvas

        images[safe_name] = img
        slots.append({"name": safe_name, "bone": "root", "attachment": safe_name})
        attachments[safe_name] = {
            safe_name: {
                "x": round(spine_x, 2),
                "y": round(spine_y, 2),
                "width": img_w,
                "height": img_h,
            }
        }

    skeleton = {
        "skeleton": {
            "hash": "",
            "spine": spine_version,
            "x": round(-canvas_w / 2.0, 2),
            "y": 0,
            "width": canvas_w,
            "height": canvas_h,
            "images": "./images/",
            "audio": "",
        },
        "bones": [{"name": "root"}],
        "slots": slots,
        "skins": [{"name": "default", "attachments": attachments}],
        "animations": {"setup": {}},
    }
    return skeleton, images


def write_spine_project(project_dir: str, name: str, tag2pinfo: dict[str, dict],
                        frame_size: tuple[int, int], *,
                        spine_version: str = "4.2.28") -> str:
    """Write `{project_dir}/{name}.json` plus `{project_dir}/images/*.png`, the
    layout the Spine editor opens directly. Returns the JSON path."""
    images_dir = os.path.join(project_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    skeleton, images = build_skeleton(tag2pinfo, frame_size, spine_version=spine_version)
    for png_stem, img in images.items():
        Image.fromarray(img).save(os.path.join(images_dir, f"{png_stem}.png"))

    json_path = os.path.join(project_dir, f"{name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(skeleton, f, indent=2, ensure_ascii=False)
    return json_path


def export_rig_bundle(rig_dir: str, output_dir: str, *, name: str = "portrait",
                      spine_version: str = "4.2.28") -> str:
    """Export an existing Rig Bundle without reading its Portrait producer."""
    manifests = sorted(
        filename for filename in os.listdir(rig_dir)
        if filename.endswith("_rig_manifest.json")
    )
    if not manifests:
        raise FileNotFoundError(f"no *_rig_manifest.json in {rig_dir}")
    with open(os.path.join(rig_dir, manifests[0]), encoding="utf-8") as handle:
        rig = json.load(handle)
    parts: dict[str, dict] = {}
    for part in rig.get("parts", []):
        image_path = os.path.join(rig_dir, *part["image"].split("/"))
        image = np.array(Image.open(image_path).convert("RGBA"))
        tag = str(part["tag"])
        parts[tag] = {
            "img": image,
            "xyxy": list(part["xyxy"]),
            "depth_median": float(part["depth"]),
            "tag": tag,
            "original_tag": tag,
        }
    renamed = rename_parts(parts)
    canvas = rig["canvas"]
    return write_spine_project(
        output_dir, name, renamed,
        (int(canvas["height"]), int(canvas["width"])),
        spine_version=spine_version,
    )


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Export a Rig Bundle to Spine")
    parser.add_argument("rig_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--name", default="portrait")
    parser.add_argument("--spine-version", default="4.2.28")
    args = parser.parse_args(argv)
    print(export_rig_bundle(args.rig_dir, args.output_dir, name=args.name,
                            spine_version=args.spine_version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
