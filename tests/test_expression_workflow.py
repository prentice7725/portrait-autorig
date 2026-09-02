import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from portrait_autorig.expression_workflow import apply_image_donors, apply_rig_donors


class ExpressionWorkflowTests(unittest.TestCase):
    def _rig_dir(self, root: Path, name: str) -> Path:
        run = root / name
        run.mkdir()
        with (run / f"{name}_rig_manifest.json").open("w", encoding="utf-8") as f:
            json.dump({"parts": [{"name": "face", "tag": "face", "z": 0, "depth": 0}]}, f)
        return run

    def test_image_donors_are_attached_in_one_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._rig_dir(root, "base")
            eye = root / "eye.png"
            mouth = root / "mouth.png"
            Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(eye)
            Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(mouth)

            with patch("portrait_autorig.expression_workflow.attach_to_run") as attach:
                attach.return_value = {"parts": {"eye_closed_l": {}, "mouth_open": {}}}
                result = apply_image_donors(base, {"eye_closed": eye, "mouth_open": mouth})

            self.assertEqual(result.states, ("eye_closed", "mouth_open"))
            self.assertEqual(result.part_count, 2)
            donors = attach.call_args.args[1]
            self.assertEqual(set(donors), {"eye_closed", "mouth_open"})

    def test_rig_donors_merge_before_manifest_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._rig_dir(root, "base")
            eye = self._rig_dir(root, "eye")
            mouth = self._rig_dir(root, "mouth")

            def fake_pack(_base, _donor, states):
                state = states[0]
                return {"parts": [state], "report": {"states": {state: {"ok": True}}}}

            with patch("portrait_autorig.expression_workflow.transplant_pack", side_effect=fake_pack), \
                 patch("portrait_autorig.expression_workflow.write_expression_pack") as writer:
                writer.return_value = {"version": "0.1", "parts": {"a": {}, "b": {}}, "report": {}}
                result = apply_rig_donors(base, {"eye_closed": eye, "mouth_open": mouth})

            merged_pack = writer.call_args.args[1]
            self.assertEqual(merged_pack["parts"], ["eye_closed", "mouth_open"])
            self.assertEqual(set(merged_pack["report"]["states"]), {"eye_closed", "mouth_open"})
            self.assertEqual(result.part_count, 2)

            manifest = json.loads(next(base.glob("*_rig_manifest.json")).read_text(encoding="utf-8"))
            self.assertIn("expressions", manifest)


if __name__ == "__main__":
    unittest.main()
