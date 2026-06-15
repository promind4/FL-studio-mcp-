"""Audio analysis with Librosa — LUFS, spectrum, dynamics, transients.

Runs in the MCP server process (full filesystem + PyTorch access, no FL sandbox).
Never import this from the bridge (device_FLStudioMCP.py).
"""
from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np


def analyze_audio(filepath: str, sr_target: int = 22050) -> dict:
    """Analyze a WAV/MP3/FLAC file and return mixing-relevant metrics.

    Returns a flat dict the LLM can act on directly:
    - Levels : peak_dbfs, rms_dbfs, lufs
    - Dynamics : dynamic_range_db (P95–P10 of frame RMS)
    - Frequency bands : sub/low/low-mid/mid/high-mid/air energy in dB
    - Spectral feel : centroid_hz (brightness), rolloff_hz, bandwidth_hz
    - Transients : onset_rate_per_sec
    - LLM hint : mix_notes (plain-text observations)
    """
    path = Path(filepath)
    if not path.exists():
        return {"error": f"File not found: {filepath}"}

    y, sr = librosa.load(str(path), sr=sr_target, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    # --- Levels ---
    peak = float(np.max(np.abs(y)))
    peak_dbfs = float(20 * np.log10(peak + 1e-9))
    rms = float(np.sqrt(np.mean(y ** 2)))
    rms_dbfs = float(20 * np.log10(rms + 1e-9))

    # LUFS (ITU-R BS.1770 via pyloudnorm, fallback to RMS estimate)
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(sr)
        lufs = float(meter.integrated_loudness(np.stack([y, y]).T))
    except Exception:
        lufs = round(rms_dbfs - 3.0, 1)

    # --- Dynamics ---
    frame_rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    frame_db = 20 * np.log10(frame_rms + 1e-9)
    dynamic_range = float(np.percentile(frame_db, 95) - np.percentile(frame_db, 10))

    # --- Frequency bands ---
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)

    def _band_db(f_lo, f_hi):
        mask = (freqs >= f_lo) & (freqs < f_hi)
        if not mask.any():
            return -96.0
        return float(20 * np.log10(np.sqrt(np.mean(S[mask] ** 2)) + 1e-9))

    bands = {
        "sub_20_80hz":       _band_db(20,   80),
        "low_80_250hz":      _band_db(80,   250),
        "low_mid_250_1khz":  _band_db(250,  1000),
        "mid_1_4khz":        _band_db(1000, 4000),
        "high_mid_4_8khz":   _band_db(4000, 8000),
        "air_8_20khz":       _band_db(8000, 20000),
    }

    # --- Spectral feel ---
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    rolloff  = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr, roll_percent=0.85)))
    bandwidth = float(np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr)))

    # --- Transients ---
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="frames")
    onset_rate = round(len(onset_frames) / max(duration, 0.001), 2)

    # --- LLM-readable notes ---
    notes = _mix_notes(peak_dbfs, lufs, dynamic_range, bands, centroid)

    return {
        "file": path.name,
        "duration_sec": round(duration, 2),
        "peak_dbfs": round(peak_dbfs, 1),
        "rms_dbfs": round(rms_dbfs, 1),
        "lufs": round(lufs, 1),
        "dynamic_range_db": round(dynamic_range, 1),
        "spectral_centroid_hz": round(centroid, 0),
        "spectral_rolloff_hz": round(rolloff, 0),
        "spectral_bandwidth_hz": round(bandwidth, 0),
        "onset_rate_per_sec": onset_rate,
        "frequency_bands_db": {k: round(v, 1) for k, v in bands.items()},
        "mix_notes": notes,
    }


def _mix_notes(peak_dbfs, lufs, dynamic_range, bands, centroid_hz) -> list[str]:
    """Generate plain-text observations for the LLM to reason about."""
    notes = []

    if peak_dbfs > -1.0:
        notes.append("CLIPPING RISK: peak above -1 dBFS — add limiting before export.")
    elif peak_dbfs > -3.0:
        notes.append("Hot peak (above -3 dBFS) — headroom is tight.")

    if lufs > -8.0:
        notes.append(f"Very loud ({lufs:.1f} LUFS) — may distort on streaming platforms (target -14 LUFS).")
    elif lufs > -12.0:
        notes.append(f"Loud ({lufs:.1f} LUFS) — acceptable for radio, slightly hot for streaming.")
    elif lufs < -20.0:
        notes.append(f"Quiet ({lufs:.1f} LUFS) — needs gain or more compression.")

    if dynamic_range < 6:
        notes.append(f"Low dynamic range ({dynamic_range:.1f} dB) — heavily compressed or limited.")
    elif dynamic_range > 20:
        notes.append(f"High dynamic range ({dynamic_range:.1f} dB) — may need more compression.")

    sub  = bands["sub_20_80hz"]
    low  = bands["low_80_250hz"]
    lmid = bands["low_mid_250_1khz"]
    mid  = bands["mid_1_4khz"]
    hmid = bands["high_mid_4_8khz"]
    air  = bands["air_8_20khz"]

    if low - mid > 8:
        notes.append(f"Bottom-heavy: low band ({low:.1f} dB) >> mids ({mid:.1f} dB) — consider high-pass or low-mid cut.")
    if lmid - mid > 6:
        notes.append(f"Muddy low-mids ({lmid:.1f} dB) — try cutting 200–500 Hz.")
    if mid > hmid + 10:
        notes.append(f"Lacking air/presence: highs ({hmid:.1f} dB) well below mids — consider high-shelf boost.")
    if hmid > mid + 4:
        notes.append(f"Harsh high-mids ({hmid:.1f} dB) — may sound fatiguing, consider dip at 4–8 kHz.")

    if centroid_hz < 1500:
        notes.append(f"Dark/warm character (centroid {centroid_hz:.0f} Hz).")
    elif centroid_hz > 4000:
        notes.append(f"Bright/airy character (centroid {centroid_hz:.0f} Hz).")

    if not notes:
        notes.append("Levels and spectrum look balanced — no obvious issues.")

    return notes
