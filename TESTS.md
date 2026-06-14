# FL Studio MCP — Journal de tests

> Mis à jour automatiquement à chaque session de test.  
> Branche : `v0-foundations` | Dernière mise à jour : 2026-06-13

---

## Architecture de transport

| Composant | Valeur |
|-----------|--------|
| Transport | MIDI SysEx via loopMIDI |
| Port FL→serveur | `fLMCP Out` |
| Port serveur→FL | `fLMCP In` |
| Protocole | JSON → base64 → trames F0 7D 46 4C |
| Délai typique | 50–200 ms par appel |

### Config MIDI FL Studio (validée 2026-06-12)

| Port | Entrée/Sortie | Port # | Type de contrôleur | Statut |
|------|--------------|--------|---------------------|--------|
| `fLMCP In` | Entrée | 1 | fLMCP Bridge | ✅ Actif |
| `fLMCP Out` | Entrée | — | — | ❌ Désactivé (évite feedback) |
| `fLMCP Out` | Sortie | 1 | — | ✅ Actif |
| `fLMCP In` | Sortie | **0** | — | ✅ Port 0 obligatoire (pas 1 !) |

**Bug critique résolu** : Si `fLMCP In` en Sortie est sur port 1 (même que `fLMCP Out`), `device.midiOutSysex()` boucle les réponses vers FL lui-même au lieu du serveur.

---

## Tests de connectivité

| Test | Résultat | Date |
|------|----------|------|
| `fl_ping` | ✅ Réponse < 100 ms | 2026-06-12 |
| `fl_list_tracks` | ✅ Master + pistes nommées retournées | 2026-06-12 |
| `fl_get_track_info` | ✅ Plugins FX chain listés par slot | 2026-06-12 |

---

## Tests — Lecture paramètres plugin

### Bug résolu : `location="channel"` vs `"mixer"`

`plugins.setParamValue` avec `useGlobal=True` (`location="channel"`) **ignore silencieusement les écritures** sur les pistes mixer. Les lectures fonctionnent dans les deux modes.

**Fix** : tous les tools MCP plugin params utilisent `location="mixer"` par défaut depuis commit `a437ee8`.

### Pro-Q 3 — Formules de calibration (location="mixer")

```python
# Fréquence (log scale, 10 Hz – 30 000 Hz)
freq_normalized = math.log10(hz / 10.0) / math.log10(3000.0)
# Exemples : 80 Hz → 0.260 | 150 Hz → 0.338 | 1 kHz → 0.575 | 8 kHz → 0.835

# Gain (linéaire, ±30 dB)
gain_normalized = 0.5 + dB / 60.0
# Exemples : -3 dB → 0.45 | 0 dB → 0.50 | +2 dB → 0.533 | +3 dB → 0.55

# Shape
SHAPES = {
    "Bell":      0.00,
    "Low Shelf": 0.10,
    "Low Cut":   0.25,   # High-Pass
    "High Shelf":0.375,
    "High Cut":  0.45,   # Low-Pass
    "Notch":     0.60,
    "Band Pass": 0.75,
    "Tilt Shelf":0.833,
    "Flat Tilt": 1.00,
}

# Q (log scale)
# v=0.55 → Q 0.7 | v=0.60 → Q 1.0 | v=0.70 → Q 2.1 | v=0.80 → Q 4.4

# Bandes : base_index = (band_number - 1) * 13
# Offsets : +0=Used, +1=Enabled, +2=Freq, +3=Gain, +7=Q, +8=Shape
```

**Quirk important** : Pro-Q 3 applique les changements de paramètres de manière asynchrone. Il faut **150–200 ms de délai** entre `setParams` et `getParam` pour obtenir les valeurs réelles.

### C1 comp-sc Mono — Calibration (location="mixer")

```python
# Threshold (linéaire, -100 dB à 0 dB)
threshold_normalized = (dB + 100) / 100.0
# Exemples : -18 dB → 0.82 | -12 dB → 0.88 | -50 dB → 0.50

# Ratio (log scale)
# v=0.218 → 1:1 | v=0.40 → 2.46:1 | v=0.42 → ~2.77:1

# Attack (log scale)
# v=0.40 → 1 ms | v=0.50 → 3 ms | v=0.60 → 10 ms | v=0.80 → 100 ms

# Release (log scale)
# v=0.40 → 40 ms | v=0.50 → 100 ms | v=0.53 → ~132 ms | v=0.60 → 251 ms

# Makeup gain
# v=0.50 → 0 dB | v=0.55 → 4 dB
# Formule approximative : v = 0.50 + dB/80
```

