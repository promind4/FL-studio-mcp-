# Cartes de contrôle des plugins — index normalisés (FL 2025)

> Découvert le 2026-06-14 via `fl_discover_plugin_params` (résultat ~219 KB/plugin,
> sauvegardé sur disque puis filtré). **Les vrais contrôles sont les premiers index ;
> au-delà commence la pollution `MIDI CC #N` (128 entrées) jusqu'à total=4240.**
> **Méthode de filtrage corrigée (2026-06-15) :** deux stratégies selon le plugin :
> - **Standard** (Waves, FabFilter, Valhalla) : prendre les params AVANT le premier `MIDI CC #0` (les vrais contrôles sont aux petits idx contigus).
> - **Non-standard** (Auto-Tune Pro, certains VST) : les vrais params sont ÉPARS et les MIDI CC commencent à idx 4096, pas 128. Filtrer par `nom non-vide AND idx < 4096`. L'entrée `MIDI CC #0` n'apparaît pas avant le premier "MIDI Channel N Aftertouch" (idx 4224+).
> → Script universel : `[p for p in params if p['name'].strip() and not p['name'].startswith('MIDI CC') and not p['name'].startswith('MIDI Channel')]`
>
> Toutes les valeurs sont **normalisées 0.0–1.0**. Rappel LECONS : le readback ment
> juste après une écriture (sauf après délai) — vérifier à l'écran.

## Pourquoi cette table existe
L'étape la plus lente de l'analyse de session, c'est d'identifier quoi contrôler sur
chaque plugin. Cette table supprime la phase de découverte (1 round-trip de 219 KB par
plugin) pour tous les plugins déjà rencontrés. **Réutiliser directement ces index.**

---

## Compresseurs

### C1 comp-sc Mono / C1 comp Stereo (Waves) — sur Master s1, Insert 1 s1, Insert 6 s5
| idx | nom | note |
|----:|-----|------|
| 0 | Low/Peak Ref | |
| 1 | LookAhead | |
| 2 | Comp Attack | |
| 3 | Comp Release | |
| 4 | Comp PDR Tc | |
| 5 | Comp Ratio | 0.218 ≈ ratio doux |
| 6 | Comp Makeup | 0.5 = unité |
| 7 | Output Gain | |
| 8 | **Threshold** | **1.0 = AUCUNE compression** ; baisser pour engager. 0.72 ≈ -28 dB |
| 9 | Filter Type | |
| 10 | Filter Freq | |
| 11 | Filter Q | |
| 12 | Monitor | |
| 13 | EQ Mode | |

### RCompressor Mono (Waves Renaissance) — chaîne vocale s6
| idx | nom | note |
|----:|-----|------|
| 0 | Bypass | |
| 2 | Gain | |
| 3 | **Threshold** | **1.0 = AUCUNE compression** ; 0.68 ≈ -19 dB |
| 4 | Attack | |
| 5 | Ratio | 0.514 |
| 6 | ARC / Manual | 0=ARC |
| 7 | Warm / Smooth | |
| 8 | Release | |
| 9 | Electro / Opto | |
| 10 | Mix | 1.0 = 100% wet |
| 11 | Trim | 0.5 = unité |

### CLA-76 Mono (Waves 1176 FET) — chaîne vocale s7
| idx | nom | note |
|----:|-----|------|
| 0 | Bypass | |
| 2 | Input | ↑ = plus de compression (pas de threshold sur un 1176) |
| 3 | Output | makeup |
| 4 | Attack | ⚠️ 1176 inversé : ↑ = attaque PLUS rapide |
| 5 | Release | |
| 6 | Ratio | 0.75 ≈ 4:1 (0=4,0.33=8,0.66=12,1=20 / All-buttons) |
| 7 | Analog | |
| 8 | Revision | |
| 9 | Meter | |
| 10 | Comp Off | |
| 11 | Mix | parallèle |
| 12 | Trim | |
| 13 | Auto Makeup | |

### Sibilance Mono (Waves de-esser) — chaîne vocale s4
| idx | nom | note |
|----:|-----|------|
| 0 | Bypass | |
| 2 | Lookahead | |
| 3 | Detection | |
| 4 | **Threshold** | **1.0 = AUCUN de-essing** ; 0.62 ≈ -14 dB |
| 5 | Range | quantité de réduction |
| 6 | Mode | |
| 7 | Monitor | 1 = écoute la bande de sibilance |

---

## Transitoires

### Smack Attack Mono (Waves transient designer) — chaîne vocale s2
| idx | nom | note |
|----:|-----|------|
| 0 | Bypass | |
| 2 | Attack | 1.0 = MAX (agressif/clic sur voix) |
| 3 | AttackSensitivity | |
| 4 | AttackDuration | |
| 5 | AttackShape | |
| 6 | Sustain | |
| 7 | SustainSensitivity | |
| 8 | SustainDuration | |
| 9 | SustainShape | |
| 10 | Mix | parallèle |
| 11 | Output | |
| 12 | Guard | limiteur de garde |

