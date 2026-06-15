# Journal de débogage & leçons apprises — Contrôle Pro-Q 3 / FabFilter via MCP

> **À lire en premier si tu reprends ce projet (humain ou IA).**
> Ce fichier existe pour une raison : on a perdu plusieurs sessions sur des
> fausses pistes à cause d'**un seul bug de lecture**. Tout est expliqué ici
> pour que ça ne se reproduise pas. Date de la découverte clé : **2026-06-13**.

---

## TL;DR — les 4 choses à retenir absolument

1. **`setParamValue` CONTRÔLE les bandes Pro-Q 3** (param « Band N Used », index 0, 13, 26, 39, …).
   On peut activer/désactiver une bande en écrivant `1` ou `0`. **Aucun preset, aucun
   redémarrage, aucune souris nécessaires.** C'est le contrôle total recherché.

2. **Le readback ment juste après une écriture.** `getParamValue` / `getParamValueString`
   renvoie l'**ancienne** valeur pendant quelques secondes (et pour le flag « Used », il peut
   mentir durablement). **Ce n'est PAS la preuve que l'écriture a échoué.** La vérité de terrain,
   c'est l'écran de FL Studio (ou attendre quelques secondes avant de relire).

3. **Le « il faut redémarrer FL Studio » était FAUX.** On le croyait parce qu'on relisait trop
   vite et qu'on voyait l'ancienne valeur. Les écritures s'appliquaient déjà (audible + visible).
   Ne JAMAIS conclure « il faut redémarrer » à partir d'un readback immédiat.

4. **Tout le système de presets `.fst` (ProQ3_Nbands.fst) est un contournement INUTILE.**
   Il avait été construit pour « activer les bandes » en croyant que `setParamValue` ne pouvait
   pas le faire. C'est faux. On peut le garder comme commodité, mais ce n'est pas nécessaire.

---

## La découverte centrale : `setParamValue` contrôle les bandes

### Ce qu'on croyait (FAUX)
> « FabFilter marque "Band N Used" comme non-automatable. `setParamValue` renvoie `applied`
> mais ne fait rien. Il faut donc charger un preset `.fst` pour activer les bandes. »

### Ce qui est vrai (vérifié à l'écran le 2026-06-13)
Sur EFFET VOIX (track 2, slot 1), Pro-Q 3 avec 6 bandes actives :
- Écriture `setParamValue(idx=65, value=0)` (Band 6 Used → off)
- **Résultat à l'écran : 6 bandes → 5 bandes.** La bande a disparu.
- Puis `setParamValue` sur idx 26, 39, 52 = 0 → **5 bandes → 2 bandes.**

**Conclusion : `setParamValue` ajoute et retire les bandes sans problème.**
La seule raison pour laquelle on avait conclu l'inverse : on lisait `getParamValue(idx=65)`
juste après l'écriture, ça renvoyait encore « Used », et on en déduisait « ça ne marche pas ».
**Le readback mentait. L'écriture, elle, marchait.**

### Workflow pour ajouter / retirer / régler une bande (LA bonne méthode)

```python
# Base d'une bande : base_index = (numero_bande - 1) * 13
# Offsets dans la bande : +0=Used, +1=Enabled, +2=Freq, +3=Gain, +7=Q, +8=Shape

# Activer la bande 3 et la régler en Bell +2 dB @ 3 kHz, en UN seul batch :
fl_set_plugin_params(track=2, slot=1, changes=[
    {"index": 26, "value": 1},      # Band 3 Used = on
    {"index": 28, "value": 0.713},  # Freq 3 kHz
    {"index": 29, "value": 0.533},  # Gain +2 dB
    {"index": 34, "value": 0.0},    # Shape Bell
])

# Retirer la bande 3 :
fl_set_plugin_params(track=2, slot=1, changes=[{"index": 26, "value": 0}])
```

**Ne PAS vérifier le résultat avec `fl_get_plugin_param` juste après** (il ment). Soit on regarde
l'écran, soit on attend ~3-5 s avant de relire si on a vraiment besoin d'une confirmation API.

---

## Le bug qui nous a fait tourner en rond : le readback périmé

### Symptôme
Après une écriture (`setParamValue` ou un chargement de preset), `getParamValue` renvoie
l'**ancienne** valeur. Exemple concret mesuré le 2026-06-13 :

