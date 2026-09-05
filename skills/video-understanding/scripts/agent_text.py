"""Normalize, split, budget, and de-duplicate narration text."""

import copy
import re

from lib import CONFIG, log
from deslop_qc import _sentence_pieces, _text_units


def _format_frame_facts(scene):
    """将帧动作描述格式化为可注入 agent brief 的文本。"""
    facts = scene.get("frame_facts", {})
    if not facts:
        return ""
    lines = [f"    {ts}s: {'; '.join(facts[ts])}" for ts in sorted(facts, key=float)]
    return "\n  帧动作:\n" + "\n".join(lines)


def _text_char_count(text):
    """计算文本的有效字数（去除标点和空白，这些不占 TTS 朗读时间）。"""
    return len(
        re.sub(
            r'[，。！？、；：…“”‘’《》〈〉\s"\'「」『』（）()【】\[\]—～·,.!?;:\\-]',
            "",
            text,
        )
    )


def _split_text_by_sentence_windows(text, min_chars=500, max_chars=800):
    """Clipto-style three-tier sentence boundary splitting for long ASR text."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if _text_units(text) <= max_chars:
        return _sentence_pieces(text)

    result = []
    rest = text
    sentence_marks = "。！？!?；;."
    while _text_units(rest) > max_chars:
        # The min/max thresholds are unit-based but punctuation is char-indexed.
        # For Chinese (the dominant recap target) these are nearly identical; for
        # non-CJK this remains a safe sentence-boundary heuristic around words.
        char_min = min(len(rest), max(1, min_chars))
        char_max = min(len(rest), max(1, max_chars))
        window = rest[:char_max]
        cut = max(window.rfind(mark) for mark in sentence_marks)
        if cut + 1 < char_min:
            outside = -1
            for i, ch in enumerate(rest[char_max:], start=char_max):
                if ch in sentence_marks:
                    outside = i
                    break
            cut = outside if outside >= 0 and outside + 1 <= len(rest) else char_max - 1
        piece = rest[: cut + 1].strip()
        if not piece:
            piece = rest[:char_max].strip()
            cut = char_max - 1
        result.append(piece)
        rest = rest[cut + 1 :].strip()
    if rest:
        result.append(rest)
    return result


def _timed_sentence_pieces(seg, min_chars, max_chars):
    """Split one ASR segment into timed sentence pieces with approximate spans."""
    text = seg["text"].strip()
    if not text:
        return []
    start, end = seg["start"], seg["end"]
    pieces = []
    for sentence in _sentence_pieces(text):
        if _text_units(sentence) > max_chars:
            pieces.extend(
                _split_text_by_sentence_windows(
                    sentence, min_chars=min_chars, max_chars=max_chars
                )
            )
        else:
            pieces.append(sentence)
    total_units = sum(max(1, _text_units(piece)) for piece in pieces)
    duration = end - start
    cursor = start
    timed = []
    for idx, piece in enumerate(pieces):
        units = max(1, _text_units(piece))
        piece_end = end if idx == len(pieces) - 1 else cursor + duration * units / total_units
        timed.append(
            {
                "start": round(cursor, 2),
                "end": round(piece_end, 2),
                "text": piece,
                "char_count": _text_units(piece),
            }
        )
        cursor = piece_end
    return timed


def _scene_ids_for_range(scenes, start, end):
    duration = max(0.001, end - start)
    scene_ids = []
    for scene in scenes:
        overlap = _overlap_seconds(start, end, scene["start"], scene["end"])
        # Ignore tiny boundary tails from approximate ASR sentence timing. A
        # scene id should mean the chunk materially belongs to that scene.
        if overlap and (overlap >= duration * 0.2 or overlap >= 3.0):
            scene_ids.append(scene["scene_id"])
    return scene_ids


def _chunk_asr_for_writing(segments, scenes_analysis, min_chars=None, max_chars=None):
    """Chunk ASR into semantic windows before an agent writes long-dialogue recaps.

    The strategy mirrors Clipto's segment splitter: accumulate a window, prefer
    the last sentence boundary inside max length, allow a slightly longer first
    boundary outside the window, and fall back to the remaining text. CJK text is
    measured by characters; non-CJK text is measured by words.
    """
    min_chars = CONFIG["asr_chunk_min_chars"] if min_chars is None else min_chars
    max_chars = CONFIG["asr_chunk_max_chars"] if max_chars is None else max_chars
    pieces = [
        piece
        for seg in segments
        for piece in _timed_sentence_pieces(seg, min_chars, max_chars)
    ]

    chunks = []
    current = []
    current_units = 0
    current_scene_ids = set()

    def flush():
        nonlocal current, current_units, current_scene_ids
        if not current:
            return
        chunks.append(
            {
                "chunk_id": len(chunks),
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "scene_ids": sorted(
                    current_scene_ids, key=lambda sid: (isinstance(sid, str), sid)
                ),
                "char_count": current_units,
                "text": " ".join(piece["text"] for piece in current).strip(),
                "segments": current,
            }
        )
        current = []
        current_units = 0
        current_scene_ids = set()

    for piece in pieces:
        units = max(1, piece["char_count"])
        piece_scene_ids = set(
            _scene_ids_for_range(scenes_analysis, piece["start"], piece["end"])
        )
        crosses_scene = (
            current
            and current_scene_ids
            and piece_scene_ids
            and not (current_scene_ids & piece_scene_ids)
        )
        if crosses_scene and current_units >= min_chars:
            flush()
        if current and current_units >= min_chars and current_units + units > max_chars:
            flush()
        current.append(piece)
        current_scene_ids.update(piece_scene_ids)
        current_units += units
        if current_units >= max_chars:
            flush()
    flush()
    return chunks


def _truncate_at_sentence(text, max_chars):
    """在句子边界截断，不产生残句。max_chars 按有效字符计（不含标点空白）。"""
    if _text_char_count(text) <= max_chars:
        return text
    eff = 0
    cutoff = len(text)
    for i, ch in enumerate(text):
        eff += 1 if _text_char_count(ch) else 0
        if eff > max_chars:
            cutoff = i + 1
            break
    idx = max(text[:cutoff].rfind(sep) for sep in ["。", "！", "？", "!", "?"])
    if idx > 0:
        return text[: idx + 1]
    idx = max(text[:cutoff].rfind(sep) for sep in ["，", "、", "；", ","])
    if idx > 3:
        return text[:idx] + "。"
    return ""


def _char_bigrams(text):
    return {text[i : i + 2] for i in range(len(text) - 1) if text[i : i + 2].strip()}


def _post_dedup_narration(narration):
    """去除相邻相似解说段（bigram 重叠 >60% 则合并）。"""
    if len(narration) < 2:
        return narration
    result = [narration[0]]
    for seg in narration[1:]:
        prev = result[-1]
        set_a, set_b = _char_bigrams(prev["narration"]), _char_bigrams(seg["narration"])
        if not set_a or not set_b:
            result.append(seg)
            continue
        overlap = len(set_a & set_b) / min(len(set_a), len(set_b))
        # Only merge near-identical adjacent beats. Short Chinese beats share many
        # bigrams by chance, so a low threshold collapses intentional parallel beats
        # ("他不再试探" / "他直接赌上全力") and silently drops density below target.
        if overlap > 0.6:
            # Validation is also the handoff boundary for renderer metadata: keep the
            # overlays authored on either merged beat.
            merged_overlays = copy.deepcopy(
                prev.get("visual_overlays", []) + seg.get("visual_overlays", [])
            )
            if len(seg["narration"]) > len(prev["narration"]):
                prev["narration"] = seg["narration"]
            prev["end"] = seg["end"]
            prev["pause_after_ms"] = seg["pause_after_ms"]
            if merged_overlays:
                prev["visual_overlays"] = merged_overlays
            log(f"  去重合并: {prev['start']:.0f}-{prev['end']:.0f}s")
        else:
            result.append(seg)
    removed = len(narration) - len(result)
    if removed:
        log(f"  去重: {len(narration)} → {len(result)} 段 (合并 {removed} 段)")
    return result


def _scene_available_seconds(start, end):
    return max(0.0, end - start - CONFIG["narration_tail_pad_seconds"])


def _recommended_char_budget(start, end):
    # account for the global narration atempo (CONFIG['narration_speed']) so a beat's text
    # is budgeted against the FINAL sped-up audio, not the raw TTS rate — otherwise windows
    # are over-sized and the bed shows long silent gaps between sentences.
    effective_rate = (
        CONFIG["speech_rate"] * CONFIG["speech_safety_margin"] * CONFIG["narration_speed"]
    )
    return int(_scene_available_seconds(start, end) * effective_rate)


def _find_scene_for_midpoint(scenes_analysis, start, end):
    mid = (start + end) / 2
    for scene in scenes_analysis:
        if scene["start"] <= mid <= scene["end"]:
            return scene
    return None


def _normalise_narration_segment(seg):
    """Normalize one lint-validated narration segment for the full-mode rewrite.

    Authored timing is a delivery contract: scene boundaries are approximate
    visual-analysis buckets, so start/end are never clamped here.
    """
    item = {
        "start": round(seg["start"], 2),
        "end": round(seg["end"], 2),
        "narration": str(seg["narration"]).strip(),
        "pause_after_ms": int(seg.get("pause_after_ms", CONFIG["breath_ms"])),
        "overlaps_speech": bool(seg.get("overlaps_speech", True)),
    }
    for optional_key in (
        "source_start",
        "source_end",
        "source_clip_id",
        "source_entry_policy",
        "source_entry_reason",
    ):
        if optional_key in seg:
            item[optional_key] = seg[optional_key]
    # carry the per-beat emotion/tone tag (MiMo TTS instruct) through lint untouched
    if seg.get("emotion"):
        item["emotion"] = seg["emotion"].strip()
    # Renderer-owned metadata survives the validation rewrite; the recap orchestrator
    # filters supported overlay kinds later.
    if "visual_overlays" in seg:
        item["visual_overlays"] = copy.deepcopy(seg["visual_overlays"])
    return item


def _clean_narration_punctuation(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r'[，：、；,]["\']?[。！？]', "。", text)
    return re.sub(r'["\']。$', "。", text)


def _overlap_seconds(start, end, other_start, other_end):
    return max(0.0, min(end, other_end) - max(start, other_start))
