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

## 🟡 PRIORITÉ MOYENNE — Confirmé limité, mais optimisation possible

### 3. Transport TCP au lieu de MIDI SysEx

**Statut actuel :** abandonné. Pivot vers MIDI SysEx le 2026-06-12.

**Raison du pivot :** « le sandbox Python de FL Studio 2025 bloque sockets, threads, etc. »

**Ce qu'on n'a PAS confirmé :**
- On n'a **jamais exécuté `import socket` depuis le script MIDI** et vu le résultat.
- La limitation a été **inférée** depuis la documentation du sandbox FL 2025, pas testée.
- Le `BridgeClient` TCP existe dans le serveur MCP et fonctionne — seul le côté FL est en question.

**Comparaison :**

| Critère | MIDI SysEx (actuel) | TCP (potentiel) |
|---------|---------------------|-----------------|
| Latence | ~100–200 ms/call | ~2–5 ms/call |
| Stabilité | ✅ validée | Inconnue |
| Complexité | Faible (un seul transport) | Moyenne (fallback MIDI si TCP absent) |
| Nécessite loopMIDI | Oui | Non |

**Ce qu'il faudra tester (quand MIDI est stable + committé) :**
```python
# Dans device_FLStudioMCP.py, ajouter en haut :
try:
    import socket
    _TCP_AVAILABLE = True
except ImportError:
    _TCP_AVAILABLE = False
# → si _TCP_AVAILABLE = True dans les logs FL, TCP est possible
```

**Impact si TCP fonctionne :** ×40 de gain en latence, suppression de la dépendance loopMIDI,
fiabilité accrue (TCP est orienté connexion vs SysEx best-effort).

**Décision actuelle :** rester MIDI tant que c'est stable. Tester TCP en parallèle quand
l'architecture est figée sur GitHub.

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
