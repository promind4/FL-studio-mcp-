# FL Studio MCP — Guide d'onboarding pour LLM

> **Tu arrives sur ce projet à froid, sans historique de conversation.**
> Ce document est le **point d'entrée unique**. Lis-le entièrement avant toute action.
> Durée de lecture : ~8 minutes.

---

## Ce que fait ce projet

Contrôle autonome de FL Studio 2025 (Windows) par un LLM via le protocole MCP.
Le LLM reçoit une session avec des presets chargés, analyse l'audio, puis mixe et masterise
de manière autonome — sans souris, sans interface utilisateur.

**Transport :** MIDI SysEx uniquement (pas TCP, pas fichiers — bloqués par le sandbox FL Studio).
**Latence :** ~150 ms par appel MCP — planifier les opérations en parallèle quand c'est possible.
**Contrainte absolue :** zéro computer-use, zéro déplacement d'interface.

---

## Règles permanentes — à appliquer sans exception

Ces règles s'appliquent **quel que soit le projet, la session ou le contexte**.
Elles ont été établies après des erreurs répétées et documentées dans `LECONS-APPRISES.md`.
Ne pas les contourner, même si une situation semble justifier une exception.

### R1 — Channel Rack avant les faders mixer

Pour ajuster le niveau d'un élément individuel :
1. `fl_set_channel_volume` (Channel Rack, pré-effets) **EN PREMIER**
2. `fl_set_track_volume` (fader mixer) uniquement pour : balance entre pistes, correction Master, niveaux de bus

**Interdit :** baisser le fader de T4 parce que l'AD LIB est trop fort → utiliser Channel Rack.
**Interdit :** monter le fader de T2 pour compenser une voix faible → utiliser Channel Rack.
**Autorisé :** baisser le Master de -4 dB pour éviter le clipping → fader mixer OK (correction bus).

### R2 — Couverture exhaustive sur un mixage complet

Sur un mixage complet : chaque plugin de chaque piste doit être inspecté et décidé.
Zéro plugin ignoré. Décision explicite pour chacun : configurer / laisser / désactiver / reporter.
Si une calibration manque, noter explicitement « non modifié — calibration manquante ».

### R3 — PARAM-MAPS.md est documentaire, pas un preset

Ne jamais réappliquer une valeur de `PARAM-MAPS.md` sans analyser la situation audio réelle.
`PARAM-MAPS.md` = index des contrôles + pièges documentés. Pas des valeurs à copier.

### R4 — Ctrl+S après chaque session de changements

Les modifications via MCP ne sont pas sauvegardées automatiquement dans FL Studio.
Toujours rappeler à l'utilisateur de faire **Ctrl+S** avant de fermer.

### R5 — Le readback ment juste après une écriture

`getParamValue` retourne l'ancienne valeur pendant ~3–15 s après un `setParamValue`.
Ne jamais conclure "l'écriture a échoué" sur un readback immédiat. Vérifier à l'écran.

---

## Carte documentaire

### Graphe de navigation

```
ONBOARDING.md  ←  point d'entrée unique (tu es ici)
│
├─── RÈGLES & MÉTHODOLOGIE
│    │
│    ├── MIX-WORKFLOW.md
│    │    Trame complète du mixage (étapes ⓪–⑨), anti-patterns, formules.
│    │    Règle P1 (Channel Rack) et P2 (couverture exhaustive) y sont détaillées.
│    │    → Lire AVANT de commencer un mixage.
│    │
│    └── LECONS-APPRISES.md
│         Règles permanentes + pièges identifiés session par session.
│         Contient tous les bugs rencontrés sur le bridge, les plugins, les formules.
│         → Lire APRÈS MIX-WORKFLOW.md, AVANT d'écrire sur les plugins.
│
├─── RÉFÉRENCE TECHNIQUE
│    │
│    ├── CONTEXT.md
│    │    Architecture MIDI SysEx, liste complète des outils MCP disponibles,
│    │    configuration, état actuel du projet, machine hôte.
│    │    → Lire pour trouver un outil, comprendre l'architecture, voir l'état du projet.
│    │
│    └── PARAM-MAPS.md
│         Index des paramètres normalisés par plugin (index → signification → pièges).
│         ⚠️ Base documentaire UNIQUEMENT — ne pas copier les valeurs sans analyse.
│         → Consulter plugin par plugin, pendant le mixage.
│
└─── ÉVOLUTION
     │
     └── INVESTIGATIONS-FUTURES.md
          Fonctionnalités identifiées mais non implémentées.
          → Consulter en fin de session ou pour planifier la prochaine.
```

### Table de référence rapide

| Document | Rôle | Quand consulter |
|----------|------|----------------|
| **`ONBOARDING.md`** (ce fichier) | Point d'entrée — règles + carte | En premier, toujours |
| **`MIX-WORKFLOW.md`** | Trame mixage + anti-patterns | Avant de mixer |
| **`LECONS-APPRISES.md`** | Pièges + bugs + règles P1/P2 | Après MIX-WORKFLOW, avant d'écrire |
| **`CONTEXT.md`** | Architecture + outils MCP + état | Pour trouver un outil ou comprendre l'archi |
| **`PARAM-MAPS.md`** | Index contrôles par plugin | Plugin par plugin pendant le mixage |
| **`INVESTIGATIONS-FUTURES.md`** | Roadmap | Fin de session / planification |

---

## Chemins de lecture selon le scénario

### Scénario A — Mixer une session complète

