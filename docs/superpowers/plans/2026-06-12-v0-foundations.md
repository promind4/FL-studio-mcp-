# FL Studio MCP — Plan v0 : Fondations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Valider les 4 fondations du projet : bridge TCP fonctionnel sur FL Studio 2025, contrôle de paramètres de plugins (FabFilter/Waves), tentative de chargement de plugin par script, stratégie d'export audio.

**Architecture:** Bridge TCP copié de geezoria (frames JSON length-prefixed, exécution via OnIdle sur le thread principal FL) + serveur MCP FastMCP côté client avec modules `tools/`. Le bridge reste sans dépendance externe (stdlib Python 3.12 uniquement).

**Tech Stack:** Python 3.12, FastMCP, pytest. Référence locale : `D:\Craft\FL studio LLM\reference\FLStudioMCP`.

**Spec:** `docs/superpowers/specs/2026-06-12-fl-studio-mcp-design.md`

---

## Contexte pour l'implémenteur

- Le repo de référence geezoria est cloné dans `D:\Craft\FL studio LLM\reference\FLStudioMCP`. Son bridge (`fl_bridge/device_FLStudioMCP.py`, ~1700 lignes) est éprouvé : on le **copie tel quel** puis on l'étend. Son `protocol.py` aussi.
- L'API Python de FL Studio n'est PAS thread-safe : tout appel API doit s'exécuter dans `OnIdle()` (le bridge gère déjà ça via une queue).
- Limites connues de l'API publique (docs/LIMITATIONS.md de geezoria) : chargement de plugin non exposé, render non scriptable. FL Studio 2025 a pu ajouter des fonctions — toujours garder les appels incertains derrière `hasattr()`.
- Working dir du projet : `D:\Craft\FL studio LLM\fl-studio-mcp`.

---

### Task 1: Scaffolding du projet + copie du bridge

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`
- Create: `bridge/device_FLStudioMCP.py` (copié de la référence)
- Create: `src/fl_studio_mcp/__init__.py`, `src/fl_studio_mcp/protocol.py` (copié)
- Create: `tests/__init__.py`

- [ ] **Step 1: Créer pyproject.toml**

```toml
[project]
name = "fl-studio-mcp"
version = "0.1.0"
description = "AI-driven mixing and mastering for FL Studio via MCP"
requires-python = ">=3.10"
dependencies = [
    "fastmcp>=2.0",
]

[project.optional-dependencies]
audio = ["librosa", "soundfile", "numpy", "scipy", "pyloudnorm"]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/fl_studio_mcp"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Créer .gitignore**

```
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/
.pytest_cache/
schemas/generated/
*.tmp.wav
```

- [ ] **Step 3: Copier le bridge et le protocole depuis la référence**

```powershell
New-Item -ItemType Directory -Force "bridge", "src\fl_studio_mcp", "tests"
Copy-Item "D:\Craft\FL studio LLM\reference\FLStudioMCP\fl_bridge\device_FLStudioMCP.py" "bridge\device_FLStudioMCP.py"
Copy-Item "D:\Craft\FL studio LLM\reference\FLStudioMCP\src\fl_studio_mcp\protocol.py" "src\fl_studio_mcp\protocol.py"
New-Item -ItemType File "src\fl_studio_mcp\__init__.py", "tests\__init__.py"
```

- [ ] **Step 4: Vérifier que les imports passent**

Run: `python -c "import sys; sys.path.insert(0, 'src'); import fl_studio_mcp.protocol as p; print(p.PORT)"`
Expected: `9876`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: scaffold project, vendor geezoria bridge and protocol"
```

---

### Task 2: Tests du protocole de framing

**Files:**
- Test: `tests/test_protocol.py`

- [ ] **Step 1: Écrire les tests**

```python
import socket
import threading

from fl_studio_mcp import protocol


def test_pack_roundtrip_over_socketpair():
    a, b = socket.socketpair()
    try:
        payload = {"id": 1, "action": "ping", "params": {"x": "é"}}
        a.sendall(protocol.pack(payload))
        result = protocol.read_frame(b)
        assert result == payload
    finally:
        a.close()
        b.close()


def test_pack_rejects_oversized_frame():
    import pytest
    big = {"data": "x" * (protocol.MAX_FRAME + 1)}
    with pytest.raises(ValueError):
        protocol.pack(big)


def test_read_frame_raises_on_closed_socket():
    import pytest
    a, b = socket.socketpair()
    a.close()
    with pytest.raises(ConnectionError):
        protocol.read_frame(b)
    b.close()
