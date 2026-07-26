"""Anti-drift guards for files copied into self-contained skills.

Skills may only import their own modules, so genuinely common code is copied rather than
shared at runtime. These copies used to be held identical to EACH OTHER, which meant every
edit had to be made twice by hand and no copy was authoritative. They are now generated
from shared/ by scripts/sync_shared.py, and this asserts the tree is in sync.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_shared  # noqa: E402

UNDERSTANDING_SCRIPTS = ROOT / "skills" / "video-understanding" / "scripts"
SCRIPT_SCRIPTS = ROOT / "skills" / "video-script" / "scripts"


def test_shared_sources_and_targets_all_exist():
    for source_name, targets in sync_shared.TARGETS.items():
        assert (sync_shared.SHARED / source_name).is_file(), f"missing shared/{source_name}"
        assert targets, f"shared/{source_name} is distributed nowhere"
        for target in targets:
            assert (ROOT / target).is_file(), f"missing generated copy {target}"


@pytest.mark.parametrize(
    ("source_name", "target"),
    [
        pytest.param(source_name, target, id=f"{source_name}->{Path(target).parts[1]}")
        for source_name, targets in sorted(sync_shared.TARGETS.items())
        for target in targets
    ],
)
def test_generated_copies_match_their_shared_source(source_name, target):
    expected = sync_shared.rendered(source_name)
    actual = (ROOT / target).read_text(encoding="utf-8")
    assert actual == expected, (
        f"{target} drifted from shared/{source_name}. "
        "Edit shared/ and run: python scripts/sync_shared.py"
    )


def test_sync_check_mode_passes_on_a_clean_tree():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_shared.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_generated_copies_carry_the_do_not_edit_banner():
    """The banner is what stops someone editing a copy and losing the change on next sync."""
    for source_name, targets in sync_shared.TARGETS.items():
        for target in targets:
            head = (ROOT / target).read_text(encoding="utf-8")[:600]
            assert "GENERATED FILE" in head, f"{target} has no generated-file banner"
            assert f"shared/{source_name}" in head, f"{target} does not name its source"


def _top_level_literal(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path}: missing top-level constant {name}")


def test_asr_span_tol_matches_across_files():
    """consolidate.py is NOT a generated copy, so this constant is still checked by hand."""
    paths = {
        ROOT / "skills/video-understanding/scripts/consolidate.py",
        UNDERSTANDING_SCRIPTS / "brief_inputs.py",
        SCRIPT_SCRIPTS / "brief_inputs.py",
    }
    values = {
        str(path.relative_to(ROOT)): _top_level_literal(path, "_ASR_SPAN_TOL")
        for path in paths
    }

    assert set(values.values()) == {0.05}, (
        f"_ASR_SPAN_TOL drifted across files: {values}"
    )
