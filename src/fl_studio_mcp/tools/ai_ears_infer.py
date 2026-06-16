"""Standalone inference script — runs ONLY inside .venv-audio-ai, never the main MCP venv.

Invoked as a subprocess by ai_ears.py. Loads the WAV via soundfile (bypasses
torchaudio.load, which on this machine requires torchcodec -> system FFmpeg,
not installed). Prints a single JSON line to stdout: {"CE":.., "CU":.., "PC":.., "PQ":..}
or {"error": "..."} on failure.
"""
import json
import sys

import soundfile as sf
import torch
from audiobox_aesthetics.infer import initialize_predictor


def main() -> None:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: ai_ears_infer.py <wav_path>"}))
        sys.exit(1)

    path = sys.argv[1]
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        wav = torch.from_numpy(data.T)  # [channels, frames]
        predictor = initialize_predictor(ckpt=None)
        result = predictor.forward([{"path": wav, "sample_rate": sr}])
        print(json.dumps(result[0]))
    except Exception as exc:  # noqa: BLE001 — surfaced as JSON for the parent process
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
