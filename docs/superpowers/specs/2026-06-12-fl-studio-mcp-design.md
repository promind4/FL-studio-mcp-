# FL Studio MCP — Design Document

**Date :** 2026-06-12
**Statut :** Validé par l'utilisateur (brainstorming complet)
**Repo :** https://github.com/promind4/FL-studio-mcp-.git

---

## 1. Objectif

Faire prendre en charge par un LLM (via MCP) la totalité du mixage et du mastering d'une session FL Studio 2025, avec un niveau de qualité professionnel. Le LLM analyse l'audio réel de chaque piste, choisit et charge lui-même les plugins adaptés, les configure, vérifie le résultat et itère.

**Critère de qualité central :** les décisions sont basées sur l'analyse mesurée de l'audio, jamais sur des presets génériques. Une voix grave et une voix aiguë doivent recevoir des traitements différents et justifiés.

## 2. Modes d'utilisation (les 3 sont requis)

| Mode | Déclencheur | Comportement |
|---|---|---|
| **Piste unique** | "Traite la piste voix" | Analyse + traitement complet d'une piste |
| **Session complète** | "Fais sonner cette session" | Toutes les pistes + équilibrage + mastering |
| **Suggestion** | "Qu'est-ce que tu ferais ?" | Analyse + rapport détaillé, aucune modification |

L'utilisateur peut passer du mode suggestion au mode application ("vas-y, applique").

## 3. Architecture

Base technique : bridge TCP de geezoria/FLStudioMCP (port 9876, FL Studio 2025 + Python 3.12 natif). Tout le reste est reconstruit proprement.

```
fl-studio-mcp/
├── bridge/
│   └── device_FLStudioMCP.py      # Script controller FL Studio — serveur TCP minimal,
│                                   # ZÉRO dépendance externe (pas de pip dans FL Studio)
├── src/fl_studio_mcp/
│   ├── server.py                  # Point d'entrée MCP (stdio → Claude Desktop)
│   ├── client.py                  # Client TCP vers FL Studio (timeout 10s, reconnexion)
│   ├── tools/                     # Actions atomiques exposées au LLM
│   │   ├── mixer.py               # Volume, pan, mute/solo, sends, routing
│   │   ├── plugins.py             # get/set params, batch, discover, load_plugin
│   │   ├── transport.py           # Play, stop, tempo
│   │   └── export.py              # Bounce piste → WAV temporaire
│   ├── analysis/
│   │   ├── audio.py               # RMS, LUFS, balance fréquentielle (6 bandes),
│   │   │                          # dynamique, sibilance, bruit, transitoires, stéréo
│   │   └── session.py             # État session : pistes, plugins chargés, routing
│   ├── schemas/
│   │   ├── generated/             # JSON auto-découverts (cache par plugin)
│   │   └── curated/               # Surcouche manuelle : ranges réels, unités, sémantique
│   │                              # Priorité : FabFilter (Pro-Q 3, Pro-C 2, Pro-L 2),
│   │                              # Waves courants, natifs FL
│   ├── knowledge/
│   │   ├── mixing_recipes.md      # Chaînes types par profil (voix grave, basse, kick...)
│   │   ├── frequency_conflicts.md # Résolution de masquage entre pistes
│   │   ├── mastering_targets.md   # Cibles LUFS par plateforme
│   │   └── decision_rules.md      # Règles conditionnelles (si sibilance > X → de-esser)
│   ├── state/
│   │   └── snapshots.py           # Sauvegarde/rollback des paramètres avant modification
│   └── orchestration/
│       ├── single_track.py        # Mode 1
│       ├── full_session.py        # Mode 2
│       ├── suggest.py             # Mode 3
│       └── verify.py              # Boucle A/B : ré-export → ré-analyse → comparaison
├── docs/superpowers/specs/
├── tests/
└── pyproject.toml
```

**Principes :**
- `tools/` = atomique, sans logique musicale. `orchestration/` = logique musicale, appelle les tools.
- Le bridge FL Studio reste minimal ; toute l'intelligence est côté serveur MCP.
- Le LLM ne configure jamais un plugin sans avoir lu l'analyse audio.

## 4. Data flow

