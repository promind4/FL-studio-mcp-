"""Frequency-masking detection between simultaneously-playing tracks.

Pure DSP (Librosa STFT), no ML. Answers the question fl_analyze_audio cannot:
not "is the mix bad" but "WHICH two tracks fight in WHICH band, WHEN".

Pairs with the same Split-export workflow as analyze_folder() in
audio_analysis.py — needs per-track WAVs that share the same timeline
(FL writes them at identical start/length, so frame-index alignment holds).
"""
from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np

# Same 6 bands as audio_analysis.py, kept for consistent vocabulary in reports.
_BANDS = {
    "sub_20_80hz":      (20,   80),
    "low_80_250hz":     (80,   250),
    "low_mid_250_1khz": (250,  1000),
    "mid_1_4khz":       (1000, 4000),
    "high_mid_4_8khz":  (4000, 8000),
    "air_8_20khz":      (8000, 20000),
}

# A pair is flagged as "conflicting" in a band when both tracks are
# simultaneously active there for at least this fraction of overlapping
# time, AND their average energy gap is small enough that neither clearly
# dominates (i.e. neither is audibly "in front").
_MIN_OVERLAP_RATIO = 0.15
_MAX_GAP_DB = 6.0
# A track is "active" in a band/frame when within this many dB of its own
# loudest moment in that band (per-track relative floor — absolute dBFS is
# meaningless when comparing a vocal stem to a drum bus).
_RELATIVE_ACTIVE_DB = 30.0


def _track_band_frames(y: np.ndarray, sr: int, n_fft: int = 2048,
                       hop_length: int = 512) -> dict[str, np.ndarray]:
    """Per-band, per-frame energy in dB for one track."""
    nyquist = sr / 2
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    out = {}
    for name, (f_lo, f_hi) in _BANDS.items():
        if f_lo >= nyquist:
            continue  # band entirely above Nyquist at this sr — skip, not "silent"
        mask = (freqs >= f_lo) & (freqs < min(f_hi, nyquist))
        if not mask.any():
            continue
        band_energy = np.sqrt(np.mean(S[mask, :] ** 2, axis=0))
        out[name] = 20 * np.log10(band_energy + 1e-9)
    return out


def detect_masking(filepaths: list[str], sr_target: int = 22050) -> dict:
    """Detect frequency-band conflicts between simultaneously-playing tracks.

    filepaths: WAVs sharing the same timeline (e.g. from a Split-export —
    same start time, same length). Tracks of different lengths are trimmed
    to the shortest one (a longer file just means silence/tail at the end,
    which carries no masking information anyway).

    Returns conflicts sorted by severity (highest overlap, smallest energy
    gap first) — each one says WHICH two tracks compete, in WHICH band,
    for WHAT fraction of the time, and HOW close their levels are (a small
    gap means neither dominates, i.e. real masking risk; a large gap means
    one is already in front and there's no problem to fix).
    """
    paths = [Path(f) for f in filepaths]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        return {"error": f"Files not found: {missing}"}
    if len(paths) < 2:
        return {"error": "Need at least 2 tracks to detect masking between them."}

    names = []
    per_track_bands = []
    min_frames = None

    for p in paths:
        y, sr = librosa.load(str(p), sr=sr_target, mono=True)
        bands = _track_band_frames(y, sr)
        per_track_bands.append(bands)
        names.append(p.stem.rsplit("_", 1)[-1] if "_" in p.stem else p.stem)
        n = min(arr.shape[0] for arr in bands.values()) if bands else 0
        min_frames = n if min_frames is None else min(min_frames, n)

    conflicts = []
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            bands_i, bands_j = per_track_bands[i], per_track_bands[j]
            shared_bands = set(bands_i) & set(bands_j)
            for band in shared_bands:
                a = bands_i[band][:min_frames]
                b = bands_j[band][:min_frames]

                active_a = a > (np.max(a) - _RELATIVE_ACTIVE_DB)
                active_b = b > (np.max(b) - _RELATIVE_ACTIVE_DB)
                both = active_a & active_b
                overlap_ratio = float(np.mean(both))

                if overlap_ratio < _MIN_OVERLAP_RATIO:
                    continue

                gap_db = float(np.mean(np.abs(a[both] - b[both])))
                if gap_db > _MAX_GAP_DB:
                    continue  # one already dominates — not a masking conflict

                louder = names[i] if float(np.mean(a[both])) > float(np.mean(b[both])) else names[j]
                conflicts.append({
                    "tracks": [names[i], names[j]],
                    "band": band,
                    "band_range_hz": list(_BANDS[band]),
                    "overlap_pct": round(overlap_ratio * 100, 1),
                    "energy_gap_db": round(gap_db, 1),
                    "slightly_louder": louder,
                    "severity": round(overlap_ratio * (1.0 / max(gap_db, 0.5)), 2),
                })

    conflicts.sort(key=lambda c: c["severity"], reverse=True)

    notes = []
    if not conflicts:
        notes.append("No significant masking conflicts detected — tracks occupy "
                      "distinct frequency space or one clearly dominates where they overlap.")
    else:
        top = conflicts[0]
        notes.append(
            f"Strongest conflict: {top['tracks'][0]} vs {top['tracks'][1]} in "
            f"{top['band']} ({top['band_range_hz'][0]}-{top['band_range_hz'][1]} Hz) — "
            f"competing {top['overlap_pct']}% of the time, only {top['energy_gap_db']} dB apart "
            f"(neither clearly in front). Consider EQ carve or sidechain between these two."
        )

    return {
        "tracks_analyzed": names,
        "conflicts": conflicts,
        "notes": notes,
    }