### TransX Wide Mono (Waves transient multibande) — chaîne vocale s3
| idx | nom |
|----:|-----|
| 0 | Bypass |
| 2 | Output Gain |
| 3 | Range |
| 4 | Sense |
| 5 | Duration |
| 6 | Release |

---

## EQ

### PuigTec EQP1A Mono (Waves Pultec) — chaîne vocale s5
| idx | nom | note |
|----:|-----|------|
| 0 | Bypass | |
| 2 | LowBoost | astuce Pultec : Boost + Atten simultanés sur les graves |
| 3 | LowAtten | |
| 4 | LowFrequency | 20/30/60/100 Hz |
| 5 | HiBoost | air |
| 6 | Bandwidth | largeur du HiBoost |
| 7 | HiFrequency | 3–16 kHz |
| 8 | HiAtten | |
| 9 | AttenSelect | fréq d'atténuation aigus |
| 10 | Gain | |
| 11 | Mains | |
| 12 | OnOff | 1 = EQ actif |

### Pro-Q 3 (FabFilter) — Master s0, Insert 1 s0, EFFET VOIX s1, Insert 6 s6
Voir `LECONS-APPRISES.md` (indexation par bande `base=(n-1)*13`, +0 Used, +2 Freq,
+3 Gain, +7 Q, +8 Shape, formules log/linéaire). 6 bandes Master/Insert1 étaient
toutes Bell 0 dB (flat) avant ce run.

---

## Modulation / Reverb (Valhalla)

### ValhallaSpaceModulator — chaîne vocale s9, Insert 6 s3
| idx | nom |
|----:|-----|
| 0 | wetDry |
| 1 | rate |
| 2 | depth |
| 3 | feedback |
| 4 | manual |
| 5 | Mode |
| 6 | Bypass |

### ValhallaSupermassive — Insert 6 s1
| idx | nom | note |
|----:|-----|------|
| 0 | Mix | 0.395 = 39.5% |
| 1 | DelaySync | 0.25 = Msec |
| 2 | DelayNote | 1/16 |
| 3 | Delay_Ms | 0.045 = 27 ms |
| 4 | DelayWarp | 35% |
| 5 | Clear | |
| 6 | Feedback | 0.5 = 50% |
| 7 | Density | 0 = 0% |
| 8 | Width | 1.0 = 100% |
| 9 | LowCut | 640 Hz |
| 10 | HighCut | 5450 Hz |
| 11 | ModRate | 0.5 Hz |
| 12 | ModDepth | 50% |
| 13 | Mode | 0.0417 = Gemini |

---

## Pitch Correction

### Auto-Tune Pro — chaîne vocale s0
⚠️ **Filtre non-standard** : les vraies commandes ne sont pas contiguës ; les params anonymes (idx sans nom) sont de l'état interne. Filtrer par `nom non-vide AND idx < 4096`.

| idx | nom | valeur actuelle | note |
|----:|-----|-----------------|------|
| 1 | Scale | 0.0357 = MINOR | clé musicale — **ne pas changer sans connaître la chanson** |
| 2 | Key | 0.3636 = E | tonalité — **idem** |
| 3 | Detune | 0.5 = 440 Hz | référence A |
| 4 | Retune Speed | 0.78 = 11 ms | rapide/audible ; ↑ = plus naturel, ↓ = effet T-Pain |
| 5 | Vibrato Shape | 0 = NO VIBRATO | |
| 6 | Vibrato Pitch | 0.18 = 18 cents | |
| 7 | Vibrato Rate | 0.5455 = 5.5 Hz | |
| 10 | Input type | 0.25 = ALTO/TENOR | adapter à la tessiture du chanteur |
| 61 | Humanize | 0.285 = 29 | |
| 62 | Natural Vibrato | 0.575 = 1.8 | |
| 70 | Use Formants | 0 = off | |
| 71 | Throat Length | 0.5 = 100 | |
| 74 | Transpose | 0.5 = 0 | |
| 89 | Bypass | 0 = off | |
| 90 | Flex-Tune | 0.095 = 10% | |

---

## Mastering (Insert 6 — aucune source audio actuellement)

### Pro-R (FabFilter) — Insert 6 s0
| idx | nom | valeur actuelle | note |
|----:|-----|-----------------|------|
| 0 | Space | 0.7 = 4000 ms | très long |
| 1 | Decay Rate | 0.2925 = 75% | |
| 2 | Brightness | 0.6 = 60% | |
| 3 | Character | 0.65 = 65% | |
| 4 | Distance | 0.7 = 70% | |
| 5 | Stereo Width | 0.5833 = 70% | |
| 6 | Mix | **1.0 = 100%** | ⚠️ 100% wet — fonctionne en bus parallèle uniquement |
| 7 | Lock Mix | 1 = Locked | |
| 8–N | Decay EQ Band N State | 1 = Unused | bandes EQ de la réverb, toutes inactives |
Suites : `Decay EQ Band N Frequency/Rate/Q/Shape` — base idx = 8 + (n-1)*5.

