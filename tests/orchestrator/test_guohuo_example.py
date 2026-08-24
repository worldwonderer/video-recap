import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "guohuo-60s"


def _load(name):
    return json.loads((EXAMPLE / name).read_text(encoding="utf-8"))


def test_guohuo_public_artifacts_are_portable_and_self_consistent():
    assert EXAMPLE.is_dir()
    json_paths = sorted(EXAMPLE.rglob("*.json"))
    assert json_paths
    for path in json_paths:
        json.loads(path.read_text(encoding="utf-8"))

    assert _load("captions.json") == _load("remotion/src/captions.json")

    manifest = _load("workflow-manifest.json")
    for stage in manifest["stages"]:
        for relative_path in stage.get("included", []):
            assert (EXAMPLE / relative_path).exists(), relative_path

    public_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in EXAMPLE.rglob("*")
        if path.is_file()
    )
    assert "/Users/" not in public_text
    assert "/Volumes/" not in public_text
    assert not re.search(r"\b(?:sk|tp)-[A-Za-z0-9_-]{8,}\b", public_text)

    media_suffixes = {".mp4", ".mov", ".mkv", ".wav", ".mp3", ".png", ".jpg"}
    assert not [
        path for path in EXAMPLE.rglob("*") if path.suffix.lower() in media_suffixes
    ]


def test_guohuo_timeline_delivery_and_source_ids_agree():
    delivery = _load("delivery-qc.json")
    timeline = _load("timeline.json")
    validated = _load("clip_plan_validated.json")
    sources = _load("multi_source_manifest.json")

    media = delivery["media"]
    assert timeline["duration"] == media["duration_seconds"]
    assert timeline["canvas"]["fps"] == media["fps"]
    assert media["frames"] == round(media["duration_seconds"] * media["fps"])

    known_source_ids = {item["source_id"] for item in sources["sources"]}
    clip_source_ids = {item["source_id"] for item in validated["clips"]}
    assert clip_source_ids <= known_source_ids

    composition = (EXAMPLE / "remotion/src/index.tsx").read_text(encoding="utf-8")
    assert f"durationInFrames={{{media['frames']}}}" in composition
    assert f"fps={{{media['fps']}}}" in composition


def test_guohuo_narration_lint_is_reproducible(tmp_path):
    work_dir = tmp_path / "guohuo-60s"
    shutil.copytree(EXAMPLE, work_dir)
    expected = json.loads((work_dir / "narration_lint.json").read_text(encoding="utf-8"))
    env = os.environ.copy()
    env.update(
        {
            "SPEECH_RATE": "7.3",
            "NARRATION_SPEED": "1.15",
            "PYTHONIOENCODING": "utf-8",
        }
    )

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills/video-script/scripts/validate.py"),
            "--work-dir",
            str(work_dir),
            "--mode",
            "cut_output",
            "--output-duration",
            "58.96",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    actual = json.loads((work_dir / "narration_lint.json").read_text(encoding="utf-8"))
    assert actual == expected
