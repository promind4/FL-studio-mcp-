"""Standalone inference script — runs ONLY inside .venv-audio-ai, never the main MCP venv.

Invoked as a subprocess by mert_similarity.py. Computes MERT (m-a-p/MERT-v1-95M)
embeddings for two WAVs and prints their cosine similarity as a single JSON line.

Loads WAVs with soundfile (same torchcodec/FFmpeg bypass as ai_ears_infer.py),
resamples to MERT's required 24kHz with torchaudio.functional.resample (a pure
tensor op — does NOT go through torchaudio.load, so no torchcodec dependency).

Mean-pools over time AND over a band of mid-depth transformer layers (not just
the last one — MERT's middle layers are the ones validated for music-similarity
tasks in the paper; the very last layer drifts toward the pretraining objective).
"""
import json
import sys

import numpy as np
import soundfile as sf
import torch
import torchaudio
from transformers import AutoModel, Wav2Vec2FeatureExtractor

_MODEL_ID = "m-a-p/MERT-v1-95M"
_TARGET_SR = 24000
# Layers ~6-9 of 13 are the commonly-cited sweet spot for timbre/music
# similarity in the MERT paper — avoids the bottom (too acoustic) and the
# very top (too close to the masked-prediction pretraining objective).
_LAYER_RANGE = (6, 9)


def _load_embedding(path: str, model, processor) -> np.ndarray:
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    wav = torch.from_numpy(data.T).mean(dim=0)  # mono mixdown: [frames]
    if sr != _TARGET_SR:
        wav = torchaudio.functional.resample(wav, sr, _TARGET_SR)

    inputs = processor(wav.numpy(), sampling_rate=_TARGET_SR, return_tensors="pt")
    with torch.no_grad():
        out = model(**inputs, output_hidden_states=True)

    lo, hi = _LAYER_RANGE
    layers = torch.stack(out.hidden_states[lo:hi + 1])  # [n_layers, 1, frames, 768]
    pooled = layers.mean(dim=(0, 1, 2))  # mean over layers, batch, time -> [768]
    return pooled.numpy()


def main() -> None:
    if len(sys.argv) != 3:
        print(json.dumps({"error": "usage: mert_infer.py <wav_a> <wav_b>"}))
        sys.exit(1)

    path_a, path_b = sys.argv[1], sys.argv[2]
    try:
        processor = Wav2Vec2FeatureExtractor.from_pretrained(_MODEL_ID, trust_remote_code=True)
        model = AutoModel.from_pretrained(_MODEL_ID, trust_remote_code=True)
        model.eval()

        emb_a = _load_embedding(path_a, model, processor)
        emb_b = _load_embedding(path_b, model, processor)

        cos_sim = float(
            np.dot(emb_a, emb_b) / (np.linalg.norm(emb_a) * np.linalg.norm(emb_b) + 1e-9)
        )
        print(json.dumps({"cosine_similarity": round(cos_sim, 4)}))
    except Exception as exc:  # noqa: BLE001 — surfaced as JSON for the parent process
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