### Pro-C 2 (FabFilter) — Insert 6 s2
| idx | nom | valeur actuelle | note |
|----:|-----|-----------------|------|
| 0 | Style | 0 = Clean | |
| 1 | **Threshold** | 0.3634 = **-38.2 dB** | ⚠️ très agressif pour mastering ; préférer -6 à -12 dB |
| 2 | Ratio | 0.5814 = 3.77:1 | |
| 3 | Knee | 0.25 = +18 dB | |
| 4 | Range | 1.0 = +60 dB | max |
| 5 | Attack | 0.1199 = 0.44 ms | |
| 6 | Release | 0.5199 = 335 ms | |
| 7 | Auto Release | 0 = Off | |
| 10 | Wet Gain | 0.5 = 0 dB | |
| 14 | Auto Gain | 1 = On | |
| 34 | Mix | 0.5 = 100% | (échelle 0.5 = 100%) |
| 35 | Input Level | 0.5 = 0 dB | |
| 37 | Output Level | 0.5 = 0 dB | |
| 39 | Bypass | 0 = Not Bypassed | |

### LALA (Waves LA-2A) — Insert 6 s4
| idx | nom | valeur actuelle | note |
|----:|-----|-----------------|------|
| 0 | Bypass | 0 = off | |
| 1 | Gain | 0.32 = 32% | gain de sortie |
| 2 | **Peak Reduction** | **0 = 0%** | ⚠️ **0% = AUCUNE compression** (même piège que threshold=1.0) |
| 3 | HF | 1.0 | contrôle haute-fréquence |
| 5 | MG | 0.5 = 0 dB | mid gain |
| 11 | Bypass | **1** | ⚠️ second indicateur bypass = 1 (vérifier à l'écran) |
| 12 | Oversampling | 0 = Off | |

### Fruity Limiter — Insert 6 s7
| idx | nom | note |
|----:|-----|------|
| 0 | Gain | 0.5 = 0 dB |
| 1 | Seuil de saturation douce | 1.0 = 0 dB |
| 2 | Plafond du limiteur | 0.5 = 0 dB |
| 3 | Temps d'attaque du limiteur | 0.1115 = 2 ms |
| 5 | Temps de relâchement du limiteur | 0.5 = 85 ms |
| 7 | Fenêtre de crête du limiteur | 0.2882 = 10 ms |
| 8 | Seuil du compresseur | 0.128 = -26.5 dB |
| 9 | Ratio de compression | 0.68 = 2.2:1 |
| 15 | Gain de bruit | 1.0 = 0 dB |
| 16 | Seuil de bruit | 0 = -INF dB |

---

## Pièges de calibration
- **Threshold à 1.0 = plugin neutralisé** (C1, RCompressor, Sibilance partaient tous
  à 1.0 → ne faisaient RIEN). Vérifier les thresholds en début d'analyse.
- **Peak Reduction à 0% = LALA neutralisé** (même principe : LA-2A compresse via
  Peak Reduction, pas threshold — idx 2 = 0.0 → aucune réduction de gain).
- **Pro-C 2 idx 11 Bypass = 1 (LALA idx 11)** : certains plugins ont un second indicateur
  bypass interne. Vérifier à l'écran si le résultat semble incohérent.
- **Pro-R Mix = 100%** : sur une piste parallèle c'est normal ; en insert série c'est
  un preset "bus reverb" — ne pas changer sauf si on veut un preset différent.
- **CLA-76 n'a pas de threshold** : c'est l'`Input` qui pilote la compression.
- **Auto-Tune Pro Retune Speed = 11ms** : rapide/audible (effet). Valeur >50ms = plus naturel.
  Key/Scale = E Minor actuellement — décision musicale, ne pas changer sans connaître la chanson.
- **`enabled: null` dans fl_get_full_track_info** : FL 2025 n'expose pas `plugins.isEnabled`.
  Le bridge (v0.1.0) tente `getParamValue(-1, ...)` en fallback ; si ça échoue, retourne `True`
  (présumé actif). L'état bypass réel n'est **pas fiable par API** → vérifier à l'écran.
  `fl_get_slot_info` retourne le même résultat (True si API absente).
- **Découverte = 219 KB/plugin, MIDI CC à idx 4096 pour certains VST** : utiliser le filtre
  universel `[p for p in params if p['name'].strip() and not p['name'].startswith('MIDI')]`.

---

## Stratégie de réutilisation — sessions futures

**Problème :** `fl_discover_plugin_params` = 219 KB/appel = lent + consomme du contexte.
**Solution en 3 étapes au début de chaque session :**

1. `fl_list_tracks` → liste de tous les slots par piste
2. Pour chaque slot occupé (`valid=true`), récupérer le nom via `fl_get_slot_info`
3. **Si le nom est dans PARAM-MAPS.md → utiliser les index directement** (zéro appel discover)
   **Sinon → appeler `fl_discover_plugin_params`, filtrer avec le script universel, ajouter à PARAM-MAPS.md**

Cette table est **indexée par nom de plugin** (pas par track/slot), donc réutilisable entre sessions.
Un nouveau plugin inconnu coûte 1 discover (~3s) ; tous les plugins déjà vus coûtent 0.
