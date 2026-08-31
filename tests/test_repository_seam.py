from pathlib import Path


def test_downstream_python_has_no_seethrough_import_dependency():
    package = Path(__file__).resolve().parents[1] / "portrait_autorig"
    offenders = []
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import seethrough_engine" in text or "from seethrough_engine" in text:
            offenders.append(path.name)
    assert offenders == []


def test_downstream_dependency_list_excludes_gpu_inference_stack():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "torch" not in pyproject
    assert "diffusers" not in pyproject

