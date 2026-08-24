"""Fish Audio TTS transport for the video-voiceover skill.

The provider returns audio bytes rather than JSON. Keep the request, response validation,
and secret-safe error handling isolated here so voiceover.py only selects an engine.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from lib import (
    CONFIG,
    DEFAULT_FISH_TTS_API_URL,
    DEFAULT_FISH_TTS_MODEL,
    _sanitize_api_error,
)


def _fish_payload(text, rate="+0%"):
    try:
        speed = 1.0 + float(str(rate).rstrip("%")) / 100.0
    except (TypeError, ValueError):
        speed = 1.0
    payload = {
        "text": text,
        "format": "wav",
        "normalize": True,
        "prosody": {
            "speed": max(0.5, min(2.0, speed)),
            "volume": 0,
            "normalize_loudness": True,
        },
    }
    reference_id = str(CONFIG.get("fish_tts_reference_id") or "").strip()
    if reference_id:
        payload["reference_id"] = reference_id
    return payload


def synthesize_fish_audio(text, output_path, rate="+0%", **_ignored):
    """Synthesize one narration block and atomically write the WAV response."""
    api_key = str(CONFIG.get("fish_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("请设置 FISH_API_KEY 用于 Fish Audio TTS")

    endpoint = str(CONFIG.get("fish_tts_api_url") or DEFAULT_FISH_TTS_API_URL)
    model = str(CONFIG.get("fish_tts_model") or DEFAULT_FISH_TTS_MODEL)
    body = json.dumps(_fish_payload(text, rate), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/wav",
            "model": model,
            "User-Agent": "video-recap/1.0",
        },
        method="POST",
    )

    timeout = max(1, int(CONFIG.get("tts_timeout", 300) or 300))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            audio = response.read()
            content_type = str(response.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as exc:
        detail = _sanitize_api_error(
            exc.read().decode("utf-8", errors="replace"),
            extra_secrets=(api_key,),
        )
        if exc.code == 401:
            raise RuntimeError("Fish Audio 认证失败 (401)，请检查 FISH_API_KEY") from exc
        if exc.code == 402:
            raise RuntimeError("Fish Audio 请求被拒绝 (402)，请检查模型额度或计费状态") from exc
        raise RuntimeError(f"Fish Audio TTS 请求失败 (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Fish Audio TTS 网络错误: "
            f"{_sanitize_api_error(exc.reason, extra_secrets=(api_key,))}"
        ) from exc

    if "json" in content_type:
        detail = _sanitize_api_error(
            audio.decode("utf-8", errors="replace"),
            extra_secrets=(api_key,),
        )
        raise RuntimeError(
            f"Fish Audio TTS 返回了 JSON 而不是音频: {detail}"
        )
    if (
        len(audio) <= 44
        or audio[:4] != b"RIFF"
        or audio[8:12] != b"WAVE"
    ):
        raise RuntimeError("Fish Audio TTS 返回的内容不是有效 WAV")

    output = Path(output_path)
    partial = Path(str(output) + ".part")
    try:
        partial.write_bytes(audio)
        os.replace(partial, output)
    finally:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