```
① ONBOARDING.md              (ce fichier — 8 min)
② MIX-WORKFLOW.md            (trame + règles — 3 min, section ⓪ critique)
③ LECONS-APPRISES.md         (section "Règles permanentes" + pièges récents — 2 min)
④ CONTEXT.md §5              (outils disponibles)
④ CONTEXT.md §7              (état actuel du projet, sessions récentes)
⑤ PARAM-MAPS.md              (consulter plugin par plugin pendant le mixage)
```

### Scénario B — Reprendre le projet après une interruption

```
① ONBOARDING.md              (ce fichier)
② CONTEXT.md §7              (état actuel) + §8 (prochaines étapes)
③ MIX-WORKFLOW.md §14        (journal des sessions)
④ INVESTIGATIONS-FUTURES.md  (ce qui reste à faire)
```

### Scénario C — Modifier le bridge ou le serveur MCP

```
① ONBOARDING.md              (ce fichier)
② CONTEXT.md §2              (architecture MIDI SysEx)
② CONTEXT.md §6              (gotchas critiques bridge)
③ LECONS-APPRISES.md         (bugs bridge et MIDI documentés)
```

---

## Procédure de démarrage rapide — mixage

```python
# ÉTAPE 1 — Vérifier la connexion (toujours en premier)
fl_ping()

# ÉTAPE 2 — Audit complet (OBLIGATOIRE avant tout changement)
# Lancer en parallèle sur toutes les pistes
fl_audit_track(0)   # Master
fl_audit_track(1)   # T1
fl_audit_track(2)   # T2
fl_audit_track(3)   # T3
# ...

# ÉTAPE 3 — Pour chaque plugin trouvé
#   a. Identifier dans PARAM-MAPS.md (structure et index des contrôles)
#   b. Lire ses paramètres actuels (threshold, ratio, gain, mix...)
#   c. Analyser la situation audio réelle de la piste
#   d. Décider (configurer / laisser / désactiver / reporter avec justification)
#   e. Appliquer via fl_set_plugin_params(track, slot, [{"index": N, "value": v}])

# ÉTAPE 4 — Niveaux : Channel Rack EN PREMIER
fl_get_channel_rack_info()              # lister tous les canaux
# fl_set_channel_volume(index, norm)    # ajuster les niveaux bruts pré-effets

# ÉTAPE 5 — Analyse audio (après export WAV split depuis FL Studio)
fl_analyze_mix_folder("D:\\chemin\\vers\\wavs\\")
# ou par fichier : fl_analyze_audio("D:\\chemin\\fichier.wav")
# sr_target=11025 par défaut (full-file en ~3-8s) — couvre jusqu'à 5.5 kHz

# ÉTAPE 6 — Rappel Ctrl+S à l'utilisateur avant de terminer
```

---

## Pièges les plus fréquents — mémo

| Piège | Vérification | Valeur problématique |
|-------|-------------|---------------------|
| Compresseur neutralisé | Lire **threshold ET ratio** | threshold=1.0 = off / ratio=1:1 = off |
| De-esser neutralisé | Lire **threshold ET Range** | idx 4=1.0 OU idx 5=1.0 → aucune action |
| LALA neutralisé | Lire Peak Reduction (idx 2) | 0.0 = aucune compression (logique inverse) |
| Changements perdus | Ctrl+S dans FL Studio | Aucune sauvegarde auto via MCP |
| Readback faux | Attendre 3-15s ou vérifier écran | Valeur ancienne retournée juste après écriture |
| Fader mixer déplacé pour niveau individuel | Utiliser Channel Rack | Fader mixer = mixage et bus seulement |
| Analyse limitée aux 30s | `analyze_seconds=None` pour full-file | Piste qui commence à 1:16 invisible sur 30s |
| Pickup mode Channel Rack | Monter d'abord à 0.85, puis descendre | Premier appel en baisse peut être ignoré |
| Plugin "actif" qui ne fait rien | Lire tous les params clés | Chargé ≠ actif |

---

## Fichiers techniques (hors documentation)

| Fichier | Rôle |
|---------|------|
| `src/fl_studio_mcp/server.py` | Serveur MCP — outils exposés au LLM |
| `src/fl_studio_mcp/client.py` | Client MIDI — encode/décode SysEx |
| `bridge/device_FLStudioMCP.py` | Bridge FL Studio — copier vers `D:\Image-Line\FL Studio\Settings\Hardware\fLMCP Bridge\` puis F5 |
| `src/fl_studio_mcp/tools/audio_analysis.py` | Analyse Librosa (sr=11025 par défaut, full-file) |
| `TESTS.md` | Suite de tests — consulter lors de modifications du bridge |

---

## Contraintes non-négociables

| Contrainte | Raison |
|---|---|
| Zéro computer-use, zéro mouvement UI | Décision explicite du projet — tout passe par le bridge MCP |
| Pas de TCP/socket dans le bridge | Sandbox FL Studio bloque tous les I/O Python (voir CONTEXT.md §2) |
| Channel Rack avant faders mixer | Structure de gain lisible, marge préservée (règle R1) |
| Audit complet avant tout changement | Un plugin chargé ≠ un plugin actif (règle R2) |
| PARAM-MAPS.md = référence, pas preset | Les valeurs sont contextuelles, pas universelles (règle R3) |
| Ctrl+S après chaque session | FL Studio ne sauvegarde pas automatiquement les changements MCP (règle R4) |