```

- [ ] **Step 2: Lancer les tests**

Run: `pytest tests/test_protocol.py -v`
Expected: 3 PASS (le protocole est déjà implémenté — ces tests verrouillent le comportement)

Note Windows : si `socket.socketpair()` n'est pas disponible, remplacer par une paire TCP locale (`socket.create_connection` vers un listener éphémère sur 127.0.0.1).

- [ ] **Step 3: Commit**

```bash
git add tests/test_protocol.py
git commit -m "test: lock framing protocol behavior"
```

---

### Task 3: Client TCP (BridgeClient)

**Files:**
- Create: `src/fl_studio_mcp/client.py`
- Test: `tests/test_client.py`

- [ ] **Step 1: Écrire les tests (serveur factice en thread)**

```python
import json
import socket
import threading

import pytest

from fl_studio_mcp import protocol
from fl_studio_mcp.client import BridgeClient, BridgeUnavailable


class FakeBridge:
    """Serveur TCP minimal imitant le bridge FL Studio."""

    def __init__(self, handler):
        self.handler = handler
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
            while True:
                req = protocol.read_frame(conn)
                conn.sendall(protocol.pack(self.handler(req)))
        except (ConnectionError, OSError):
            pass

    def close(self):
        self.sock.close()


def test_call_returns_result():
    bridge = FakeBridge(lambda req: {"id": req["id"], "ok": True,
                                     "result": {"pong": True}, "error": None})
    client = BridgeClient(port=bridge.port)
    assert client.call("ping") == {"pong": True}
    client.close()
    bridge.close()


def test_call_raises_on_bridge_error():
    bridge = FakeBridge(lambda req: {"id": req["id"], "ok": False,
                                     "result": None, "error": "slot 2 is empty"})
    client = BridgeClient(port=bridge.port)
    with pytest.raises(RuntimeError, match="slot 2 is empty"):
        client.call("plugin_get_param", {"track": 1, "slot": 2})
    client.close()
    bridge.close()


def test_unreachable_bridge_raises_bridge_unavailable():
    client = BridgeClient(port=1)  # port 1: jamais ouvert
    with pytest.raises(BridgeUnavailable):
        client.call("ping")
```

- [ ] **Step 2: Lancer — vérifier l'échec**

Run: `pytest tests/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: fl_studio_mcp.client`

- [ ] **Step 3: Implémenter le client**

```python
"""TCP client to the FL Studio bridge. Thread-safe, lazy connect, one retry."""

from __future__ import annotations

import itertools
import socket
import threading
from typing import Any

from . import protocol


class BridgeUnavailable(ConnectionError):
    """FL Studio is not running or the bridge script is not loaded."""


