"""Behaviour contract for the shared full-file fingerprint helper.

The digest is compared ACROSS skills — video-cut writes edited_source.mp4.meta.json,
video-recap and video-assemble read it back — so every skill must produce the same value
for the same bytes. The seven hand-written copies are now generated from
shared/fingerprint.py (byte-equality is asserted in test_brief_narration_parity), so what
is left to prove here is that the implementation behaves correctly and that each consumer
still exposes it under the name its own code uses.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# module path -> the attribute that module's own code calls
CONSUMERS = (
    ("skills/video-assemble/scripts/artifacts.py", "_file_fingerprint"),
    ("skills/video-cut/scripts/cut_contract.py", "file_fingerprint"),
    ("skills/video-recap/scripts/materials.py", "file_fingerprint"),
    ("skills/video-recap/scripts/recap_runtime.py", "_file_fingerprint"),
    ("skills/video-script/scripts/lib.py", "file_fingerprint"),
    ("skills/video-understanding/scripts/lib.py", "file_fingerprint"),
    ("skills/video-voiceover/scripts/lib.py", "file_fingerprint"),
)


def _load(rel_path, index):
    """Import one skill module under a unique name, in its own module namespace.

    Every skill ships its own top-level `lib` (and `fingerprint`, `narration`, ...), which
    is why the suite runs one pytest process per skill. Loading several here would resolve
    `from lib import ...` against whichever skill was imported first, so each load gets a
    clean sys.modules for the bare skill-local names, restored afterwards.
    """
    path = ROOT / rel_path
    scripts_dir = str(path.parent)
    skill_local = {p.stem for p in path.parent.glob("*.py")}
    shadowed = {name: sys.modules.pop(name) for name in skill_local if name in sys.modules}

    spec = importlib.util.spec_from_file_location(f"_fp_probe_{index}", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, scripts_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_dir)
        for name in skill_local:
            sys.modules.pop(name, None)
        sys.modules.update(shadowed)
    return module


@pytest.fixture(scope="module")
def shared_fingerprint():
    spec = importlib.util.spec_from_file_location(
        "_shared_fingerprint", ROOT / "shared" / "fingerprint.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def consumers():
    return [
        (rel, getattr(_load(rel, index), attr))
        for index, (rel, attr) in enumerate(CONSUMERS)
    ]


def test_every_skill_exposes_a_fingerprint_that_agrees_with_the_others(consumers, tmp_path):
    sample = tmp_path / "asset.bin"
    sample.write_bytes(b"video-recap-skills" * 5000)
    digests = {rel: fn(sample) for rel, fn in consumers}

    assert len(set(digests.values())) == 1, f"implementations disagree: {digests}"
    # content-addressed: an independent copy at a different path matches
    copy = tmp_path / "copied.bin"
    copy.write_bytes(sample.read_bytes())
    for rel, fn in consumers:
        assert fn(copy) == digests[rel], f"{rel} is not content-addressed"


def test_fingerprint_never_serves_a_stale_digest(shared_fingerprint, tmp_path):
    """The memo is keyed on identity metadata, but the guarantee callers rely on is
    content-addressing: rewriting a file in place must yield a new digest."""
    target = tmp_path / "rewritten.bin"
    target.write_bytes(b"before")
    first = shared_fingerprint.file_fingerprint(target)

    # Same length, so size cannot distinguish the revisions and only mtime can. mtime is
    # advanced explicitly rather than trusting host clock resolution, so this exercises the
    # memo key on every filesystem CI runs on.
    target.write_bytes(b"after!")
    stat = os.stat(target)
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert shared_fingerprint.file_fingerprint(target) != first

    target.write_bytes(b"before")
    stat = os.stat(target)
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000))
    assert shared_fingerprint.file_fingerprint(target) == first


def test_fingerprint_is_memoized_within_a_process(shared_fingerprint, tmp_path, monkeypatch):
    """One understanding run fingerprints the source video 8-10 times and the whole
    extracted frame set 2-3 times. Without a memo that is gigabytes of redundant reads."""
    target = tmp_path / "memo.bin"
    target.write_bytes(b"x" * 100_000)
    reads = {"count": 0}
    real_open = open

    def counting_open(*args, **kwargs):
        reads["count"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(shared_fingerprint, "open", counting_open, raising=False)
    digests = {shared_fingerprint.file_fingerprint(target) for _ in range(5)}

    assert len(digests) == 1
    assert reads["count"] == 1, f"re-read the file {reads['count']} times"


def test_memo_key_is_device_inode_size_and_mtime(shared_fingerprint, tmp_path):
    target = tmp_path / "identity.bin"
    target.write_bytes(b"abc")
    stat = os.stat(target)
    assert shared_fingerprint._file_identity(target) == (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
    )


def test_value_fingerprint_is_stable_across_key_order(shared_fingerprint):
    """Cut writes a plan fingerprint that assemble and recap re-derive and compare."""
    left = {"b": [1, 2], "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "b": [1, 2]}
    assert shared_fingerprint.value_fingerprint(left) == shared_fingerprint.value_fingerprint(right)
    assert shared_fingerprint.value_fingerprint(left) != shared_fingerprint.value_fingerprint(
        {"a": {"x": 1, "y": 2}, "b": [2, 1]}
    )
