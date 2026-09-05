"""Apply the optional or strict narration-review gate before TTS."""

import json
import os
from pathlib import Path


def review_narration_enabled(args):
    if args.review_narration is not None:
        return args.review_narration
    return _env_bool("REVIEW_NARRATION", True)


def require_narration_review(args):
    return args.require_narration_review or _env_bool("REQUIRE_NARRATION_REVIEW", False)


def _env_bool(name, default):
    raw = os.environ.get(name)
    return default if not raw else raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def review_result_status(work_dir):
    path = Path(work_dir) / "narration_review.json"
    if not path.exists():
        return {"ok": False, "reason": "missing or invalid narration_review.json"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "reason": "missing or invalid narration_review.json"}
    if not isinstance(data, dict):
        return {"ok": False, "reason": "missing or invalid narration_review.json"}
    findings = data.get("findings")
    if not isinstance(findings, list) or any(
        not isinstance(finding, dict)
        or not isinstance(finding.get("severity"), str)
        for finding in findings
    ):
        return {"ok": False, "reason": "missing or invalid narration_review.json"}
    error_count = sum(1 for finding in findings if finding["severity"] == "error")
    if data.get("parse_error"):
        return {"ok": False, "reason": "parse_error", "review": data, "errors": error_count}
    if error_count:
        return {
            "ok": False,
            "reason": f"error {error_count}",
            "review": data,
            "errors": error_count,
        }
    # Strict mode gates only on parse errors or factual error findings. The model's
    # holistic verdict stays advisory because craft-class findings are warnings.
    return {"ok": True, "reason": "ok", "review": data, "errors": error_count}


def clear_narration_review_artifacts(work_dir):
    """Remove prior review artifacts before a fresh pre-TTS review run."""
    for name in ("narration_review.json", "narration_review.md"):
        (Path(work_dir) / name).unlink(missing_ok=True)


def run_narration_review(work_dir, args, *, run, timeline="source"):
    """Run the review gate using the caller's skill-command runner."""
    strict = require_narration_review(args)
    if not review_narration_enabled(args) and not strict:
        return False
    try:
        clear_narration_review_artifacts(work_dir)
        # Pin the grounding timeline so stale cut artifacts cannot alter auto-detection.
        review_args = ["--work-dir", work_dir, "--timeline", timeline]
        if strict and timeline == "cut_output":
            review_args.append("--strict-evidence")
        run("video-script", "review.py", *review_args)
    except SystemExit as exc:
        if strict:
            raise SystemExit(f"严格解说评审失败，已阻止 TTS: {exc}") from exc
        print(f"[video-recap] ⚠️ 建议性评审失败，继续执行 TTS: {exc}", flush=True)
        return False

    status = review_result_status(work_dir)
    if strict and not status["ok"]:
        raise SystemExit(f"严格解说评审未通过，已阻止 TTS: {status['reason']}")
    if strict:
        print("[video-recap] ✅ 严格解说评审通过，继续 TTS", flush=True)
    return True