class BridgeClient:
    def __init__(self, host: str = protocol.HOST, port: int = protocol.PORT,
                 timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def _connect(self) -> socket.socket:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise BridgeUnavailable(
                f"Cannot reach FL Studio bridge on {self.host}:{self.port}. "
                "Is FL Studio running with the fLMCP Bridge script loaded?"
            ) from exc
        sock.settimeout(self.timeout)
        return sock

    def call(self, action: str, params: dict | None = None) -> Any:
        with self._lock:
            request = {"id": next(self._ids), "action": action, "params": params or {}}
            for attempt in (1, 2):
                if self._sock is None:
                    self._sock = self._connect()
                try:
                    self._sock.sendall(protocol.pack(request))
                    response = self._read_response(request["id"])
                    break
                except (ConnectionError, OSError):
                    self._drop()
                    if attempt == 2:
                        raise BridgeUnavailable("connection lost and reconnect failed")
            if not response.get("ok"):
                raise RuntimeError(f"{action}: {response.get('error')}")
            return response.get("result")

    def _read_response(self, request_id: int) -> dict:
        while True:
            frame = protocol.read_frame(self._sock)
            if "event" in frame:  # notification push — ignorée en v0
                continue
            if frame.get("id") == request_id:
                return frame

    def _drop(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self):
        with self._lock:
            self._drop()
```

- [ ] **Step 4: Lancer — vérifier le succès**

Run: `pytest tests/test_client.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/fl_studio_mcp/client.py tests/test_client.py
git commit -m "feat: bridge TCP client with reconnect and structured errors"
```

---

### Task 4: Serveur MCP minimal (ping + statut)

**Files:**
- Create: `src/fl_studio_mcp/server.py`
- Create: `src/fl_studio_mcp/__main__.py`
- Test: `tests/test_server_build.py`

- [ ] **Step 1: Écrire le test de construction**

```python
def test_server_builds_and_lists_tools():
    from fl_studio_mcp.server import build_server

    server = build_server()
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert "fl_ping" in tool_names
```

Note : si l'attribut interne `_tool_manager` diffère dans la version de FastMCP installée, utiliser l'API publique équivalente (`server.list_tools()` async) — vérifier avec `python -c "import fastmcp; print(fastmcp.__version__)"`.

- [ ] **Step 2: Lancer — vérifier l'échec**

Run: `pytest tests/test_server_build.py -v`
Expected: FAIL — module server absent

- [ ] **Step 3: Implémenter le serveur**

```python
"""MCP server entry point. Exposes FL Studio control tools to the LLM."""

from __future__ import annotations

from fastmcp import FastMCP

from .client import BridgeClient, BridgeUnavailable

_client: BridgeClient | None = None


def get_client() -> BridgeClient:
    global _client
    if _client is None:
        _client = BridgeClient()
    return _client


def build_server() -> FastMCP:
    mcp = FastMCP("fl-studio-mcp")

    @mcp.tool()
    def fl_ping() -> dict:
        """Check that FL Studio is running and the bridge is reachable."""
        try:
            result = get_client().call("ping")
            return {"connected": True, "bridge": result}
        except BridgeUnavailable as exc:
            return {"connected": False, "error": str(exc)}

    return mcp


def main():
    build_server().run()
```

`__main__.py` :

```python
from .server import main

main()
```

- [ ] **Step 4: Lancer — vérifier le succès**

Run: `pytest tests/test_server_build.py -v`
Expected: PASS

- [ ] **Step 5: Vérifier l'action `ping` côté bridge**

Le bridge geezoria expose-t-il une action `ping` ? Vérifier :
`Select-String -Path bridge\device_FLStudioMCP.py -Pattern '"ping"|def _act'`
Si l'action s'appelle autrement (ex : `bridge_info`, `hello`), adapter le nom dans `fl_ping` pour correspondre à l'action réelle du bridge.

- [ ] **Step 6: Commit**

```bash
git add src/fl_studio_mcp/server.py src/fl_studio_mcp/__main__.py tests/test_server_build.py
git commit -m "feat: minimal MCP server with bridge connectivity check"
```

---

### Task 5: Outils plugins — lecture/écriture de paramètres + découverte avec cache

**Files:**
- Create: `src/fl_studio_mcp/tools/__init__.py`
- Create: `src/fl_studio_mcp/tools/plugins.py`
- Test: `tests/test_plugins_tools.py`

Le bridge geezoria expose déjà les actions plugin (`plugin_params`, `plugin_get_param`, `plugin_set_param`, `plugin_name`, `plugin_is_valid`). Vérifier les noms exacts dans `bridge/device_FLStudioMCP.py` (chercher `plugin_` dans le dispatcher autour de la ligne 1690) et les utiliser tels quels.

- [ ] **Step 1: Écrire les tests (client factice injecté)**

```python
import json

from fl_studio_mcp.tools.plugins import discover_params, set_params


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call(self, action, params=None):
        self.calls.append((action, params))
        return self.responses[action]


def test_discover_params_builds_schema(tmp_path):
    client = FakeClient({
        "plugin_name": "FabFilter Pro-Q 3",
        "plugin_params": [
            {"index": 0, "name": "Band 1 Frequency", "value": 0.5},
            {"index": 1, "name": "Band 1 Gain", "value": 0.5},
        ],
    })
    schema = discover_params(client, track=5, slot=0, cache_dir=tmp_path)
    assert schema["plugin"] == "FabFilter Pro-Q 3"
    assert schema["params"][0]["name"] == "Band 1 Frequency"
    # Le cache est écrit
    cached = json.loads((tmp_path / "FabFilter Pro-Q 3.json").read_text(encoding="utf-8"))
    assert cached == schema


def test_discover_params_uses_cache(tmp_path):
    (tmp_path / "FabFilter Pro-Q 3.json").write_text(
        json.dumps({"plugin": "FabFilter Pro-Q 3", "params": [{"index": 0, "name": "X"}]}),
        encoding="utf-8",
    )
    client = FakeClient({"plugin_name": "FabFilter Pro-Q 3"})
    schema = discover_params(client, track=5, slot=0, cache_dir=tmp_path)
    assert schema["params"][0]["name"] == "X"
    # plugin_params n'a PAS été appelé (cache hit)
    assert all(a != "plugin_params" for a, _ in client.calls)


def test_set_params_batches_changes():
    client = FakeClient({"plugin_set_params": {"applied": 2}})
    result = set_params(client, track=5, slot=0,
                        changes=[{"index": 3, "value": 0.62}, {"index": 4, "value": 0.31}])
    assert result == {"applied": 2}
    action, params = client.calls[0]
    assert action == "plugin_set_params"
    assert len(params["changes"]) == 2
```

- [ ] **Step 2: Lancer — vérifier l'échec**

Run: `pytest tests/test_plugins_tools.py -v`
Expected: FAIL — module absent

- [ ] **Step 3: Implémenter**

```python
"""Plugin parameter tools: discovery with cache, batched writes."""

from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_CACHE = Path(__file__).resolve().parents[3] / "schemas" / "generated"


def _safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def discover_params(client, track: int, slot: int,
                    cache_dir: Path = DEFAULT_CACHE) -> dict:
    """Return the full parameter map of the plugin in (track, slot).

    Uses a per-plugin-name JSON cache: discovery over TCP is slow
    (1000+ params on big plugins), so it runs once per plugin.
    """
    plugin_name = client.call("plugin_name", {"track": track, "slot": slot})
    cache_file = Path(cache_dir) / f"{_safe_filename(plugin_name)}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    params = client.call("plugin_params", {"track": track, "slot": slot})
    schema = {"plugin": plugin_name, "params": params}
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(schema, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    return schema


def set_params(client, track: int, slot: int, changes: list[dict]) -> dict:
    """Apply several parameter changes in one TCP round-trip.

    changes: [{"index": int, "value": float 0..1}, ...]
    """
    return client.call("plugin_set_params",
                       {"track": track, "slot": slot, "changes": changes})


def get_param(client, track: int, slot: int, index: int) -> dict:
    return client.call("plugin_get_param",
                       {"track": track, "slot": slot, "index": index})
```

- [ ] **Step 4: Lancer — vérifier le succès**

Run: `pytest tests/test_plugins_tools.py -v`
Expected: 3 PASS

- [ ] **Step 5: Adapter aux actions réelles du bridge**

Ouvrir `bridge/device_FLStudioMCP.py`, localiser le dispatcher d'actions (~ligne 1690). Confirmer les noms d'actions plugin et le format de retour de `plugin_params`. Si le format diffère (ex : retourne `{"params": [...]}` au lieu d'une liste), adapter `discover_params` et les tests en conséquence. Documenter les noms réels en commentaire de module.

- [ ] **Step 6: Commit**

```bash
git add src/fl_studio_mcp/tools/ tests/test_plugins_tools.py
git commit -m "feat: plugin param discovery with cache and batched writes"
```

---

### Task 6: Action batch côté bridge

**Files:**
- Modify: `bridge/device_FLStudioMCP.py` (dispatcher + nouveau handler)

Le bridge geezoria a `plugin_set_param` (unitaire) mais pas de batch. Un EQ = 15–20 paramètres ; à 15–80 ms par aller-retour, le batch est obligatoire.

- [ ] **Step 1: Ajouter le handler dans le bridge**

Localiser les handlers plugin existants (chercher `def _plugin_set_param` ou équivalent) et ajouter à côté, en suivant le style du fichier :

```python
def _plugin_set_params(p):
    """Batch parameter writes: one TCP round-trip, N setParamValue calls."""
    track = int(p["track"])
    slot = int(p["slot"])
    changes = p.get("changes", [])
    applied = 0
    errors = []
    for change in changes:
        try:
            plugins.setParamValue(
                float(change["value"]), int(change["index"]), track, slot
            )
            applied += 1
        except Exception as exc:
            errors.append({"index": change.get("index"), "error": str(exc)})
    return {"applied": applied, "errors": errors}
```

Puis enregistrer `"plugin_set_params": _plugin_set_params` dans le dispatcher, à côté des autres actions plugin (même mécanisme d'enregistrement que le fichier utilise — table de dispatch ou chaîne if/elif).

Important : vérifier la signature exacte de `plugins.setParamValue` utilisée ailleurs dans CE fichier (ordre des arguments, éventuel paramètre `pickupMode`) et utiliser la même.

- [ ] **Step 2: Vérification syntaxique**

Run: `python -m py_compile bridge\device_FLStudioMCP.py`
Expected: aucune sortie (le fichier importe des modules FL indisponibles hors FL Studio — py_compile vérifie seulement la syntaxe, c'est suffisant ici)

- [ ] **Step 3: Commit**

```bash
git add bridge/device_FLStudioMCP.py
git commit -m "feat(bridge): add plugin_set_params batch action"
```

---

### Task 7: Outils mixer de base

**Files:**
- Create: `src/fl_studio_mcp/tools/mixer.py`
- Test: `tests/test_mixer_tools.py`

Actions bridge existantes (vérifier les noms exacts dans le dispatcher) : volume, pan, mute, solo, routing, EQ natif.

- [ ] **Step 1: Écrire les tests**

```python
from fl_studio_mcp.tools.mixer import set_volume, set_pan, get_track_info


class FakeClient:
    def __init__(self):
        self.calls = []

    def call(self, action, params=None):
        self.calls.append((action, params))
        return {"ok": True}


def test_set_volume_clamps_to_valid_range():
    client = FakeClient()
    set_volume(client, track=3, volume=1.5)  # > 1.0
    _, params = client.calls[0]
    assert params["volume"] == 1.0


def test_set_pan_passes_through():
    client = FakeClient()
    set_pan(client, track=3, pan=-0.5)
    action, params = client.calls[0]
    assert params == {"track": 3, "pan": -0.5}


def test_get_track_info_calls_bridge():
    client = FakeClient()
    get_track_info(client, track=3)
    assert client.calls[0][0] == "mixer_track_info"
```

- [ ] **Step 2: Lancer — vérifier l'échec**

Run: `pytest tests/test_mixer_tools.py -v`
Expected: FAIL — module absent

- [ ] **Step 3: Implémenter**

```python
"""Mixer tools: volume, pan, mute, solo, track info."""

from __future__ import annotations


def set_volume(client, track: int, volume: float) -> dict:
    """volume: 0.0..1.0 (0.8 = 0 dB in FL Studio)."""
    clamped = max(0.0, min(1.0, volume))
    return client.call("mixer_set_volume", {"track": track, "volume": clamped})


def set_pan(client, track: int, pan: float) -> dict:
    """pan: -1.0 (left) .. 1.0 (right)."""
    clamped = max(-1.0, min(1.0, pan))
    return client.call("mixer_set_pan", {"track": track, "pan": clamped})


def set_mute(client, track: int, muted: bool) -> dict:
    return client.call("mixer_set_mute", {"track": track, "muted": bool(muted)})


def get_track_info(client, track: int) -> dict:
    """Name, volume, pan, mute/solo state, loaded plugins of one track."""
    return client.call("mixer_track_info", {"track": track})
```

- [ ] **Step 4: Adapter aux noms d'actions réels du bridge** (même démarche que Task 5 Step 5 — si le bridge expose `mixer_set_track_volume` au lieu de `mixer_set_volume`, suivre le bridge et corriger tests + code)

- [ ] **Step 5: Lancer — vérifier le succès**

Run: `pytest tests/test_mixer_tools.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/fl_studio_mcp/tools/mixer.py tests/test_mixer_tools.py
git commit -m "feat: basic mixer tools (volume, pan, mute, track info)"
```

---

### Task 8: Chargement de plugin — stratégie 1 (ui) + repli assisté

**Files:**
- Modify: `bridge/device_FLStudioMCP.py` (action `plugin_load_attempt`)
- Create: `src/fl_studio_mcp/tools/plugin_loader.py`
- Test: `tests/test_plugin_loader.py`

Contexte : l'API publique (stubs) n'expose pas le chargement de plugin. FL Studio 2025 a PU ajouter des fonctions. Cette task implémente : (a) une action bridge qui sonde les capacités réelles à l'exécution, (b) le repli assisté côté serveur.

- [ ] **Step 1: Action bridge de sondage des capacités**

Ajouter dans le bridge :

```python
def _plugin_load_attempt(p):
    """Probe runtime API for plugin-loading capabilities (FL 2025 may
    expose more than the public stubs). Returns what was found/tried."""
    report = {"strategies": {}}

    # Stratégie A : fonction directe éventuelle sur le module mixer/plugins
    for mod, fn in ((mixer, "loadPlugin"), (plugins, "load"),
                    (channels, "addChannel")):
        report["strategies"][f"{mod.__name__}.{fn}"] = hasattr(mod, fn)

    # Stratégie B : navigation browser via ui (les fonctions existent-elles ?)
    for fn in ("navigateBrowser", "selectBrowserMenuItem", "findBrowserItem",
               "getFocusedNodeCaption", "enterBrowserMenu"):
        report["strategies"][f"ui.{fn}"] = hasattr(ui, fn)

    return report
```

Enregistrer `"plugin_load_attempt"` dans le dispatcher.

- [ ] **Step 2: Vérification syntaxique**

Run: `python -m py_compile bridge\device_FLStudioMCP.py`
Expected: aucune sortie

- [ ] **Step 3: Tests du repli assisté**

```python
from fl_studio_mcp.tools.plugin_loader import wait_for_plugin


class FakeClient:
    def __init__(self, names_sequence):
        self.names = list(names_sequence)

    def call(self, action, params=None):
        assert action == "plugin_name"
        return self.names.pop(0) if self.names else ""


def test_wait_for_plugin_detects_insertion():
    # 1er poll : slot vide, 2e poll : plugin inséré
    client = FakeClient(["", "FabFilter Pro-Q 3"])
    result = wait_for_plugin(client, track=5, slot=0,
                             expected="Pro-Q 3", timeout=2, poll_interval=0.01)
    assert result["loaded"] is True
    assert "Pro-Q 3" in result["plugin"]


def test_wait_for_plugin_times_out():
    client = FakeClient([""] * 1000)
    result = wait_for_plugin(client, track=5, slot=0,
                             expected="Pro-Q 3", timeout=0.05, poll_interval=0.01)
    assert result["loaded"] is False
```

- [ ] **Step 4: Lancer — vérifier l'échec**

Run: `pytest tests/test_plugin_loader.py -v`
Expected: FAIL — module absent

- [ ] **Step 5: Implémenter le repli assisté**

```python
"""Plugin loading: capability probe + assisted-insertion fallback.

The public FL API does not expose plugin loading. Strategy:
1. probe_capabilities() asks the bridge what the runtime API actually has
   (FL 2025 may exceed the public stubs)
2. wait_for_plugin() implements the assisted fallback: the LLM asks the
   user to insert the plugin, then polls until it appears in the slot.
"""

from __future__ import annotations

import time


def probe_capabilities(client) -> dict:
    """One-time runtime probe. Result tells which strategies are viable."""
    return client.call("plugin_load_attempt", {})


def wait_for_plugin(client, track: int, slot: int, expected: str,
                    timeout: float = 60.0, poll_interval: float = 1.0) -> dict:
    """Poll (track, slot) until a plugin whose name contains `expected`
    appears, or timeout. Used after asking the user to insert it manually."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            name = client.call("plugin_name", {"track": track, "slot": slot}) or ""
        except RuntimeError:
            name = ""  # slot vide → le bridge renvoie une erreur : on continue
        if expected.lower() in name.lower():
            return {"loaded": True, "plugin": name}
        time.sleep(poll_interval)
    return {"loaded": False, "plugin": None,
            "hint": f"No plugin matching '{expected}' appeared in "
                    f"track {track} slot {slot} within {timeout}s"}
```

- [ ] **Step 6: Lancer — vérifier le succès**

Run: `pytest tests/test_plugin_loader.py -v`
Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add bridge/device_FLStudioMCP.py src/fl_studio_mcp/tools/plugin_loader.py tests/test_plugin_loader.py
git commit -m "feat: plugin load capability probe and assisted fallback"
```

---

### Task 9: Export audio — sondage + stratégie fichiers source

**Files:**
- Modify: `bridge/device_FLStudioMCP.py` (actions `export_capabilities`, `channel_sample_info`)
- Create: `src/fl_studio_mcp/tools/export.py`
- Test: `tests/test_export_tools.py`

Contexte : `project_render` n'est pas scriptable (limitation geezoria). Stratégies : (a) sonder l'API runtime, (b) lire le chemin des fichiers audio source des channels (suffit pour analyser des pistes enregistrées/importées non encore traitées), (c) repli assisté (l'utilisateur exporte, le serveur lit le fichier).

- [ ] **Step 1: Actions bridge**

```python
def _export_capabilities(p):
    """Probe runtime API for any render/export entry points."""
    report = {}
    for mod, fn in ((transport, "render"), (general, "renderProject"),
                    (mixer, "saveAudio"), (ui, "exportAudio")):
        report[f"{mod.__name__}.{fn}"] = hasattr(mod, fn)
    return report


def _channel_sample_info(p):
    """Best-effort source file path of a sampler/audio channel."""
    idx = int(p["channel"])
    info = {"channel": idx, "name": channels.getChannelName(idx)}
    if hasattr(channels, "getChannelSamplePath"):
        info["sample_path"] = channels.getChannelSamplePath(idx)
    else:
        info["sample_path"] = None
        info["hint"] = "getChannelSamplePath not in this FL build"
    return info
```

Enregistrer `"export_capabilities"` et `"channel_sample_info"` dans le dispatcher.

- [ ] **Step 2: Vérification syntaxique**

Run: `python -m py_compile bridge\device_FLStudioMCP.py`
Expected: aucune sortie

- [ ] **Step 3: Tests côté serveur**

```python
from pathlib import Path

from fl_studio_mcp.tools.export import resolve_track_audio


class FakeClient:
    def __init__(self, sample_path):
        self.sample_path = sample_path

    def call(self, action, params=None):
        assert action == "channel_sample_info"
        return {"channel": params["channel"], "name": "Vocal",
                "sample_path": self.sample_path}


def test_resolve_returns_existing_file(tmp_path):
    wav = tmp_path / "vocal.wav"
    wav.write_bytes(b"RIFF")
    client = FakeClient(str(wav))
    result = resolve_track_audio(client, channel=0)
    assert result["available"] is True
    assert result["path"] == str(wav)


def test_resolve_reports_missing_file():
    client = FakeClient("C:/nonexistent/vocal.wav")
    result = resolve_track_audio(client, channel=0)
    assert result["available"] is False


def test_resolve_handles_no_path():
    client = FakeClient(None)
    result = resolve_track_audio(client, channel=0)
    assert result["available"] is False
    assert "hint" in result
```

- [ ] **Step 4: Lancer — vérifier l'échec**

Run: `pytest tests/test_export_tools.py -v`
Expected: FAIL — module absent

- [ ] **Step 5: Implémenter**

```python
"""Track audio resolution for analysis.

Render is not scriptable in FL's public API. Order of strategies:
1. source file of the channel (works for recorded/imported audio)
2. assisted export: user renders, we read the file (orchestrated by the LLM)
"""

from __future__ import annotations

from pathlib import Path


def probe_export_capabilities(client) -> dict:
    return client.call("export_capabilities", {})


def resolve_track_audio(client, channel: int) -> dict:
    """Find an analyzable audio file for a channel. Returns
    {"available": bool, "path": str|None, "hint": str (when unavailable)}."""
    info = client.call("channel_sample_info", {"channel": channel})
    path = info.get("sample_path")
    if not path:
        return {"available": False, "path": None,
                "hint": "No source file on this channel. Ask the user to "
                        "export the track (right-click mixer track → "
                        "'render to wav') and provide the file path."}
    if not Path(path).exists():
        return {"available": False, "path": path,
                "hint": f"Source file not found on disk: {path}"}
    return {"available": True, "path": path, "name": info.get("name")}
```

- [ ] **Step 6: Lancer — vérifier le succès**

Run: `pytest tests/test_export_tools.py -v`
Expected: 3 PASS

- [ ] **Step 7: Commit**

```bash
git add bridge/device_FLStudioMCP.py src/fl_studio_mcp/tools/export.py tests/test_export_tools.py
git commit -m "feat: track audio resolution with export capability probe"
```

---

### Task 10: Câblage MCP complet + script d'installation + checklist de validation

**Files:**
- Modify: `src/fl_studio_mcp/server.py` (enregistrer tous les outils)
- Create: `scripts/install_windows.ps1`
- Create: `docs/VALIDATION.md`

- [ ] **Step 1: Enregistrer tous les outils dans le serveur**

Étendre `build_server()` dans `server.py` :

```python
def build_server() -> FastMCP:
    mcp = FastMCP("fl-studio-mcp")

    from .tools import export, mixer, plugin_loader, plugins as plugin_tools

    @mcp.tool()
    def fl_ping() -> dict:
        """Check that FL Studio is running and the bridge is reachable."""
        try:
            return {"connected": True, "bridge": get_client().call("ping")}
        except BridgeUnavailable as exc:
            return {"connected": False, "error": str(exc)}

    @mcp.tool()
    def fl_discover_plugin_params(track: int, slot: int) -> dict:
        """Full parameter map of the plugin at (track, slot). Cached per plugin name."""
        return plugin_tools.discover_params(get_client(), track, slot)

    @mcp.tool()
    def fl_set_plugin_params(track: int, slot: int, changes: list[dict]) -> dict:
        """Batch-apply parameter changes. changes: [{"index": int, "value": 0..1}]."""
        return plugin_tools.set_params(get_client(), track, slot, changes)

    @mcp.tool()
    def fl_get_plugin_param(track: int, slot: int, index: int) -> dict:
        """Read one parameter's current value."""
        return plugin_tools.get_param(get_client(), track, slot, index)

    @mcp.tool()
    def fl_set_track_volume(track: int, volume: float) -> dict:
        """Set mixer track volume (0.0-1.0, 0.8 = 0 dB)."""
        return mixer.set_volume(get_client(), track, volume)

    @mcp.tool()
    def fl_set_track_pan(track: int, pan: float) -> dict:
        """Set mixer track pan (-1.0 left .. 1.0 right)."""
        return mixer.set_pan(get_client(), track, pan)

    @mcp.tool()
    def fl_get_track_info(track: int) -> dict:
        """Track name, volume, pan, mute state and loaded plugins."""
        return mixer.get_track_info(get_client(), track)

    @mcp.tool()
    def fl_probe_plugin_loading() -> dict:
        """Check which plugin-loading strategies this FL build supports."""
        return plugin_loader.probe_capabilities(get_client())

    @mcp.tool()
    def fl_wait_for_plugin(track: int, slot: int, expected: str,
                           timeout: float = 60.0) -> dict:
        """After asking the user to insert a plugin, poll until it appears."""
        return plugin_loader.wait_for_plugin(get_client(), track, slot,
                                             expected, timeout)

    @mcp.tool()
    def fl_probe_export() -> dict:
        """Check which audio export strategies this FL build supports."""
        return export.probe_export_capabilities(get_client())

    @mcp.tool()
    def fl_resolve_track_audio(channel: int) -> dict:
        """Find an analyzable audio file for a channel (source file strategy)."""
        return export.resolve_track_audio(get_client(), channel)

    return mcp
```

- [ ] **Step 2: Mettre à jour le test de construction**

Dans `tests/test_server_build.py`, étendre l'assertion :

```python
    assert {"fl_ping", "fl_discover_plugin_params", "fl_set_plugin_params",
            "fl_probe_plugin_loading", "fl_resolve_track_audio"} <= tool_names
```

Run: `pytest tests/ -v`
Expected: tous PASS

- [ ] **Step 3: Script d'installation**

S'inspirer de `D:\Craft\FL studio LLM\reference\FLStudioMCP\scripts\install_windows.ps1` (le lire d'abord). Structure :

```powershell
# install_windows.ps1 — copie le bridge dans le dossier Hardware de FL Studio
$ErrorActionPreference = "Stop"

$flSettings = Join-Path $env:USERPROFILE "Documents\Image-Line\FL Studio\Settings"
$target = Join-Path $flSettings "Hardware\fLMCP Bridge"

if (-not (Test-Path $flSettings)) {
    Write-Error "FL Studio settings folder not found: $flSettings"
}

New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item "$PSScriptRoot\..\bridge\device_FLStudioMCP.py" $target -Force

Write-Host "Bridge installed to: $target"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Restart FL Studio"
Write-Host "2. Options > MIDI Settings > Input: enable 'fLMCP Bridge' (controller type)"
Write-Host "3. Add to Claude Desktop config (claude_desktop_config.json):"
Write-Host '   "fl-studio": {"command": "python", "args": ["-m", "fl_studio_mcp"], "cwd": "<repo path>"}'
```

- [ ] **Step 4: Checklist de validation manuelle**

Créer `docs/VALIDATION.md` :

```markdown
# Validation v0 — checklist manuelle (sur la machine avec FL Studio 2025)

Pré-requis : `scripts/install_windows.ps1` exécuté, FL Studio redémarré,
bridge activé dans MIDI Settings, serveur MCP configuré dans Claude Desktop.

## Ticket 1 — Bridge TCP
- [ ] `fl_ping` → `{"connected": true}`

## Ticket 2 — Paramètres plugins
- [ ] Charger manuellement FabFilter Pro-Q 3 sur la piste mixer 1, slot 1
- [ ] `fl_discover_plugin_params(1, 0)` → liste des paramètres avec noms
- [ ] `fl_set_plugin_params(1, 0, [{"index": <freq band 1>, "value": 0.3}])`
      → le changement est VISIBLE dans l'UI du plugin
- [ ] Répéter avec un plugin Waves
- [ ] Noter : les noms de paramètres Waves sont-ils exploitables ?
      (certains VST n'exposent que "Param 1", "Param 2"...)

## Ticket 3 — Chargement de plugin
- [ ] `fl_probe_plugin_loading()` → noter quelles fonctions existent
- [ ] Si une stratégie directe existe → la tester
- [ ] Sinon : valider le repli assisté avec `fl_wait_for_plugin`

## Ticket 4 — Export audio
- [ ] `fl_probe_export()` → noter quelles fonctions existent
- [ ] Sur un channel contenant un enregistrement audio :
      `fl_resolve_track_audio(0)` → chemin du fichier source
- [ ] Si aucun chemin : valider le flux assisté (export manuel + chemin fourni)

## Résultats → décisions
Consigner les résultats ici. Ils déterminent l'architecture définitive de
`load_plugin` et `export_track` pour le plan v1 (analyse + orchestration).
```

- [ ] **Step 5: Lancer toute la suite**

Run: `pytest tests/ -v`
Expected: tous PASS

- [ ] **Step 6: Commit final**

```bash
git add -A
git commit -m "feat: wire all v0 tools into MCP server, add installer and validation checklist"
git push origin main
```

---

## Self-review (fait à l'écriture du plan)

- **Couverture spec :** les 4 tickets de validation v0 de la section 7 du spec sont couverts (Task 4 = ticket 1, Tasks 5-6 = ticket 2, Task 8 = ticket 3, Task 9 = ticket 4). Les sections analyse/knowledge/orchestration du spec sont hors scope v0 — plans suivants.
- **Placeholders :** aucun — chaque step a son code ou sa commande.
- **Cohérence des types :** `BridgeClient.call(action, params) -> Any` utilisé uniformément ; les outils prennent `client` en premier argument (injection pour les tests).
- **Incertitude documentée :** les noms exacts des actions du bridge geezoria doivent être vérifiés à la Task 5 Step 5 et Task 7 Step 4 — c'est une étape explicite du plan, pas un trou.
