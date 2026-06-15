# MIX-WORKFLOW — Méthodologie de mixage autonome via MCP

> **À lire en premier lorsque tu commences une session de mixage.**
> Ce fichier définit l'ordre exact des opérations, les pièges à éviter,
> et les chemins vers les autres documents utiles.
> Une lecture en début de session suffit. Mettre à jour dès qu'une nouvelle leçon est apprise.

---

## 0. Ordre de lecture des fichiers — début de session obligatoire

Lire dans cet ordre, **sans exception**, avant de toucher quoi que ce soit.

```
① MIX-WORKFLOW.md (ce fichier) ← tu es ici
② CONTEXT.md                   ← architecture MCP, outils disponibles, chemins de déploiement
③ LECONS-APPRISES.md           ← bugs readback critiques (Pro-Q 3, plugins) — NE PAS IGNORER
④ PARAM-MAPS.md                ← index normalisés par plugin, à consulter avant chaque write
```

| Fichier | Temps de lecture | Utilité |
|---------|-----------------|---------|
| **`MIX-WORKFLOW.md`** | ~3 min | Trame + pièges + formules clip gain |
| [`CONTEXT.md`](CONTEXT.md) | ~2 min | Outils MCP, chemin bridge, config MIDI |
| [`LECONS-APPRISES.md`](LECONS-APPRISES.md) | ~2 min | Bugs readback Pro-Q 3, pickup mode |
| [`PARAM-MAPS.md`](PARAM-MAPS.md) | consulter au besoin | Index exacts par plugin |
| [`INVESTIGATIONS-FUTURES.md`](INVESTIGATIONS-FUTURES.md) | fin de session | Ce qui reste à explorer |

> **Pourquoi cet ordre ?** LECONS-APPRISES contient des pièges qui ont coûté plusieurs heures de débogage. Les lire avant de toucher aux plugins évite de rejouer les mêmes erreurs.

---

## 1. Ordre des opérations — la trame

Ne pas brûler les étapes. Chaque niveau doit être stabilisé avant de passer au suivant.

> ⚠️ **Les noms de plugins dans ce schéma sont des EXEMPLES issus d'une session donnée.** La chaîne varie d'un projet à l'autre. Ce qui ne varie pas, c'est l'ordre des étapes et le principe d'audit exhaustif. Adapter les plugins trouvés à l'étape correspondante.

```
⓪ AUDIT PLUGINS (inventaire complet — AVANT tout changement)
        │
        ▼
① ANALYSE AUDIO (Librosa — lire les pistes sources)
        │
        ▼
② GAIN DE CLIP (Channel Rack — corriger les niveaux bruts, pré-effets)
        │
        ▼
③ PITCH (Auto-Tune ou équivalent — vérifier clé, gamme, retune speed)
        │
        ▼
④ ÉGALISATION (EQ paramétrique ou graphique — sculpter la fréquence)
        │
        ▼
⑤ TRANSIENTS (shaper d'attaque/sustain — contrôler le transitoire)
        │
        ▼
⑥ DE-ESSING (de-esser ou EQ dynamique — avant compression)
        │
        ▼
⑦ DYNAMIQUE (compresseur(s) — body, character, bus glue)
        │
        ▼
⑧ ESPACE (reverb, delay, chorus/doubler — attention aux faux doubleurs)
        │
        ▼
⑨ MASTER (limiter, loudness final)
```

**Règle d'or : ne jamais sauter une étape. Les erreurs en ②–③ se propagent et faussent toutes les décisions suivantes.**

---

## 2. Étape ⓪ — Audit complet des plugins

> **Règle absolue : ne JAMAIS modifier quoi que ce soit avant d'avoir listé et lu tous les plugins de toutes les pistes.**

### 2a. Lister tous les tracks

```python
# Lancer en parallèle — un appel par track
fl_audit_track(track=0)   # Master
fl_audit_track(track=1)   # T1
fl_audit_track(track=2)   # T2
# ...
```

`fl_audit_track` retourne en un seul appel : plugins, état actif/bypass, et paramètres clés de chaque plugin. C'est l'outil à utiliser en début de session.

### 2b. Pour chaque piste : dresser l'inventaire

> Ce tableau est un **exemple** (session 2026-06-15). Les plugins varient. L'important : dresser le même tableau avec TOUS les plugins réellement présents, puis statuer sur chacun.

