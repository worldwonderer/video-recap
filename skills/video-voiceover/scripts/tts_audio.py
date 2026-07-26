"""Loudness normalization for synthesized TTS blocks.

Split out of voiceover.py to keep that module within the bundle's per-module line
budget. Dependency-free on purpose (stdlib `wave` + `array` only) so QC and assembly
can reuse the returned metadata without pulling in the synthesis path.
"""
import array
import math
import os
import sys
import wave
from pathlib import Path

from lib import CONFIG, log


def _normalize_tts_wav_rms(input_wav, output_wav, *, target_rms_dbfs=-20.0, peak_limit=0.98):
    """Normalize a mono/stereo 16-bit WAV to a target RMS with peak guard.

    This helper is intentionally dependency-free so QC/assembly can reuse the
    returned metadata even when normalization is applied in a later lane.
    """
    input_wav = Path(input_wav)
    output_wav = Path(output_wav)
    with wave.open(str(input_wav), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.getnframes()
        data = wf.readframes(frames)
    if sampwidth != 2:
        raise ValueError(f"仅支持 16-bit PCM WAV: {input_wav}")

    # array('h') decodes the whole block in C. The previous per-sample int.from_bytes
    # comprehension ran three times over the audio (decode, normalize, re-decode the
    # OUTPUT just to measure it) — about 420ms for a 12s block, times every narration
    # segment. Same arithmetic, same rounding, one decode.
    samples = array.array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if sys.byteorder != "little":  # wave data is little-endian regardless of host
        samples.byteswap()
    if not samples:
        output_wav.write_bytes(input_wav.read_bytes())
        return {
            "rms_dbfs_before": None,
            "rms_dbfs_after": None,
            "peak_after": 0.0,
            "gain_db": 0.0,
        }
    count = len(samples)
    rms = math.sqrt(sum(s * s for s in samples) / count)
    peak = max(max(samples), -min(samples)) / 32768.0
    rms_dbfs_before = 20 * math.log10(max(rms, 1e-9) / 32768.0)
    target_linear = 10 ** (float(target_rms_dbfs) / 20.0) * 32768.0
    gain = target_linear / max(rms, 1e-9)
    if peak > 0:
        gain = min(gain, float(peak_limit) / peak)

    # Accumulate the output statistics while normalizing instead of decoding the result back.
    normalized = array.array("h", bytes(2 * count))
    out_square_sum = 0
    out_peak_raw = 0
    for i in range(count):
        value = max(-32768, min(32767, int(round(samples[i] * gain))))
        normalized[i] = value
        out_square_sum += value * value
        if abs(value) > out_peak_raw:
            out_peak_raw = abs(value)
    out_bytes = normalized
    if sys.byteorder != "little":
        out_bytes = array.array("h", normalized)
        out_bytes.byteswap()
    with wave.open(str(output_wav), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        wf.writeframes(out_bytes.tobytes())

    out_rms = math.sqrt(out_square_sum / count)
    return {
        "rms_dbfs_before": rms_dbfs_before,
        "rms_dbfs_after": 20 * math.log10(max(out_rms, 1e-9) / 32768.0),
        "peak_after": out_peak_raw / 32768.0,
        "gain_db": 20 * math.log10(max(gain, 1e-9)),
    }


def _maybe_normalize_tts_wav(output_wav):
    """Normalize a synthesized TTS block in-place when possible.

    Unit tests often stub TTS with text bytes rather than real WAV. In that case
    normalization is skipped safely; real MiMo WAV output gets RMS/peak metadata.
    """
    if not CONFIG.get("tts_segment_normalize", True):
        return None
    output_wav = Path(output_wav)
    tmp = output_wav.with_name(f"{output_wav.stem}_norm{output_wav.suffix}")
    try:
        meta = _normalize_tts_wav_rms(
            output_wav,
            tmp,
            target_rms_dbfs=float(CONFIG.get("tts_segment_target_rms_dbfs", -20.0) or -20.0),
            peak_limit=float(CONFIG.get("tts_segment_peak_limit", 0.98) or 0.98),
        )
        os.replace(tmp, output_wav)
        return meta
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        log(f"  TTS RMS 归一跳过: {exc}")
        return None
