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

### Tests à effectuer

- [ ] Découverte paramètres (9 plugins) — mesure du temps total
- [ ] Application preset vocal (batch multi-slot)
- [ ] Enable/disable slot (bouton vert)
- [ ] Suppression d'un plugin de slot
- [ ] Sidechain track 2 → track 6 (Insert 6 — delay chain)

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

### Tests à effectuer

- [ ] `fl_set_sidechain(src=2, dst=6)` — activer route EFFET VOIX → Insert 6
- [ ] Vérification `getRouteSendActive`
- [ ] Réglage level send

---

## Nouvelles fonctionnalités ajoutées (session 2026-06-13)

| Feature | Commit | Status |
|---------|--------|--------|
| `fl_list_available_plugins` | `a437ee8` | ✅ Live |
| Fix `location="mixer"` default | `a437ee8` | ✅ Live |
| `fl_set_slot_enabled` | en cours | 🔧 Bridge déployé, test à faire |
| `fl_remove_plugin` | en cours | 🔧 Bridge déployé, test à faire |
| `fl_set_sidechain` | en cours | 🔧 Bridge déployé, test à faire |

---

## Problèmes connus / Quirks

| Problème | Cause | Solution |
|----------|-------|----------|
| SysEx via `OnMidiIn` (pas `OnSysEx`) | FL Studio 2025 route les SysEx via `OnMidiIn` | Géré dans le bridge |
| Pro-Q 3 readback asynchrone | Le plugin n'applique pas les params instantanément | Délai 150–200 ms avant lecture |
| `setParamValue` silencieux avec `location="channel"` pour mixer | `useGlobal=True` ignore les writes mixer | Toujours utiliser `location="mixer"` |
| Cache `discover_params` écrit avec `location="channel"` | Ancien comportement (pre-fix) | Effacer `schemas/generated/*.json` si incohérence |