| Slot | Plugin | Enabled | Action |
|------|--------|---------|--------|
| 0 | Auto-Tune Pro *(ex.)* | ✓ | Lire clé/gamme/retune |
| 1 | Pro-Q 3 *(ex.)* | ✓ | Lire bandes actives + gains |
| 2 | Smack Attack *(ex.)* | ✓ | Lire sustain/attack/output |
| 3 | TransX Wide *(ex.)* | ✓ | Lire Fast/Slow dB |
| 4 | Sibilance *(ex.)* | ✓ | Lire threshold |
| 5 | PuigTec EQP1A *(ex.)* | ✓ | Lire LF/HF boost |
| 6 | RCompressor *(ex.)* | ✓ | Lire threshold/ratio |
| 7 | CLA-76 *(ex.)* | ✓ | Lire input/ratio |
| 9 | ValhallaSpaceModulator *(ex.)* | ✓ | Lire mode/mix |

**Pour chaque session :** remplir ce tableau avec les slots réels renvoyés par `fl_audit_track`, pas ceux ci-dessus.

### 2c. Décision pour chaque plugin

- ✅ **Configurer** — plugin utile, ajuster les paramètres
- ⚡ **Laisser tel quel** — preset déjà adapté
- 🔕 **Désactiver** — présent mais inutile ou nuisible sur cette piste
- ❌ **Retirer** — vraiment inapproprié (rare, nécessite UI)

> **Ne jamais finir un mixage sans avoir statué explicitement sur chaque plugin de chaque piste.**

### 2d. Pièges d'audit découverts (2026-06-15)

| Piège | Symptôme | Vérification |
|-------|----------|--------------|
| **Pro-Q 3 bande "Used" à 0 dB** | Bande active mais gain=0 → ne fait rien | Toujours lire idx+2 (freq), +3 (gain), +8 (shape) |
| **Sibilance threshold à 0.0 dB** | De-esser présent mais n'agit jamais | Lire index 4 — si 1.0 (0.0 dB) → inactif, fixer à ~0.62 (-14 dB) |
| **Compresseur threshold=1.0** | Compresseur présent mais aucune compression | Lire index threshold — si 1.0 → neutralisé |
| **Plugin enabled=false** | Dans la chaîne mais ne traite pas le son | Vérifier `enabled` dans fl_audit_track |
| **Smack Attack sustain 80%+ output +5 dB** | Signal trop gonflé avant la compression | Réduire sustain à 60%, output à +2 dB |
| **TransX Slow à +6 dB sur voix lead** | Corps vocal trop boursouflé, manque de clarté | Lead : Slow à 0 ou négatif / Harmony : Slow positif |
| **ValhallaSpaceModulator mode Doubler** | Ce n'est PAS une reverb | Vérifier le mode (index 5) — Doubler ≠ reverb |
| **Auto-Tune clé différente entre pistes** | Voix corrigées vers des gammes différentes | Vérifier que toutes les pistes vocales ont la même clé |

---

## 3. Étape ① — Analyse audio (Librosa)

