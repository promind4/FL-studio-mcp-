# FL Studio MCP — Contexte technique et état du projet

> **Point d'entrée :** Si tu arrives ici directement, lis d'abord [`ONBOARDING.md`](ONBOARDING.md) — il contient les règles permanentes, la carte des documents et les chemins de lecture par scénario.
> **Rôle de ce document :** Architecture MIDI SysEx, liste complète des outils MCP disponibles, configuration système, état actuel du projet et prochaines étapes.
> **Lire avant :** [`ONBOARDING.md`](ONBOARDING.md)
> **Lire après :** [`LECONS-APPRISES.md`](LECONS-APPRISES.md) (si tu codes le bridge) · [`PARAM-MAPS.md`](PARAM-MAPS.md) (si tu mixe)

---

## 1. Ce que fait ce projet

Contrôle complet de FL Studio 2025 (Windows) par un LLM via le protocole MCP.
Objectif final : recevoir une session avec des presets chargés → analyser l'audio → mixer et masteriser de manière autonome.

---

## 2. Architecture — comment ça fonctionne

```
Claude Desktop
    │  MCP (stdio)
    ▼
src/fl_studio_mcp/server.py      ← MCP server (outils exposés au LLM)
    │  client.py : encode en SysEx MIDI
    ▼
FL Studio Python bridge (MIDI In)
    │  device_FLStudioMCP.py      ← handler MIDI dans FL Studio
    ▼
FL Studio API (channels, mixer, plugins, ui…)
    │  réponse encodée en SysEx MIDI
    ▼
server.py reçoit la réponse → renvoie au LLM
```

### Transport : MIDI SysEx UNIQUEMENT

FL Studio 2025 Windows tourne dans un sous-interpréteur Python qui bloque :
- `socket.socket()` → NULL
- `_io.FileIO` (open write) → NULL
- `start_new_thread` → NULL
- `ctypes` → ImportError

