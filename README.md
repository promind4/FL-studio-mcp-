# fl-studio-mcp

Contrôle autonome de FL Studio 2025 par un LLM via le protocole MCP.
Mixage et mastering sans souris — entièrement piloté par le bridge MIDI SysEx.

## Point d'entrée

**→ Lire [`ONBOARDING.md`](ONBOARDING.md) en premier.**

Ce document contient :
- Les règles permanentes (à appliquer sans exception)
- La carte de tous les fichiers de documentation
- Les chemins de lecture selon le scénario (mixage / développement / reprise)
- La procédure de démarrage rapide

## Documents principaux

| Document | Rôle |
|----------|------|
| [`ONBOARDING.md`](ONBOARDING.md) | **Point d'entrée unique** — règles + carte + chemins de lecture |
| [`MIX-WORKFLOW.md`](MIX-WORKFLOW.md) | Trame du mixage autonome (étapes ⓪–⑨, anti-patterns) |
| [`LECONS-APPRISES.md`](LECONS-APPRISES.md) | Pièges documentés session par session |
| [`CONTEXT.md`](CONTEXT.md) | Architecture MIDI SysEx, outils MCP, état du projet |
| [`PARAM-MAPS.md`](PARAM-MAPS.md) | Index des paramètres par plugin (base documentaire, pas des presets) |
| [`INVESTIGATIONS-FUTURES.md`](INVESTIGATIONS-FUTURES.md) | Fonctionnalités à explorer |

## Architecture rapide

```
Claude (LLM)
    │  MCP stdio
    ▼
src/fl_studio_mcp/server.py        ← outils exposés
    │  MIDI SysEx
    ▼
bridge/device_FLStudioMCP.py       ← handler dans FL Studio
    │  API FL Studio Python
    ▼
mixer, plugins, channel rack...
```

Design doc initial : [`docs/superpowers/specs/2026-06-12-fl-studio-mcp-design.md`](docs/superpowers/specs/2026-06-12-fl-studio-mcp-design.md)