**Format : WAV obligatoire pour le split tracks.** FL Studio ne propose pas le split par piste en MP3 — uniquement en WAV/AIFF. Le MP3 export = master stereo seul (utile pour vérifier le rendu global, pas pour l'analyse par piste).

**`analyze_seconds=30` résout le problème de taille** : `librosa.load(path, duration=30)` ne lit que les 30 premières secondes du WAV, soit ~3 MB de données indépendamment de la taille du fichier. Pas besoin de changer de format.

**Workflow export depuis FL Studio :**
1. File > Export > Wave > cocher "Sép. pistes du mix." → un WAV par piste
2. Pour vérifier le master seul (rapide) : File > Export > MP3 → master stéréo unique

**Outil :**
```python
fl_analyze_audio("D:\\TEST MCP\\TEST MCP_EFFET VOIX.wav")  # WAV ou MP3
# Toujours passer analyze_seconds=30 si le MCP server n'a pas été redémarré récemment
```

**En cas de timeout MCP** : lancer directement via Python (contournement sans redémarrage) :
```python
# Dans un terminal PowerShell :
python -c "
import sys; sys.path.insert(0, 'D:/Craft/FL studio LLM/fl-studio-mcp/src')
from fl_studio_mcp.tools.audio_analysis import analyze_audio
import json; print(json.dumps(analyze_audio('D:/TEST MCP/fichier.wav'), indent=2))
"
```

Métriques clés par piste :

| Métrique | Seuil d'alerte | Action |
|----------|---------------|--------|
| `peak_dbfs` | > −1 dBFS | Réduire le clip gain (étape ②) |
| `lufs` | > −9 LUFS | Trop fort — compresser ou réduire gain |
| `lufs` | < −20 LUFS | Trop faible — booster clip gain |
| `spectral_centroid_hz` | < 1500 Hz | Piste sombre → booter les hauts (étape ④) |
| `spectral_centroid_hz` | > 4000 Hz | Piste brillante → vérifier la sibilance |

**Analyser TOUTES les pistes, y compris doublures (LeadVox2, AdLibs) avant de commencer.**

---

## 4. Étape ② — Gain de clip (Channel Rack)

**Outil :** `fl_set_channel_volume(index, volume_db)`

Le volume Channel Rack est le gain **pré-effets** — avant toute la chaîne FX mixer.  
**C'est ici qu'on corrige les niveaux bruts.** Ne jamais utiliser le fader mixer pour ça sauf pour la correction globale du master (anti-clipping en l'absence de limiter).

### Échelle de valeurs

| dB cible | Normalisé | Usage |
|----------|-----------|-------|
| −5.18 dB | 0.78125 | **Défaut FL Studio** |
| 0 dB | 1.0 | Unity gain |
| −7 dB | 0.710 | Réduction −2 dB depuis le défaut |
| −1.3 dB | 0.945 | Boost +3.9 dB depuis le défaut |

**Formule :** `normalized = 10^(dB / 48.28)` · inverse : `dB = 48.28 × log10(normalized)`

### Pièges

- **Pickup mode** : après F5, le premier appel qui RÉDUIT le volume peut être ignoré. Workaround : monter d'abord à 0.85, puis descendre à la cible.
- **Readback** : `getChannelVolume(i, True)` retourne des dB (True = 1 = flag dB). Le −5.18 est correct.
- **Plafond 0 dB** : `setChannelVolume` avec norm > 1.0 est silencieusement capé à 1.0 = 0 dB. La plage effective est −∞ à **0 dB**. Ne pas cibler de valeurs positives.
- **Lister tous les canaux** avec `fl_get_channel_rack_info` avant de commencer — ne pas oublier les doublures.

---

## 5. Étape ③ — Pitch / Auto-Tune

**Vérifier impérativement avant tout autre traitement :**

1. **Clé (Key)** — doit correspondre à la tonalité du morceau. Une clé erronée corrige la voix vers les mauvaises notes.
2. **Gamme (Scale)** — Minor, Major, Harmonic Minor, Chromatic...
3. **Retune speed** — lent (>200 ms) = naturel / rapide (<50 ms) = effet T-Pain audible
4. **Mode** — Auto (automatique) vs Graph (manuel, nécessite notes dessinées)

### Cohérence entre pistes vocales

Toutes les pistes vocales d'un même morceau doivent avoir **la même clé et la même gamme**.  
La vitesse de retune peut différer intentionnellement :
- Voix lead : retune rapide = effet artistique assumé
- Voix harmonies/doublures : retune lent = correction naturelle invisible

**Si les clés diffèrent entre pistes → demander confirmation avant de modifier.** C'est une décision artistique.

### Paramètres Auto-Tune Pro (indices)

| Index | Paramètre | Valeur type |
|-------|-----------|-------------|
| 0 | Mode | 0=Auto, 1=Graph |
| 1 | Scale | 0=Chromatic, 0.036=Minor, 0.5=Major... |
| 2 | Key | 0=C, 0.09=C#, 0.18=D... 0.36=E, 0.83=A |
| 3 | Référence Hz | 0.5=440 Hz (standard) |
| 4 | Retune speed | 0=instantané, 0.78=11ms, 1.0=400ms |
| 9 | Humanize | 0.5=50% |
| 10 | Voice type | 0.25=Alto/Tenor |

---

## 6. Étape ④ — Égalisation

### Pro-Q 3

**Index de bande :** `base = (numéro_bande − 1) × 13`

| Offset | Paramètre | Formule |
|--------|-----------|---------|
| +0 | BandUsed | 0=off, 1=on |
| +1 | BandEnabled | 0=bypass, 1=actif |
| +2 | Fréquence | `log10(Hz/10) / log10(3000)` |
| +3 | Gain | `(dB + 30) / 60` — 0.5 = 0 dB |
| +7 | Q | voir PARAM-MAPS |
| +8 | Shape | Bell=0, LowShelf=0.10, LowCut=0.25, HighShelf=0.375, HighCut=0.45 |

**Readback** : peut mentir quelques secondes après écriture. Vérifier à l'écran, pas par relecture API immédiate.

### Principes EQ par type de piste

| Piste | HP | Coupes typiques | Boosts typiques |
|-------|-----|-----------------|-----------------|
| Beat/Instrumental | 30 Hz | −2.5dB@70Hz (sub) / −2dB@250Hz (mud) / −1.5dB@450Hz (boxy) | +1.5dB@3kHz / +1dB@8kHz |
| Voix lead | 80 Hz | −2dB@200Hz (mud) | +2dB@3kHz (présence) / +2dB@8kHz (air) |
| Voix harmonie sombre | 80 Hz | −3dB@300Hz / −1.5dB@1kHz | +3.5dB@3kHz / +3dB HS@5kHz / +4dB HS@8kHz |
| AdLibs | 80 Hz | Identique voix lead ou plus doux | Moins de présence que le lead |

### PuigTec EQP1A

Plugin de couleur — ajoute du caractère vintage.
- LF Boost @ 60 Hz : chaleur, corps (ne pas exagérer sur voix, risque de mud)
- HF Boost @ 5 kHz : présence, intelligence de la voix
- HF Atténuation @ 5 kHz : contrôle de la largeur du boost (simultané avec le boost = effet musicale)

---

## 7. Étape ⑤ — Transients (Smack Attack / TransX)

### Smack Attack — calibration voix

| Paramètre | Index | Valeur trop agressive | Valeur recommandée |
|-----------|-------|----------------------|-------------------|
| Attack amount | 3 | > 70 | 25–40 |
| Sustain amount | 7 | > 70 | 50–65 |
| Output gain | 11 | > +4 dB (norm ~0.58) | +1 à +2 dB (norm ~0.52–0.54) |

Style "Blunt" (index 9 = 1) : arrondit les consonnes — adapté aux voix.  
Style "Nail" (index 5) : renforce les transitoires — plutôt pour percussions.

### TransX Wide — rôle différencié lead vs harmonie

| Piste | Slow dB | Effet |
|-------|---------|-------|
| Voix lead | 0 ou négatif (−3 dB) | Nettoie la queue, donne de la clarté |
| Voix harmonie | Positif (+4 à +6 dB) | Étend le sustain, donne du corps et de l'espace |

Cette différence est **intentionnelle** — elle crée le contraste lead/harmonie.

---

## 8. Étape ⑥ — De-essing (Sibilance)

**Toujours vérifier avant de passer à la compression.**

Paramètres clés (Sibilance Waves) :

| Index | Paramètre | Valeur à vérifier |
|-------|-----------|------------------|
| 4 | Threshold | **Si 1.0 (0.0 dB) → inactif !** Fixer à ~0.62 (≈ −14 dB) |
| 5 | Range/Output | Même valeur que le threshold environ |
| 3 | Sensitivity | 50 = valeur standard |

**Piège fréquent :** Sibilance chargé avec un preset Full Reset → threshold à 0.0 dB = ne de-esse rien. Vérifier systématiquement.

---

## 9. Étape ⑦ — Dynamique (compression)

### Double compression voix (RComp → CLA-76)

Chaîne typique vocale RnB/Hip-Hop :
1. **RCompressor** : compression musicale, contrôle le niveau général
   - Threshold : −18 à −22 dB selon le niveau de la voix
   - Ratio : 1.5 à 2.5:1 (doux pour les harmonies, plus marqué pour le lead)
   - Attack : 5 ms / Release : 80 ms
2. **CLA-76** : coloration FET, réponse rapide, caractère
   - Ratio 4:1 standard, 8:1 pour plus d'agressivité
   - Input level drive la compression (pas un threshold)
   - "Blacky" character = réponse proche de l'original 1176

### C1 comp-sc (bus / master)

- Threshold bus instrumental : autour de −28 à −32 dB (pumping intentionnel hip-hop)
- Threshold master : autour de −24 à −28 dB (glue compression)
- Sidechain Low-Pass @ 7 kHz = les hautes fréquences ne déclenchent pas la compression

**Priorité sidechain :** configurer le routing sidechain AVANT de régler les paramètres.

---

## 10. Étape ⑧ — Espace (Reverb / Delay)

### Convention FL Studio — buses dédiés

| Bus | Rôle | Plugins typiques |
|-----|------|-----------------|
| Bus Reverb (ex. T5) | Ambiance commune à toutes les voix | Valhalla Room, Fruity Reeverb 2 |
| Bus Delay (ex. T6) | Écho lead vocal | H-Delay, Fruity Delay 3 |

Les voix envoient vers ces buses via les sends mixer — **ne pas mettre la reverb en insert** sauf si pas de bus disponible.

**Sidechain reverb :** compresseur sur le bus reverb sidechainé par la voix sèche → la reverb s'efface quand la voix chante, remonte dans les silences. Évite que la reverb noie le vocal.

### ValhallaSpaceModulator

Ce plugin est un **modulateur / chorus / doubleur** — PAS une reverb.  
Modes utiles pour voix :
- **Doubler** : épaississement subtil (mix 18–25 %)
- **Chorus** : plus large, légèrement plus coloré

Pour une vraie reverb, utiliser un autre plugin (Valhalla Room, Reeverb...).

---

## 11. Étape ⑨ — Master

```python
fl_get_track_peaks(0)   # vérifier le peak actuel
```

- Peak > 0 dBFS → limiter ou réduire le fader master
- Cible loudness streaming : −14 LUFS intégrée
- Cible loudness radio / club : −9 à −10 LUFS

### Formule fader Mixer Track
```
volume = 0.8 × 10^(dB / 45.08)   # 0.8 = référence 0 dB FL Studio
dB     = 45.08 × log10(volume / 0.8)
```
Exemples : −4 dB → 0.653 · −6 dB → 0.600 · −9 dB → 0.505

⚠️ Le fader master ne remplace pas un limiter. Sans limiter sur T0, réduire de ~4 à 5 dB laisse une marge propre avant export. Le Fruity Limiter doit être ajouté via UI.

---

## 12. Anti-patterns — ce qu'il ne faut JAMAIS faire

| ❌ Anti-pattern | ✅ Ce qu'il faut faire |
|----------------|----------------------|
| Modifier le fader mixer pour corriger un niveau | `fl_set_channel_volume` (Channel Rack, pré-effets) |
| Supposer qu'un plugin charge "à 0 dB" ou neutre | Lire ses paramètres avant toute modification |
| Conclure "l'écriture a échoué" sur readback immédiat | Attendre 2–3s ou vérifier à l'écran |
| Mixer sans avoir audité tous les plugins d'abord | Étape ⓪ obligatoire — `fl_audit_track` sur chaque piste |
| Oublier de vérifier la Sibilance threshold | Toujours lire index 4 — si 1.0 → inactif |
| Oublier les pistes doublures (LeadVox2, AdLibs) | `fl_get_channel_rack_info` → lister TOUS les canaux |
| Modifier la clé Auto-Tune sans confirmer avec l'artiste | La tonalité = décision artistique, demander avant de changer |
| Traiter uniquement l'EQ et ignorer les autres plugins | Chaque plugin de chaque piste doit être évalué |
| Utiliser computer-use / bouger l'UI | Tout passe par le bridge MCP |
| Commencer par le master | Stabiliser les pistes d'abord, master en dernier |
| Cibler > 0 dB en clip gain | FL Studio cap silencieux à 0 dB (norm=1.0) — plafond réel du Channel Rack |
| Analyser un grand WAV avec fl_analyze_audio sans `analyze_seconds` | Timeout MCP sur fichiers > 20 MB — toujours passer `analyze_seconds=30` |
| Oublier d'activer les sends vers le bus reverb | Vérifier `fl_get_route_info(vocal, reverb_bus)` pour chaque piste vocale |

---

## 13. Déploiement bridge

Fichier : `D:\Image-Line\FL Studio\Settings\Hardware\fLMCP Bridge\device_FLStudioMCP.py`  
Après modification → **F5 dans FL Studio** (pas besoin de redémarrage complet).  
Le `script_dir` de `fl_ping` est un chemin calculé, pas le chemin réel du fichier.

---

## 14. Journal des sessions

| Date | Travail réalisé |
|------|----------------|
| 2026-06-15 | Phase A-1 : analyse Librosa, clip gain 4 canaux, EQ T1/T3, Sibilance T3/T4 corrigée (0dB→−14dB), Smack Attack calibré, fl_audit_track ajouté au serveur |