**Seul canal vivant : `device.midiOutSysex()`** (API FL Studio, pas de l'I/O Python).

Latence : ~150 ms par appel. Ne jamais tenter de re-brancher TCP, fichiers, ou ctypes —
même en admin. Prouvé et documenté dans `LECONS-APPRISES.md`.

---

## 3. Fichiers clés

| Fichier | Rôle |
|---------|------|
| `bridge/device_FLStudioMCP.py` | Bridge FL Studio — handlers MIDI SysEx |
| `src/fl_studio_mcp/server.py` | MCP server — outils exposés au LLM |
| `src/fl_studio_mcp/client.py` | Client MIDI — encode/décode les messages |
| `src/fl_studio_mcp/protocol.py` | Protocole SysEx (framing, sérialisation JSON) |
| `LECONS-APPRISES.md` | Journal de bugs critiques — **lire avant de coder** |
| `INVESTIGATIONS-FUTURES.md` | Pistes à explorer après stabilisation |
| `docs/superpowers/specs/2026-06-12-fl-studio-mcp-design.md` | Design doc initial |

### Déploiement bridge

Le bridge doit être copié à deux endroits :
- Développement : `bridge/device_FLStudioMCP.py`
- FL Studio actif : `D:\Image-Line\FL Studio\Settings\Hardware\fLMCP Bridge\device_FLStudioMCP.py`

Après chaque modification du bridge, copier vers FL Studio et recharger (F5 dans le Script Editor de FL Studio).

---

## 4. Configuration MCP (claude_desktop_config.json)

```json
{
  "mcpServers": {
    "fl-studio": {
      "command": "C:\\Python313\\python.exe",
      "args": ["-m", "fl_studio_mcp"],
      "cwd": "D:\\Craft\\FL studio LLM\\fl-studio-mcp"
    }
  }
}
```

---

## 5. Outils MCP disponibles

### Connexion & diagnostic
| Outil | Description |
|-------|-------------|
| `fl_ping` | Vérifie que FL Studio est connecté |
| `fl_get_project_info` | Snapshot projet : BPM, version, nombre de pistes/canaux |
| `fl_probe_sandbox` | Vérifie les capacités du sandbox Python (socket/thread/file) |
| `fl_probe_all_modules` | Liste tous les modules Python disponibles dans FL |
| `fl_get_undo_history` | Historique des actions annulables |
| `fl_undo` / `fl_redo` | Annuler / refaire |
| `fl_tool_guide` | Guide des outils disponibles (auto-documentation) |

### Projet & transport
| Outil | Description |
|-------|-------------|
| `fl_set_bpm(bpm)` | Change le tempo (10–999 BPM) |
| `fl_set_time_signature(num, den)` | Change la signature rythmique ⚠️ API FL non disponible — échoue silencieusement |

### Mixer — lecture
| Outil | Description |
|-------|-------------|
| `fl_list_tracks` | Liste toutes les pistes mixer (nommées ou toutes) |
| `fl_get_track_info(track)` | Nom, volume, pan, mute/solo, plugins d'une piste |
| `fl_get_full_track_info(track)` | Idem + état de chaque slot FX + peaks |
| `fl_get_slot_info(track, slot)` | Nom + état enabled d'un slot précis |
| `fl_get_track_peaks(track)` | Niveaux audio L/R en temps réel |
| `fl_get_track_stereo(track)` | Séparation stéréo d'une piste |
| `fl_get_route_info(track)` | Routing vers les autres pistes |

### Mixer — écriture
| Outil | Description |
|-------|-------------|
| `fl_set_track_volume(track, volume)` | Volume normalisé 0.0–1.25 (0.8 = 0 dB) |
| `fl_set_track_pan(track, pan)` | Pan -1.0 (gauche) → +1.0 (droite) |
| `fl_set_track_mute(track, muted)` | Mute/unmute |
| `fl_set_track_solo(track, solo)` | Solo/unsolo |
| `fl_set_track_stereo(track, sep)` | Séparation stéréo |
| `fl_set_slot_enabled(track, slot, enabled)` | Active/bypasse un plugin |
| `fl_set_track_slots_enabled(track, enabled)` | Active/bypasse tous les slots |
| `fl_set_record_arm(track, armed)` | Arme une piste pour l'enregistrement |
| `fl_set_sidechain(source, target)` | Configure un sidechain entre pistes |

### Plugins — lecture
| Outil | Description |
|-------|-------------|
| `fl_get_plugin_param(track, slot, index)` | Valeur d'un paramètre (normalisée 0.0–1.0) |
| `fl_get_plugin_params(track, slot, indices)` | **Batch read** : N paramètres en 1 round-trip (~150 ms au lieu de N×150 ms) |
| `fl_get_plugin_mix_level(track, slot)` | Niveau dry/wet du plugin |
| `fl_get_native_eq(track)` | EQ 3 bandes native FL Studio de la piste |
| `fl_discover_plugin_params(track, slot)` | Carte complète des paramètres d'un plugin ⚠️ résultat ~219 KB — utiliser PARAM-MAPS.md à la place si le plugin est déjà connu |

### Plugins — écriture
| Outil | Description |
|-------|-------------|
| `fl_set_plugin_params(track, slot, changes)` | Batch write : `[{"index": N, "value": 0.0–1.0}]` |
| `fl_set_plugin_param_rec(track, slot, index, value)` | Write via bus REC (à éviter, voir LECONS-APPRISES.md) |
| `fl_set_plugin_mix_level(track, slot, level)` | Dry/wet du plugin |
| `fl_set_native_eq_band(track, band, gain, freq, q)` | EQ 3 bandes native |

### Plugins — presets
| Outil | Description |
|-------|-------------|
| `fl_get_preset_count(track, slot)` | Nombre de presets disponibles |
| `fl_next_preset(track, slot)` / `fl_load_preset(track, slot, index)` | Naviguer dans les presets |
| `fl_list_mixer_presets` / `fl_load_mixer_preset` / `fl_select_mixer_preset` | Presets de piste mixer (FST) |
| `fl_deploy_mixer_preset(track, preset_path)` | Charge un preset FST sur une piste |
| `fl_list_available_plugins` | Liste tous les plugins installés (lit la DB FL Studio) |

### Channel Rack — v0.2
| Outil | Description |
|-------|-------------|
| `fl_get_channel_rack_info` | Liste tous les instruments du Channel Rack |
| `fl_get_channel_info(index)` | Détail d'un canal précis |

### Audio & analyse
| Outil | Description |
|-------|-------------|
| `fl_resolve_track_audio(track)` | Cherche le fichier audio associé à une piste |
| `fl_get_track_stereo(track)` | Mesure la séparation stéréo |
| `fl_analyze_audio(filepath)` | Librosa : LUFS, peak, dynamic range, bandes de fréquence, mix_notes |
| `fl_analyze_mix_folder(folder)` | `fl_analyze_audio` sur tout un dossier de Split-export |
| `fl_evaluate_mix_quality(filepath)` | Oreilles IA no-reference (audiobox-aesthetics, CE/CU/PC/PQ) — sous-processus `.venv-audio-ai/`, ~15-30s/appel |
| `fl_detect_masking(folder)` | Détection de conflits fréquentiels localisés entre pistes (DSP pur, pas de ML) — quelles pistes se chevauchent, dans quelle bande, à quel point |

### Mémoire de session
| Outil | Description |
|-------|-------------|
| `fl_log_session_event(session, event_type, data)` | Journal JSON Lines append-only (`sessions/<session>.jsonl`) — trace les changements de plugins, scores, conflits de masking. Survit aux redémarrages du serveur MCP |
| `fl_get_session_history(session, limit, event_type)` | Relit le journal d'une session, filtrable par type d'événement |
| `fl_list_sessions` | Liste toutes les sessions journalisées avec compteur d'événements |

### Utilitaires
| Outil | Description |
|-------|-------------|
| `fl_show_notification(msg)` | Affiche un message dans FL Studio |
| `fl_wait_for_plugin(track, slot)` | Attend qu'un plugin soit chargé |
| `fl_remove_plugin(track, slot)` | Supprime un plugin d'un slot |
| `fl_load_plugin_via_ui(track, slot, name)` | Charge un plugin via l'UI (lent, ~2s) |
| `fl_probe_export` / `fl_probe_browser_structure` | Exploration de la structure FL Studio |

---

## 6. Gotchas critiques — lire avant d'écrire du code

### Le readback ment après une écriture
`getParamValue` retourne l'ancienne valeur pendant ~3–15 s après un `setParamValue`.
**L'écriture a réussi si elle retourne `applied`.** Vérifier à l'écran, pas par relecture immédiate.

### Pro-Q 3 — indexation des bandes
```python
# base_index = (numero_bande - 1) * 13
# +0=Used +1=Enabled +2=Freq +3=Gain +7=Q +8=Shape

# Formules de conversion
freq_norm = math.log10(hz / 10.0) / math.log10(3000.0)  # 10 Hz→0.0 … 30 kHz→1.0
gain_norm = 0.5 + dB / 60.0                               # -30 dB→0.0 … +30 dB→1.0
```

Shapes : `Bell=0.0`, `LowShelf=0.10`, `LowCut=0.25`, `HighShelf=0.375`, `HighCut=0.45`, `Notch=0.60`

### `general.processRECEvent` crashe FL Studio
Ne jamais utiliser pour contrôler des params plugin. Handler désactivé.

### `navigateBrowserTabs` sans browser ouvert = crash natif
Toujours appeler `ui.showWindow(4)` avant. `getFocusedNodeCaption()` retourne toujours `""` depuis un handler bridge — inutilisable programmatiquement.

### EQ native FL Studio (3 bandes)
```python
gain_dB = (norm - 0.5) * 36     # 0.0=-18 dB, 0.5=0 dB, 1.0=+18 dB
freq_Hz  = 10 * 1600**norm       # 0.0=10 Hz, 1.0=16 kHz
```

### Plugins Waves (VST14 seulement disponible)
VST15 et VST13 ne sont pas installés sur cette machine. Les presets sauvegardés avec ces versions peuvent ne pas se charger.

### Threshold/Peak Reduction à 1.0 ou 0.0 = plugin neutralisé
**Toujours vérifier ces params en début d'analyse — un plugin chargé ≠ un plugin actif :**
- C1 (Waves) : idx 8 = threshold. `1.0` = aucune compression.
- RCompressor : idx 3 = threshold. `1.0` = aucune compression.
- Sibilance : idx 4 = threshold. `1.0` = aucun de-essing.
- LALA (LA-2A) : idx 2 = Peak Reduction. `0.0` = aucune compression.
- CLA-76 : pas de threshold — c'est l'`Input` (idx 2) qui pilote.

### `fl_show_notification` — entier requis, pas du texte
`ui.showNotification()` attend un **ID entier** (liste prédéfinie FL). Passer du texte libre → `TypeError`. Fix : le bridge bascule sur `ui.setHintMsg(str)` pour le texte libre. Déjà corrigé dans le bridge v0.1.0+.

### `fl_get_full_track_info` — `enabled` était toujours `null`
FL 2025 n'expose pas `plugins.isEnabled`. Fix bridge (2026-06-15) : tente `getParamValue(-1, ...)` en fallback, puis `True` par défaut. L'état bypass **n'est pas parfaitement fiable par API** — vérifier visuellement si un slot semble inactif malgré `enabled: true`.

### Déploiement bridge — chemin réel vs chemin rapporté
`fl_ping` rapporte `script_dir` = `C:\Users\USER\Documents\Image-Line\...` (chemin inexistant).
**Vrai chemin de déploiement :** `D:\Image-Line\FL Studio\Settings\Hardware\fLMCP Bridge\device_FLStudioMCP.py`.
Après copie → **F5 dans le Script Editor FL Studio** obligatoire pour recharger.

### `fl_discover_plugin_params` — filtre universel (2026-06-15)
Le filtre classique `avant MIDI CC #0` échoue pour Auto-Tune Pro (MIDI CC commence à idx 4096).
**Script universel :**
```python
[p for p in params if p['name'].strip() and not p['name'].startswith('MIDI')]
```
Réutiliser `PARAM-MAPS.md` en priorité — tous les plugins courants déjà cartographiés.

### Session startup — workflow optimal
1. `fl_get_full_track_info` sur chaque piste → liste nom + enabled de tous les slots
2. Pour chaque plugin, vérifier si le nom est dans **`PARAM-MAPS.md`** → utiliser les index directement
3. Si plugin inconnu → `fl_discover_plugin_params` + filtrage → ajouter à `PARAM-MAPS.md`
4. Vérifier threshold/Peak Reduction sur tous les compresseurs/de-essers avant d'appliquer le mix

---

## 7. État actuel du projet

**Branche active : `v0.2-foundations`**

### Fonctionnel et testé
- Connexion bridge MIDI SysEx (52/52 tests passent)
- Lecture complète du mixer : pistes, slots, peaks, routing, **état enabled/bypass** (fix 2026-06-15)
- Modification volume/pan/mute/solo/sidechain/send level
- Contrôle paramètres plugins : FabFilter (Pro-Q 3, Pro-C 2, Pro-R), Valhalla, Auto-Tune Pro, Waves
- EQ native 3 bandes FL Studio
- Presets FST mixer
- BPM (`fl_set_bpm`)
- Channel Rack inspection
- **Batch read** params : `fl_get_plugin_params` (N index en 1 round-trip — ajouté 2026-06-14)
- **PARAM-MAPS.md** : tous les plugins de la session cartographiés (2026-06-14/15)

### Session courante mixée (2026-06-15)
| Track | Plugins configurés |
|-------|-------------------|
| t0 Master | Pro-Q 3 (s0) + C1 comp-sc (s1) — glue -28 dB |
| t1 Insert 1 | Pro-Q 3 (s0) + C1 comp-sc (s1) — bus beat |
| t2/t3 EFFET VOIX | Auto-Tune Pro (s0, intact) + Pro-Q 3 (s1) + Smack Attack (s2) + TransX Wide (s3, range 0dB) + Sibilance (s4, -14.2dB) + PuigTec (s5) + RCompressor (s6, -19.2dB) + CLA-76 (s7) + ValhaSpaceMod (s9, 18% wet) |
| t6 Insert 6 | Bus reverb parallèle — Pro-R + ValhaSupermassive + Pro-C 2 (thr -6dB) + ValhaSpaceMod + LALA (PR 45%) + C1 + Pro-Q 3 + Fruity Limiter. **Send actif : t1 → t6 @ 20%** |

### Non implémenté (dépriorisé)
- Navigation browser programmatique (impossible — voir LECONS-APPRISES.md)
- Mega-template auto (plugins pré-chargés/bypassés)
- Analyse audio avec Librosa — **prochaine phase majeure**
- Volumes/balance (nécessite écoute)

---

## 8. Prochaines étapes (par ordre de priorité)

1. **Volumes/balance** : ajuster les niveaux relatifs entre pistes (nécessite lecture audio)
2. **Sends voix → Insert 6** : t2/t3 peuvent aussi envoyer vers le bus reverb (à décider)
3. **Récupération audio** : identifier comment exporter/streamer une piste pour analyse Librosa
4. **Intégration Librosa** : analyser le fichier audio exporté (spectre, dynamique, LUFS)
5. **Workflow autonome** : LLM reçoit presets chargés → analyse → mix/master complet

---

## 9. Machine hôte

- **OS** : Windows 10 Pro, i5-4590 @ 3.30 GHz, 16 GB RAM
- **FL Studio** : 2025, version 25.1.4.4951, fl_version=38
- **Python** : 3.13 (`C:\Python313\python.exe`)
- **Plugins dispo** : FabFilter (Pro-Q 3, Pro-C 2, Pro-R), Valhalla (SpaceModulator, Supermassive), Auto-Tune Pro, Waves VST14 (Smack Attack, CLA-76, RCompressor, Sibilance, TransX, PuigTec EQP1A, Doubler2, LALA, C1, S1 Imager), Fruity Limiter, Tonal Balance Control 2
- **Disque** : C: ~10 GB libre (serré — Waves prend 21 GB sur C:), D: 192 GB libre

> **Note système** : computer-use désactivé (`chicagoEnabled: false`) pour préserver les ressources. Phone Link désinstallé (crashait en boucle). Si les vm_bundles manquent après une réactivation computer-use, ils se re-téléchargent automatiquement.