### Mode 1 — Piste unique
1. `get_session_state()` → pistes, plugins chargés
2. `export_track_audio(track)` → WAV temporaire
3. `analyze_track(wav)` → profil mesuré
4. Consultation `knowledge/` → recette adaptée au profil
5. `snapshot_state(track)` → sauvegarde avant modification
6. Sélection/chargement plugins + configuration (batch TCP)
7. Vérification : ré-export → ré-analyse → comparaison avant/après
8. Itération si critères non atteints (max 3 passes) → rapport

### Mode 2 — Session complète
1. État session complet (pistes + routing)
2. Analyse de toutes les pistes (profils individuels)
3. Analyse croisée : conflits fréquentiels entre pistes
4. Plan de mixage : fondations (kick/basse) → voix → reste → bus → master
5. Traitement piste par piste avec contexte global
6. Équilibrage : volumes relatifs, panning, sends
7. Mastering : analyse master bus → limiteur/maximiseur → cible LUFS (-14 par défaut)
8. Vérification globale + rapport

### Mode 3 — Suggestion
Étapes 1–4 du mode 1, puis rapport détaillé sans modification. Bascule possible vers le mode 1 avec les réglages déjà calculés.

### Gestion d'erreur
- Bridge déconnecté → message explicite ("FL Studio non lancé ou script non chargé")
- Export audio impossible → mode 3 disponible en dégradé (état session uniquement, signalé)
- Toute modification est précédée d'un snapshot → `undo_last_operation()` disponible

## 5. Chargement de plugins (capacité critique)

Le LLM doit pouvoir insérer lui-même un plugin sur une piste — choisi dans l'inventaire complet de l'utilisateur (FabFilter, Waves, natifs FL).

**Inventaire :** au premier lancement, scan de la base de plugins FL Studio → `plugin_inventory.json` catégorisé (EQ, compresseur, reverb...). C'est ce qui permet au LLM de choisir l'égaliseur le plus adapté au contexte parmi ceux disponibles.

**Stratégies d'implémentation `load_plugin(track, slot, name)`, par ordre :**
1. Navigation du browser via le module `ui` de l'API (recherche → insertion)
2. Bibliothèque de presets .fst pré-générés (un par plugin, vierge) chargés dans le slot
3. Repli assisté : demande à l'utilisateur, détecte l'insertion, reprend la main

## 6. Protocole TCP

JSON par ligne, `id` corrélé requête/réponse, timeout 10s :

```json
→ {"id": 42, "type": "set_param_batch", "params": {"track": 5, "slot": 2,
     "changes": [{"index": 3, "value": 0.62}]}}
← {"id": 42, "status": "ok", "result": {}}
← {"id": 43, "status": "error", "message": "slot 2 is empty"}
```

Commandes : `get_state`, `get_param`, `get_param_count`, `get_param_name`, `set_param`, `set_param_batch`, `load_plugin`, `snapshot`, `restore`, `export_track`, `transport_*`.

Le batching est obligatoire pour les performances (un EQ = 15–20 paramètres en un seul aller-retour).

## 7. Tickets de validation v0 — AVANT tout code d'orchestration

Ces 4 points valident ou invalident les fondations :

1. **Bridge TCP** fonctionne sur le FL Studio 2025 de l'utilisateur
2. **`setParamValue`** opère réellement sur FabFilter Pro-Q 3 ET un plugin Waves
3. **Chargement de plugin par script** (stratégies 1 → 2 → 3 de la section 5)
4. **Export audio d'une piste** (API non documentée pour le bounce — risque identifié ;
   replis : solo + enregistrement master, lecture des fichiers source du projet)

## 8. Dépendances

```toml
[project]
dependencies = [
    "mcp", "fastmcp",
    "librosa", "soundfile", "numpy", "scipy",
    "pyloudnorm",        # LUFS
]
```

Le bridge (`device_FLStudioMCP.py`) n'a aucune dépendance — stdlib Python 3.12 uniquement.

## 9. Hors scope v1

- UI dans FL Studio (phase avancée — Claude Desktop suffit pour v1)
- Architecture multi-processus pour l'analyse (v2 si les performances l'exigent)
- Composition musicale / piano roll (le projet cible le mixage/mastering)

## 10. Références

- `D:\Craft\FL studio LLM\fl-studio-mcp-reference.md` — analyse comparative des repos existants
- `D:\Craft\FL studio LLM\reference\FLStudioMCP` — clone de geezoria (bridge TCP à récupérer)
- API FL Studio : modules `plugins`, `mixer`, `channels`, `ui`, `transport`