---

## Tests — Écriture paramètres plugin

| Plugin | Track | Slot | Preset | Résultat | Date |
|--------|-------|------|--------|----------|------|
| C1 comp-sc Mono | Insert 1 | 1 | -18 dB / 2.77:1 / 10 ms / 132 ms / +3.2 dB | ✅ Vérifié | 2026-06-13 |
| Pro-Q 3 | Insert 1 | 0 | HP 80Hz / LowShelf +2dB / Bell -3dB@400Hz / HiShelf +2dB@8kHz | ✅ Vérifié | 2026-06-13 |

---

## Tests — Plugin browser

| Test | Résultat | Date |
|------|----------|------|
| `fl_list_available_plugins` | ✅ 243 plugins (182 effets + 61 générateurs) | 2026-06-13 |
| Formats couverts | Fruity (native), VST2, VST3 | — |
| Base de données | `D:\Image-Line\FL Studio\Presets\Plugin database\Installed\` | — |

---

## Tests — Multi-plugin (EFFET VOIX, track 2)

### Plugins présents

| Slot | Plugin | Type |
|------|--------|------|
| 0 | Auto-Tune Pro | VST3 — pitch correction |
| 1 | Pro-Q 3 | VST3 — EQ |
| 2 | Smack Attack Mono | VST3 — transient shaper |
| 3 | TransX Wide Mono | VST3 — transient |
| 4 | Sibilance Mono | VST3 — de-esser |
| 5 | PuigTec EQP1A Mono | VST3 — EQ vintage |
| 6 | RCompressor Mono | VST3 — compresseur |
| 7 | CLA-76 Mono | VST3 — compresseur FET |
| 8 | (vide) | — |
| 9 | ValhallaSpaceModulator | VST3 — reverb |

### Résultats (2026-06-13)

| Test | Résultat | Détail |
|------|----------|--------|
| Comptage params 9 plugins | ✅ 1.07s total | ~0.10s/plugin, tous 4240 params (format Waves) |
| Application preset 7 plugins | ✅ **0.89s** | 14 changements de paramètres batch |
| Enable/disable bouton vert | ✅ | Via `setParamValue(pid=-1)` — stratégie interne FL Studio |
| Suppression plugin de slot | ❌ | API FL Studio 2025 ne l'expose pas (removeTrackPlugin absent) |
| Sidechain track 2 → track 6 | ✅ | `mixer.sidechain` active=True, level=0.8 confirmé |
| Pro-Q 3 EFFET VOIX — activation bandes + EQ | ✅ | HP 80Hz, LowShelf −2dB@200Hz, Bell +2dB@3kHz, HiShelf +2dB@10kHz |
| **Pro-Q 3 — ajout/retrait de bande via `setParamValue`** | ✅ **2026-06-13** | Écrire idx Used (0/13/26/39…) = 1/0 active/désactive la bande. **AUCUN restart requis.** Voir `LECONS-APPRISES.md` |

### Calibrations Waves (patterns communs à tous les plugins Waves)

- Threshold : v=1.0 = 0 dB (maximum, pas de compression). Formule approximative C1 : `v = 1 + dB/100`
- RCompressor Ratio : **échelle inversée** — v=0.4 ≈ 4:1, v=0.514 = 2:1, v=0.0 = 50:1
- Smack Attack : param 0 = Bypass (0=Off=actif), params 2-12 = contrôles réels

### Limitation connue : suppression de plugin

Impossible via API de scripting FL Studio 2025. Seule alternative : automatisation UI (clic droit → Supprimer). Non implémentée pour l'instant.

---

## Tests — Sidechain & Routing

### Track 6 — Insert 6 (delay chain)

| Slot | Plugin |
|------|--------|
| 0 | Pro-R |
| 1 | ValhallaSupermassive |
| 2 | Pro-C 2 |
| 3 | ValhallaSpaceModulator |
| 4 | LALA |
| 5 | C1 comp Stereo |
| 6 | Pro-Q 3 |
| 7 | Fruity Limiter |

### Résultats (2026-06-13)

| Test | Résultat | Détail |
|------|----------|--------|
| `fl_set_sidechain(src=2, dst=6, level=0.8)` | ✅ | active=True, level=0.8 |
| `fl_get_route_info(src=2, dst=6)` | ✅ | Lecture état route confirmée |

---

## Nouvelles fonctionnalités ajoutées (session 2026-06-13)

| Feature | Commit | Status |
|---------|--------|--------|
| `fl_list_available_plugins` | `a437ee8` | ✅ Live |
| Fix `location="mixer"` default | `a437ee8` | ✅ Live |
| `fl_set_slot_enabled` | `c10db48` | ✅ Testé — fonctionne via pid=-1 |
| `fl_remove_plugin` | `c10db48` | ❌ API FL 2025 ne supporte pas la suppression |
| `fl_set_sidechain` | `c10db48` | ✅ Testé — route active confirmée |
| `fl_get_route_info` | `c10db48` | ✅ Testé |
| `fl_get_full_track_info` | `c10db48` | ✅ Testé (enabled=None car isEnabled absent) |

---

## Nouvelles fonctionnalités — session 2026-06-13 (suite)

| Feature | Détail |
|---------|--------|
| `fl_get_preset_count(track, slot)` | Compte les presets FL Studio disponibles pour un plugin |
| `fl_load_preset(track, slot, index)` | Charge un preset par index (0-based) — nécessite `plugins.setPreset` absent en FL 2025 |
| `fl_next_preset(track, slot)` | Cycle au preset suivant — **fonctionne** en FL 2025 via `plugins.nextPreset` |
| `fl_set_plugin_param_rec` | Désactivé — `general.processRECEvent` avec plugin param event IDs crash FL Studio |

### Workflow Pro-Q 3 — ajout/retrait de bandes (MÉTHODE ACTUELLE)

> ⚠️ **Le workflow par presets `.fst` ci-dessous est OBSOLÈTE.** On a découvert le 2026-06-13
> que `setParamValue` contrôle directement les bandes. Détails complets : `LECONS-APPRISES.md`.

1. Pour activer une bande N : `fl_set_plugin_params` avec `{"index": (N-1)*13, "value": 1}`
2. Pour la régler : mêmes batch, offsets +2 (Freq), +3 (Gain), +8 (Shape)
3. Pour la retirer : `{"index": (N-1)*13, "value": 0}`
4. **NE PAS vérifier via `fl_get_plugin_param` juste après** — le readback ment quelques secondes
   (et durablement pour le flag « Used »). Vérifier à l'écran. **Aucun restart FL nécessaire.**

### Approche obsolète (presets `.fst`) — conservée pour mémoire

Avant la découverte ci-dessus, on activait les bandes en chargeant des presets
`ProQ3_1bands.fst` → `ProQ3_8bands.fst` via `fl_next_preset`. Ça marchait mais c'était lourd
(cyclage à l'aveugle) et ça reposait sur le mythe « Band Used non-automatable ». Plus nécessaire.

```
D:\Image-Line\FL Studio\Presets\Plugin presets\Effects\Fruity Wrapper - Pro-Q 3\
```

---

## Problèmes connus / Quirks

| Problème | Cause | Solution |
|----------|-------|----------|
| SysEx via `OnMidiIn` (pas `OnSysEx`) | FL Studio 2025 route les SysEx via `OnMidiIn` | Géré dans le bridge |
| Pro-Q 3 readback asynchrone | Le plugin n'applique pas les params instantanément | Délai 150–200 ms avant lecture |
| `setParamValue` silencieux avec `location="channel"` pour mixer | `useGlobal=True` ignore les writes mixer | Toujours utiliser `location="mixer"` |
| Cache `discover_params` écrit avec `location="channel"` | Ancien comportement (pre-fix) | Effacer `schemas/generated/*.json` si incohérence |
| ~~Pro-Q 3 `Band N Used` non automatable~~ | **FAUX** — c'était un artefact de readback périmé | `setParamValue` contrôle bien les bandes. Voir `LECONS-APPRISES.md` |
| Readback `getParamValue` périmé après une écriture | L'API FL ne resynchronise son snapshot qu'après un délai/événement | Vérifier à l'écran, pas par relecture immédiate. Pour le flag « Used » la lecture ment durablement |
| `plugins.setPreset` absent en FL Studio 2025 | FL 2025 n'implémente pas cette fonction (re-vérifié 2026-06-13) | Utiliser `fl_next_preset`/`prevPreset`, ou mieux `setParamValue` direct |
| `general.processRECEvent` crash FL Studio | Event ID formula incorrecte pour plugin params | **Ne pas utiliser** — handler désactivé dans le bridge |
| ~~Writes Pro-Q 3 visibles seulement après restart~~ | **FAUX** — même cause (readback périmé) | **Aucun restart nécessaire.** Les writes s'appliquent immédiatement |
