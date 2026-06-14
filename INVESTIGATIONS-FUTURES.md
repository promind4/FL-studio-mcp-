# Investigations futures — pistes non explorées ou abandonnées prématurément

> Ce fichier liste ce qu'on a **présumé impossible** ou **abandonné sans test complet**.
> À reprendre une fois l'architecture MIDI stable, validée et commitée sur GitHub.
> Classement par priorité d'impact potentiel.

---

## 🔴 PRIORITÉ HAUTE — Probablement faisable, jamais vraiment essayé

### 1. Charger un plugin dans un slot via l'API UI browser

**Statut actuel :** « impossible » — on a cherché une API directe et on a arrêté là.

**Réalité :** la probe FL Studio (2026-06-13) montre que ces fonctions UI **existent** :
```
ui.navigateBrowser      → true
ui.selectBrowserMenuItem → true
ui.getFocusedNodeCaption → true
ui.previewBrowserMenuItem → true
```

On n'a **jamais** essayé de charger un plugin en naviguant le browser FL programmatiquement.
C'était disponible depuis le début.

**Ce qu'il faudra tester :**
1. `ui.navigateBrowser` pour aller jusqu'au plugin voulu dans la liste
2. `ui.selectBrowserMenuItem` pour le sélectionner / l'insérer dans un slot
3. Vérifier que le slot cible est bien rempli après l'opération

**Impact si ça marche :** débloquerait le cas d'usage le plus demandé — insérer un Pro-Q 3,
un compresseur, n'importe quel plugin sans intervention manuelle. Contrôle total du chaîne FX.

---

### 2. Supprimer un plugin d'un slot via l'API UI

**Statut actuel :** « impossible » — `mixer.removeTrackPlugin` et `mixer.setTrackPluginId` absents.

**Réalité :** le test était réel (hasattr = false sur les deux), mais on n'a **jamais essayé**
la voie UI. Clic droit → Supprimer passe peut-être par `ui.selectBrowserMenuItem` ou un autre
appel UI.

**Ce qu'il faudra tester :**
- Explorer `ui.*` pour trouver un équivalent de « clic droit sur slot → remove »
- Ou passer par computer-use si l'API UI ne suffit pas (clic pixel)

**Impact si ça marche :** permet de « réinitialiser » un slot FX proprement, essentiel pour
reconfigurer une chaîne complète.

---

## ✅ RÉSOLU — Transport TCP : CONFIRMÉ IMPOSSIBLE (preuve, plus une inférence)

### 3. Transport TCP au lieu de MIDI SysEx — TRANCHÉ le 2026-06-14

**Statut :** ❌ **Définitivement impossible.** Ne plus jamais re-tester sauf changement
majeur de version FL Studio.

**Comment on l'a prouvé :** handler `meta.sandboxProbe` (tool `fl_probe_sandbox`) qui exécute
les tests de capacité *en direct* dans le sous-interpréteur FL et renvoie le résultat par MIDI.
Plus aucune inférence — voici les retours bruts :

```
socket_create  → BLOCKED: SystemError: socket.__init__ returned NULL
socket_bind    → BLOCKED: idem
thread_create  → BLOCKED: SystemError: start_new_thread returned NULL
file_write     → BLOCKED: SystemError: _io.FileIO returned NULL
ctypes         → BLOCKED: ImportError: module _ctypes does not support
                          loading in subinterpreters
accept_socket_active → false   (le listener TCP n'a jamais pu démarrer)
midi_active          → true    (seul canal vivant)
```

**Analyse :** le sandbox neutralise les **constructeurs C eux-mêmes** (NULL sans exception).
`_ctypes` refuse même de s'importer dans un sous-interpréteur (limitation CPython connue).
Donc :

| Piste envisagée | Verdict | Raison |
|---|---|---|
| Socket non-bloquant dans OnIdle (Piste A) | ❌ | `socket.socket()` → NULL avant tout |
| Déporter le réseau côté serveur (Piste C) | ❌ | le bridge ne peut ouvrir ni socket ni fichier |
| Bus de fichiers (méthode Calvin/MacFLStudioMCP) | ❌ | `open()` en écriture → NULL |
| Bus de fichiers via ctypes (CreateFileW raw) | ❌ | `_ctypes` ne charge pas en subinterpreter |
| **MIDI SysEx** | ✅ | API FL native (`device.midiOutSysex`/`OnMidiIn`), hors I/O Python |

**Conséquence importante :** le code TCP non-bloquant existe déjà dans le bridge
(`_start_listening`, `_pump_network` appelé depuis `OnIdle`) — l'architecture Piste A était
déjà implémentée correctement. Elle échoue uniquement parce que `socket.socket()` retourne NULL.
Le `BridgeClient` TCP côté serveur reste en place comme fallback inerte (auto-détection :
si le port 9876 ne répond pas, bascule MIDI).

**MIDI n'était jamais un compromis temporaire — c'est la solution unique et correcte.**

**Note latence :** le timeout de `fl_load_mixer_preset` n'a **rien à voir** avec le transport.
Il vient de `navigateBrowser` (~300 ms/appel × N appels) exécuté sur le thread principal de FL.
Un transport plus rapide n'y changerait rien. Solution chargement plugin = mega-template (Option 3).

---

## 🟢 CONFIRMÉ IMPOSSIBLE — Ne pas re-tester sauf changement majeur de version FL

| Fonctionnalité | Preuve | Détail |
|---|---|---|
| `plugins.setPreset(index)` | `AttributeError` direct | Absent en FL 2025 (fl_version 38). `nextPreset`/`prevPreset` existent. |
| `general.processRECEvent` pour params plugin | Crash dur FL Studio | Access violation `FLEngine_x64.dll` offset B0E59F. Event ID formula `getTrackPluginId() + paramIdx` = FAUSSE. Handler désactivé dans le bridge. |
| `mixer.loadPlugin` / `plugins.load` / `channels.addChannel` / `mixer.trackPluginLoad` | `hasattr = false` | Aucune API directe de chargement plugin. Voie UI à tester (voir #1 ci-dessus). |
| `mixer.removeTrackPlugin` / `mixer.setTrackPluginId` | `hasattr = false` | Aucune API directe de suppression. Voie UI à tester (voir #2). |
| `location="channel"` (`useGlobal=True`) pour écrire sur le mixer | Tests silencieux confirmés | Ignore les writes. Toujours `location="mixer"`. |

---

## Fausse croyance résolue — ne pas la recréer

| Croyance | Statut | Réalité |
|---|---|---|
| « `Band N Used` non-automatable — `setParamValue` ne fait rien » | ❌ FAUSSE | `setParamValue` contrôle les bandes. C'était un artefact du readback périmé. Voir `LECONS-APPRISES.md`. |
| « Il faut redémarrer FL Studio pour appliquer les writes Pro-Q 3 » | ❌ FAUSSE | Même cause. Les writes s'appliquent immédiatement. |

---

## Méthode pour les prochaines investigations

Avant de conclure « c'est impossible » :

1. **Chercher d'abord dans `hasattr`** — ce que FL Studio expose réellement, pas ce que la doc dit
2. **Tester les voies UI** (`ui.*`) quand les API directes manquent
3. **Vérifier à l'écran** si le résultat API est suspect — le readback ment parfois
4. **Une hypothèse = un test minimal**, jamais plusieurs changements en même temps

Voir `LECONS-APPRISES.md` pour la méthode de débogage complète.
