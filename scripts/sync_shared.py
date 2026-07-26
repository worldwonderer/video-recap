#!/usr/bin/env python3
"""Distribute shared/ into the skills that need it.

Skills are self-contained on purpose: a skill's scripts may only import that skill's own
modules (tests/orchestrator/test_test_suite_architecture.py enforces it), and the stages
communicate solely through work_dir artifacts. So genuinely common code is COPIED into
each skill rather than imported across skills.

What was missing was a source of truth. The copies were kept identical to each other by
an anti-drift test, which meant every edit had to be applied by hand in both places and
neither copy was authoritative. Now shared/ is the source, this script distributes it,
and the test asserts each copy equals banner + source.

  python scripts/sync_shared.py           # write the copies
  python scripts/sync_shared.py --check    # verify only (CI / pytest)
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"

BANNER_BY_SUFFIX = {
    ".py": (
        "# GENERATED FILE — do not edit here.\n"
        "# Source: shared/{source}. Edit that, then run: python scripts/sync_shared.py\n"
        "# Copied rather than imported because skills must stay self-contained.\n"
    ),
    ".md": (
        "<!-- GENERATED FILE — do not edit here. Source: shared/{source}.\n"
        "     Edit that, then run: python scripts/sync_shared.py -->\n"
    ),
}

# source in shared/  ->  every path it is copied to
TARGETS = {
    "fingerprint.py": [
        "skills/video-assemble/scripts/fingerprint.py",
        "skills/video-cut/scripts/fingerprint.py",
        "skills/video-recap/scripts/fingerprint.py",
        "skills/video-script/scripts/fingerprint.py",
        "skills/video-understanding/scripts/fingerprint.py",
        "skills/video-voiceover/scripts/fingerprint.py",
    ],
    # The writing brief and its lint are twins: video-understanding produces the brief and
    # video-script validates narration against the same facts. They must not drift.
    **{
        f"{name}.py": [
            f"skills/video-understanding/scripts/{name}.py",
            f"skills/video-script/scripts/{name}.py",
        ]
        for name in (
            "agent_brief",
            "agent_text",
            "brief_context",
            "brief_inputs",
            "brief_timeline",
            "deslop_qc",
            "narration_lint",
            "speech_ownership",
            "timeline_fusion",
        )
    },
    # Same module, different public name in each skill.
    "brief_entry.py": [
        "skills/video-understanding/scripts/brief.py",
        "skills/video-script/scripts/narration.py",
    ],
    "creative-editing-playbook.md": [
        "skills/video-recap/references/creative-editing-playbook.md",
        "skills/video-script/references/creative-editing-playbook.md",
    ],
}


def rendered(source_name):
    """Banner + source content, i.e. exactly what the copy on disk must contain."""
    source = SHARED / source_name
    banner = BANNER_BY_SUFFIX[source.suffix].format(source=source_name)
    text = source.read_text(encoding="utf-8")
    if source.suffix == ".py":
        # Keep any module docstring first so `python -c "import x; x.__doc__"` still works
        # and tooling that reads the first statement is unaffected.
        return _insert_after_docstring(text, banner)
    return banner + text


def _insert_after_docstring(text, banner):
    import ast

    try:
        module = ast.parse(text)
    except SyntaxError:
        return banner + text
    body = module.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        lines = text.splitlines(keepends=True)
        cut = body[0].end_lineno
        return "".join(lines[:cut]) + banner + "".join(lines[cut:])
    return banner + text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify copies match without writing"
    )
    args = parser.parse_args(argv)

    stale, written = [], 0
    for source_name, targets in sorted(TARGETS.items()):
        if not (SHARED / source_name).is_file():
            print(f"missing source: shared/{source_name}", file=sys.stderr)
            return 2
        expected = rendered(source_name)
        for target in targets:
            path = ROOT / target
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current == expected:
                continue
            if args.check:
                stale.append(target)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")
                written += 1

    if args.check:
        if stale:
            print(
                "These copies are out of sync with shared/:\n  "
                + "\n  ".join(sorted(stale))
                + "\nRun: python scripts/sync_shared.py",
                file=sys.stderr,
            )
            return 1
        print(f"All {sum(len(v) for v in TARGETS.values())} copies match shared/.")
        return 0

    print(f"Synced {written} file(s) from shared/ ({'no changes' if not written else 'updated'}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