| Param | Lecture immédiate (juste après write) | Lecture ~15 s plus tard |
|-------|----------------------------------------|--------------------------|
| Freq Band 1 (idx 2)  | `101.18 Hz` ❌ | `80.18 Hz` ✅ |
| Shape Band 1 (idx 8) | `Bell` ❌      | `Low Cut` ✅ |
| Freq Band 2 (idx 15) | `2019 Hz` ❌   | `8005 Hz` ✅ |
| Shape Band 2 (idx 21)| `Bell` ❌      | `High Shelf` ✅ |

**Les écritures étaient bonnes depuis le début.** Seule la lecture était en retard.

### Cause racine
Le bridge n'a **aucun cache** (`h_plugins_get_param` appelle directement `plugins.getParamValue`).
La staleness vient de l'**API FL Studio elle-même** : après une opération qui change l'état du
plugin (chargement de preset, et apparemment aussi certaines écritures), le « snapshot » de
paramètres interrogeable par l'API ne se resynchronise qu'après un délai / un événement FL
(traitement d'un buffer audio, repaint UI, interaction projet). Le DSP réel et l'UI, eux, sont
à jour immédiatement.

### Cas particulier : le flag « Used »
Pour le paramètre « Band N Used », le readback peut mentir **durablement** (on a lu « Used »
plusieurs fois alors que la bande était visuellement désactivée). **Ne jamais se fier au readback
du flag Used.** Se fier à l'écran.

### Règle d'or
> **Une écriture qui renvoie `applied` a réussi. Si le readback dit le contraire, c'est le
> readback qui a tort, pas l'écriture.** Vérifier visuellement, pas par relecture API immédiate.

---

## Pourquoi la piste 1 marchait du premier coup et pas la piste 2

C'est la question qui a tout débloqué. Le parallèle :

| | Piste 1 (Insert 1, slot 0) | Piste 2 (EFFET VOIX, slot 1) |
|---|---|---|
| Bandes déjà présentes ? | Oui | Non (on voulait les activer) |
| Chargement de preset ? | **Non** | Oui (`nextPreset`) |
| Readback après write | Immédiat et correct | Périmé pendant quelques secondes |
| Conclusion qu'on en tirait | « ça marche » ✅ | « ça ne marche pas, il faut redémarrer » ❌ (FAUX) |

**La seule différence, c'est l'opération de preset.** Sur la piste 1, aucun preset chargé → le
snapshot de lecture restait synchro → lecture immédiate. Sur la piste 2, le `nextPreset`
désynchronisait temporairement la lecture. **Le plugin marchait pareil dans les deux cas ; c'est
notre vérification qui était cassée sur la piste 2.**

---

## Les pièges où on a perdu du temps (à ne pas refaire)

### Piège n°1 — La boucle « sauvegarde / redémarre »
On disait à l'utilisateur : « les valeurs ne s'affichent pas, sauvegarde et redémarre FL Studio ».
**Contradiction relevée à juste titre par l'utilisateur** : sauvegarder fige l'état actuel, donc
les écritures suivantes ne seraient « jamais prises en compte automatiquement » → boucle sans fin.
**La réalité : aucun redémarrage n'était nécessaire.** Les écritures s'appliquaient. On confondait
« je n'arrive pas à relire » avec « le write a échoué ». → **Ne jamais demander de redémarrer pour
"appliquer" un changement de paramètre. Le changement est déjà appliqué.**

### Piège n°2 — Le cyclage `nextPreset` à l'aveugle
On cyclait avec `fl_next_preset` en comptant les appels pour atteindre « le preset 2 bandes ».
Problème : pour savoir où on était, on lisait le flag « Used »… qui ment. **On naviguait donc à
l'aveugle** et on atterrissait sur le mauvais preset (6 bandes au lieu de 2). → Maintenant qu'on
sait que `setParamValue` contrôle les bandes, **on n'a plus besoin de cycler du tout.**

### Piège n°3 — Croire le readback du flag « Used »
Voir plus haut. Le flag Used est le pire pour la staleness. Toujours vérifier à l'écran.

### Piège n°4 — `general.processRECEvent` qui crashe FL Studio
Tentative d'activer les bandes via le bus d'automation REC. Event ID calculé via
`mixer.getTrackPluginId(track, slot) + paramIndex`. **Crash dur** : access violation dans
`FLEngine_x64.dll` (offset B0E59F, lecture adresse 0x178 = déréférencement de pointeur nul).
**Cette formule d'event ID est FAUSSE. Ne JAMAIS réutiliser cette approche.** Handler désactivé
dans le bridge. De toute façon devenu inutile (`setParamValue` suffit).

---

## Ce qui ne marche VRAIMENT pas (vérifié, pas un artefact de lecture)

| Fonction | Statut | Détail |
|----------|--------|--------|
| `plugins.setPreset(index, …)` | ❌ Absent | `AttributeError: module 'plugins' has no attribute 'setPreset'` en FL 2025 (fl_version 38). Re-testé le 2026-06-13. Seuls `nextPreset` / `prevPreset` existent. |
| `general.processRECEvent` pour params plugin | ❌ Crash | Voir piège n°4. |
| Suppression d'un plugin d'un slot | ❌ Absent | `removeTrackPlugin` / équivalent non exposé par l'API FL 2025. Seule alternative : clic droit UI. |
| `location="channel"` (`useGlobal=True`) pour écrire sur le mixer | ❌ Silencieux | Ignore les writes mixer. Toujours `location="mixer"`. |

---

## Transport : pourquoi MIDI SysEx et rien d'autre (verdict 2026-06-14)

**Question tranchée définitivement** : peut-on remplacer MIDI SysEx (~150 ms/appel) par un canal
plus rapide — TCP, bus de fichiers, ctypes ? **Non. Prouvé, plus inféré.**

Le sandbox Python de FL Studio 2025 tourne dans un **sous-interpréteur** qui neutralise les
constructeurs C eux-mêmes. Le handler `meta.sandboxProbe` (tool `fl_probe_sandbox`) l'exécute en
direct et renvoie par MIDI :

```
socket.socket()      → NULL (SystemError sans exception)
start_new_thread     → NULL
_io.FileIO (open w)  → NULL
import ctypes        → ImportError: _ctypes ne charge pas en subinterpreter
device.midiOutSysex  → OK  ← seul canal vivant (API FL, pas de l'I/O Python)
```

**Toutes** les pistes alternatives sont mortes : socket non-bloquant dans OnIdle, bus de fichiers
(approche Calvin/MacFLStudioMCP), bus de fichiers via ctypes raw Win32. Le code TCP non-bloquant
existe déjà dans le bridge (`_start_listening`/`_pump_network` dans `OnIdle`) — l'architecture
était correcte, elle échoue juste parce que `socket.socket()` retourne NULL.

**Leçon méta** : on avait *inféré* cette limite depuis la doc sans la tester (3 sessions de doute).
Un seul handler de probe qui exécute les tests *à l'intérieur* du sandbox a tranché en un appel.
→ Quand une limite d'environnement est « supposée », **fais-la dire à l'environnement lui-même**
avant de bâtir des contournements.

**Test admin (2026-06-14)** : on a relancé FL Studio **en administrateur** et re-lancé la probe.
`file_write` reste `BLOCKED` (`_io.FileIO returned NULL`). L'élévation de privilèges ne change
rien → ce n'est PAS une restriction de droits Windows, mais un **durcissement Image-Line dans le
build Windows** (les constructeurs C `_io.FileIO`/`_socket.socket`/`start_new_thread` sont
neutralisés). Un sous-interpréteur CPython standard autorise pourtant ces trois ; seule la limite
`_ctypes` est universelle. Le bus fichier de Calvin marche sur Mac parce que le build **macOS**
n'a pas le même durcissement — pas une question d'OS, une question de build.

**Ne jamais re-tenter TCP/fichiers/ctypes** sauf changement majeur de version FL (même en admin).
Détails complets : `INVESTIGATIONS-FUTURES.md` §3.

---

## Crash natif FL Studio : navigateBrowserTabs / navigateBrowserMenu (2026-06-14)

**Exception :** `Cannot focus a disabled or invisible window`  
**Callstack :** FLEngine_x64.dll + Python312.dll — crash **natif**, non attrapable en Python.

**Cause :** `ui.navigateBrowserTabs()` et `ui.navigateBrowserMenu()` tentent de donner le focus
au panneau Browser de FL Studio. Si ce panneau est fermé/invisible au moment de l'appel, FL Studio
crash immédiatement sans possibilité de `try/except`.

**Règle :** Toujours ouvrir le browser AVANT d'appeler ces fonctions. La séquence sûre :
```python
ui.showWindow(4)  # ou ui.setFocused(4) — ouvre le browser
# … PUIS seulement appeler navigateBrowserTabs / navigateBrowserMenu
```

**Fix appliqué :** `h_browser_probe_nav` tente désormais plusieurs méthodes d'ouverture
(`showBrowser`, `showWindow(4)`, `setFocused(4)`) et retourne une erreur explicite si aucune
ne fonctionne — plutôt que de crasher FL Studio.

**Ne jamais appeler navigateBrowserTabs / navigateBrowserMenu sans ouvrir le browser d'abord.**

### Verdict final — getFocusedNodeCaption() est inutilisable depuis un handler bridge

Tests exhaustifs (2026-06-14) : même avec `showWindow(4)` + `setFocused(4)` + `navigateBrowser(1,1)`,
`getFocusedNodeCaption()` et `getFocusedNodeFileType()` retournent toujours `""` / `-1`.

Ces fonctions ne lisent la sélection que si le browser a été focusé par l'**utilisateur**
(clic ou interaction clavier). Depuis un handler bridge appelé via MIDI, le focus programmatique
ne suffit pas.

**Conséquence :** la navigation browser rapide (tabs/menu) pour localiser les FST est
**impossible de manière autonome**. L'approche mega-template (plugins pré-chargés, bypass)
est la seule solution viable pour le contrôle sans interaction utilisateur.

---

## Formules de calibration Pro-Q 3 (location="mixer")

```python
# Fréquence (log, 10 Hz – 30 000 Hz)
freq_norm = math.log10(hz / 10.0) / math.log10(3000.0)
# 80 Hz → 0.260 | 200 Hz → 0.434 | 1 kHz → 0.575 | 3 kHz → 0.713 | 8 kHz → 0.835 | 10 kHz → 0.863

# Gain (linéaire, ±30 dB)
gain_norm = 0.5 + dB / 60.0
# -2 dB → 0.467 | 0 dB → 0.50 | +2 dB → 0.533 | +3 dB → 0.55

# Shape
SHAPES = {"Bell": 0.0, "Low Shelf": 0.10, "Low Cut (HP)": 0.25,
          "High Shelf": 0.375, "High Cut (LP)": 0.45, "Notch": 0.60,
          "Band Pass": 0.75, "Tilt Shelf": 0.833, "Flat Tilt": 1.00}

# Indexation des bandes : base = (numero_bande - 1) * 13
#   +0 = Used   (0/1)   <-- contrôle l'existence de la bande, ÉCRITURE OK, lecture ment
#   +1 = Enabled (0/1)
#   +2 = Freq
#   +3 = Gain
#   +7 = Q
#   +8 = Shape
```

**Quirk timing** : laisser ~150–200 ms entre `setParams` et un éventuel `getParam`. Mais pour le
flag « Used », même ce délai ne suffit pas → vérifier à l'écran.

---

## Exemple complet vérifié — preset 2 bandes voix (2026-06-13)

Objectif : coupe-bas 80 Hz + légère remontée des aigus. Réglé sur EFFET VOIX (track 2, slot 1),
confirmé visuellement à 2 bandes propres :

```python
# Bande 1 : Low Cut (HP) @ 80 Hz
{"index": 2,  "value": 0.260}   # Freq 80 Hz
{"index": 8,  "value": 0.25}    # Shape Low Cut
# Bande 2 : High Shelf +2 dB @ 8 kHz
{"index": 15, "value": 0.835}   # Freq 8 kHz
{"index": 16, "value": 0.533}   # Gain +2 dB
{"index": 21, "value": 0.375}   # Shape High Shelf
# Bandes 3 à 8 : éteintes
{"index": 26, "value": 0}       # Band 3 Used off
{"index": 39, "value": 0}       # Band 4 Used off
{"index": 52, "value": 0}       # Band 5 Used off
```

---

## Leçons session 2026-06-15 — Mix multi-plugins & cartographie complète

### Piège #5 — Plugins « actifs » qui ne font rien (threshold/Peak Reduction neutres)
Sur cette session, **3 plugins sur 9** dans la chaîne vocale étaient chargés mais neutralisés :
- C1 comp-sc (Master + Insert 1) : Threshold idx 8 = **1.0** → aucune compression
- RCompressor (t2/t3 s6) : Threshold idx 3 = **1.0** → aucune compression
- Sibilance (t2/t3 s4) : Threshold idx 4 = **1.0** → aucun de-essing
- LALA (Insert 6 s4) : Peak Reduction idx 2 = **0.0** → aucune compression (logique inverse)

**Règle :** en début de session, lire les thresholds/Peak Reduction de tous les compresseurs et de-essers AVANT d'évaluer leur effet. Un plugin présent ≠ un plugin actif.

### Piège #6 — `fl_show_notification` crashait avec du texte
`ui.showNotification()` attend un **ID entier** FL. Passer une chaîne → `TypeError`.
Fix : le bridge bascule sur `ui.setHintMsg(str)` pour le texte libre. Corrigé dans le bridge.

### Piège #7 — `fl_get_full_track_info` retournait `enabled: null`
FL 2025 n'expose pas `plugins.isEnabled`. Fix bridge (2026-06-15) : tente `getParamValue(-1, ...)` en fallback, puis `True` par défaut. L'état bypass désormais lisible — `enabled: true` confirmé sur 9/9 slots vocaux.
⚠️ Pas parfaitement fiable : si un slot affiche `enabled: true` malgré un comportement suspect, vérifier visuellement le bouton vert dans FL Studio.

### Piège #8 — Chemin bridge ≠ `script_dir` rapporté par `fl_ping`
`fl_ping` rapporte `C:\Users\USER\Documents\Image-Line\...` (inexistant). Vrai chemin : `D:\Image-Line\FL Studio\Settings\Hardware\fLMCP Bridge\device_FLStudioMCP.py`. Après déploiement → **F5 dans le Script Editor**. Vérifier le reload : l'uptime `fl_ping` doit baisser (reset à 0 puis remonte).

### Piège #9 — Filtre `MIDI CC #0` inopérant sur Auto-Tune Pro
Plugins standard : MIDI CC commence à idx ~14-128, filtre `name.startswith('MIDI CC')` marche.
Auto-Tune Pro : params nommés épars (idx 1, 2, 4, 10…89), MIDI CC à idx **4096** → filtre classique renvoie 4096 « vrais params ».
**Script universel :**
```python
[p for p in params if p['name'].strip() and not p['name'].startswith('MIDI')]
```

### Optimisation — `fl_get_plugin_params` batch read (ajouté 2026-06-14)
Lit N paramètres en 1 round-trip (~150 ms total au lieu de N×150 ms).
Handler bridge `plugins.getParams`. Outil MCP `fl_get_plugin_params(track, slot, indices=[...])`.

### Architecture — Insert 6 = bus reverb parallèle (2026-06-15)
Pro-R 100% wet + ValhaSupermassive + modulation → compression → EQ → limiter = preset **bus reverb parallèle**, pas mastering. Send activé : t1 → Insert 6 @ 20%.

### PARAM-MAPS.md — cartographie complète et stratégie inter-sessions
10 plugins cartographiés (Auto-Tune Pro, Pro-R, ValhaSupermassive, Pro-C 2, LALA, Fruity Limiter + plugins précédents). Workflow startup : `fl_get_full_track_info` → comparer noms contre PARAM-MAPS → discover uniquement les inconnus. Gain : -3 à -6 min/session.

---

## Méthode de débogage qui a marché (pour la prochaine fois)

On a appliqué `superpowers:systematic-debugging` :
1. **Phase 1 — cause racine d'abord, pas de fix au pif.** On a lu le code du bridge (aucun cache),
   donc la staleness venait de l'API FL.
2. **Phase 2 — comparer ce qui marche (piste 1) à ce qui casse (piste 2).** Différence = preset.
3. **Phase 3 — une hypothèse, un test minimal.** « Et si setParamValue contrôlait bien les bandes
   et que c'était le readback qui mentait ? » → test : couper 1 bande, **regarder l'écran**.
4. **Vérité de terrain > API.** L'écran a tranché en 1 test ce que 3 sessions de relectures API
   n'avaient pas tranché.

**La leçon méta : quand l'outil de mesure (ici l'API de lecture) est suspect, change d'instrument
de mesure (l'écran) au lieu de remesurer avec le même instrument cassé.**
