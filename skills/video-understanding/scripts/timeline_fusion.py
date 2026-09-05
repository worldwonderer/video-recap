"""Fuse scenes, ASR, and quiet windows for narration planning."""

from lib import CONFIG
from agent_text import _overlap_seconds, _recommended_char_budget
from narration_lint import _validate_narration_budget


def _quiet_windows(silence_periods):
    return [qp for qp in silence_periods if not qp["has_speech"]]


def _align_narration_to_quiet(narration, scenes_analysis, silence_periods):
    """Recompute overlaps_speech from real quiet windows; keep the agent's timing.

    The dense continuous-bed design places narration ON the pictured beat over a
    ducked original bed, so segments are never relocated into silence gaps. Only
    the overlaps_speech flag that the ducking stage consumes is corrected, leaving
    the agent's start/end (and text) intact.

    Budget/dedup runs FIRST so a dedup-merged beat's overlaps_speech reflects its
    extended timing, not its original shorter span.
    """
    aligned = _validate_narration_budget(narration, scenes_analysis)
    quiet_windows = _quiet_windows(silence_periods)
    quiet_ratio_min = CONFIG["quiet_overlap_min_ratio"]
    for n in aligned:
        seg_dur = n["end"] - n["start"]
        quiet_overlap = sum(
            _overlap_seconds(n["start"], n["end"], qw["start"], qw["end"])
            for qw in quiet_windows
        )
        n["overlaps_speech"] = quiet_overlap < max(0.3, seg_dur * quiet_ratio_min)
    return aligned


def _scene_asr_lines(asr_result, scene):
    lines = []
    for seg in asr_result:
        if scene["start"] < seg["end"] and scene["end"] > seg["start"] and seg["text"]:
            lines.append(f"    [{seg['start']:.1f}-{seg['end']:.1f}] {seg['text']}")
    return lines


def _quiet_windows_for_scene(silence_periods, scene):
    windows = []
    for qp in _quiet_windows(silence_periods):
        if qp["start"] < scene["end"] and qp["end"] > scene["start"]:
            start = max(qp["start"], scene["start"])
            end = min(qp["end"], scene["end"])
            if end > start:
                windows.append((start, end))
    return windows


def _build_timeline_fusion(scenes, asr_segments, silence_periods):
    """Fuse VLM scenes, ASR dialogue and quiet narration slots on one timeline."""
    fusion = []
    quiet_windows = _quiet_windows(silence_periods)
    for scene in scenes:
        start, end = scene["start"], scene["end"]
        dialogue_segments = []
        dialogue_overlap = 0.0
        for seg in asr_segments:
            overlap = _overlap_seconds(start, end, seg["start"], seg["end"])
            if overlap <= 0:
                continue
            dialogue_overlap += overlap
            dialogue_segments.append(
                {
                    "start": round(seg["start"], 2),
                    "end": round(seg["end"], 2),
                    "overlap_seconds": round(overlap, 2),
                    "text": seg["text"],
                }
            )

        narration_slots = []
        for window in quiet_windows:
            overlap = _overlap_seconds(start, end, window["start"], window["end"])
            if overlap <= 0:
                continue
            slot_start = max(start, window["start"])
            slot_end = min(end, window["end"])
            narration_slots.append(
                {
                    "start": round(slot_start, 2),
                    "end": round(slot_end, 2),
                    "duration": round(slot_end - slot_start, 2),
                    "char_budget": _recommended_char_budget(slot_start, slot_end),
                }
            )

        fusion.append(
            {
                "scene_id": scene["scene_id"],
                "time_range": [round(start, 2), round(end, 2)],
                "visual_description": scene["description"],
                "depth_analysis": scene.get("depth_analysis", ""),
                "frame_facts": scene.get("frame_facts", {}),
                "dialogue_segments": dialogue_segments,
                "dialogue_overlap_seconds": round(dialogue_overlap, 2),
                "narration_slots": narration_slots,
                "recommended_mode": "quiet-slot"
                if narration_slots and dialogue_overlap < (end - start) * 0.4
                else "ducked-bed",
            }
        )
    return fusion
