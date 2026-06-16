"""No-reference perceptual mix quality evaluation (audiobox-aesthetics).

Runs in the MCP server process but delegates the actual inference to a
SEPARATE Python interpreter (.venv-audio-ai/) via subprocess. torch and the
ML stack are deliberately kept out of the main MCP server venv — see
PLAN-TEST-OREILLES-IA.md / INVESTIGATIONS-FUTURES.md for why.

Never import torch/audiobox_aesthetics directly in this module.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VENV_PYTHON = _REPO_ROOT / ".venv-audio-ai" / "Scripts" / "python.exe"
_INFER_SCRIPT = Path(__file__).resolve().parent / "ai_ears_infer.py"

_AXES_NOTES = {
    "CE": "Content Enjoyment — agrément perçu à l'écoute",
    "CU": "Content Usefulness — utilité/exploitabilité du contenu",
    "PC": "Production Complexity — richesse perçue de la production",
    "PQ": "Production Quality — qualité technique perçue de la production",
}


def evaluate_mix_quality(filepath: str, timeout_s: float = 120.0) -> dict:
    """Evaluate perceptual mix/master quality WITHOUT a reference track.

    Returns 4 scores (roughly 0-10) from facebookresearch/audiobox-aesthetics:
    CE (enjoyment), CU (usefulness), PC (production complexity), PQ (production
    quality). Complements fl_analyze_audio's mathematical metrics with a
    listening-based judgment.

    Cost: ~15-30s per call (model reloads each subprocess invocation — no
    persistent server yet, see INVESTIGATIONS-FUTURES.md for the deferred
    optimization). Intended for asynchronous use after export, not real-time.
    """
    if not _VENV_PYTHON.exists():
        return {
            "error": f"venv introuvable : {_VENV_PYTHON}. "
                     "Voir PLAN-TEST-OREILLES-IA.md Phase 0 pour le recréer "
                     "(python -m venv .venv-audio-ai puis pip install audiobox_aesthetics "
                     "requests \"huggingface_hub==0.27.1\" pip-system-certs soundfile)."
        }
    if not Path(filepath).exists():
        return {"error": f"fichier introuvable : {filepath}"}

    try:
        proc = subprocess.run(
            [str(_VENV_PYTHON), str(_INFER_SCRIPT), filepath],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timeout ({timeout_s}s) — le sous-processus d'inférence n'a pas répondu"}

    if proc.returncode != 0 and not proc.stdout.strip():
        return {"error": f"sous-processus en échec (code {proc.returncode}): {proc.stderr[-2000:]}"}

    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"error": f"sortie inattendue du sous-processus: {proc.stdout[-2000:]} / stderr: {proc.stderr[-1000:]}"}

    if "error" in result:
        return result

    result["axes_legend"] = _AXES_NOTES
    return result
