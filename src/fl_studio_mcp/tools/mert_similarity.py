"""Reference-track comparison via MERT embeddings (m-a-p/MERT-v1-95M).

Runs in the MCP server process but delegates the actual inference to the
SEPARATE Python interpreter (.venv-audio-ai/) via subprocess — same pattern
as ai_ears.py. torch/transformers stay out of the main MCP server venv.

Answers a different question than fl_evaluate_mix_quality (no-reference
quality score) or fl_detect_masking (frequency conflicts): "how close does
this mix sound, in timbre/production character, to a reference track?" —
useful when the user has a target reference ("make it sound more like X").

Never import torch/transformers directly in this module.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VENV_PYTHON = _REPO_ROOT / ".venv-audio-ai" / "Scripts" / "python.exe"
_INFER_SCRIPT = Path(__file__).resolve().parent / "mert_infer.py"


def compare_to_reference(filepath: str, reference_path: str,
                         timeout_s: float = 120.0) -> dict:
    """Compare a mix to a reference track via MERT embedding cosine similarity.

    Returns a similarity score in [-1, 1] (in practice ~0.3-0.95 for real
    music). Not an absolute quality judgment — a higher score means closer
    timbral/production character to the reference, not "better".

    Cost: ~15-30s per call (model reloads each subprocess invocation, same
    as fl_evaluate_mix_quality). First call also downloads the model
    (~380 MB) from Hugging Face — subsequent calls hit the local cache.
    """
    if not _VENV_PYTHON.exists():
        return {
            "error": f"venv introuvable : {_VENV_PYTHON}. "
                     "Voir INVESTIGATIONS-FUTURES.md (.venv-audio-ai) pour la recréer."
        }
    if not Path(filepath).exists():
        return {"error": f"fichier introuvable : {filepath}"}
    if not Path(reference_path).exists():
        return {"error": f"fichier de référence introuvable : {reference_path}"}

    try:
        proc = subprocess.run(
            [str(_VENV_PYTHON), str(_INFER_SCRIPT), filepath, reference_path],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timeout ({timeout_s}s) — le sous-processus d'inférence n'a pas répondu"}

    if proc.returncode != 0 and not proc.stdout.strip():
        return {"error": f"sous-processus en échec (code {proc.returncode}): {proc.stderr[-2000:]}"}

    # mert_infer.py prints exactly one JSON line, but stray stdout from
    # lazy submodule warnings (e.g. nnAudio) can land before OR after it
    # depending on flush timing — scan all lines, not just the last one.
    result = None
    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            result = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if result is None:
        return {"error": f"sortie inattendue du sous-processus: {proc.stdout[-2000:]} / stderr: {proc.stderr[-1000:]}"}

    if "error" in result:
        return result

    result["file"] = Path(filepath).name
    result["reference"] = Path(reference_path).name
    sim = result["cosine_similarity"]
    if sim > 0.85:
        result["note"] = "Très proche de la référence en timbre/caractère de production."
    elif sim > 0.65:
        result["note"] = "Proche de la référence, écarts perceptibles mais cohérents."
    elif sim > 0.45:
        result["note"] = "Écart notable — caractère de production différent."
    else:
        result["note"] = "Très différent de la référence (genre/texture éloignés, ou silence/bruit dans un des deux fichiers)."
    return result
