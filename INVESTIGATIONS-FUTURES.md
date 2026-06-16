# Investigations futures — pistes non explorées ou abandonnées prématurément

> **Point d'entrée :** Si tu arrives ici directement, lis d'abord [`ONBOARDING.md`](ONBOARDING.md) — règles permanentes et état actuel du projet.
> **Rôle de ce document :** Fonctionnalités identifiées mais non implémentées. Pistes abandonnées prématurément. Idées à explorer après stabilisation.
> **Lire avant :** [`ONBOARDING.md`](ONBOARDING.md), [`CONTEXT.md`](CONTEXT.md) §7-8 (état et prochaines étapes)
> **Quand consulter :** En fin de session, pour planifier la suivante. Ou quand une fonctionnalité semble "impossible" — vérifier ici si elle a déjà été étudiée.

> Ce fichier liste ce qu'on a **présumé impossible** ou **abandonné sans test complet**.
> À reprendre une fois l'architecture MIDI stable, validée et commitée sur GitHub.
> Classement par priorité d'impact potentiel.

---

## ✅ RÉSOLU — Oreilles IA no-reference : audiobox-aesthetics VALIDÉ (2026-06-16)

**Besoin :** évaluer la qualité perceptive d'un mix/mastering sans morceau de référence externe
(priorité 1, voir `synthese_exploration_ai_audio.md`, `neural_ears_concept.md`, `final_architecture.md`
à la racine du dépôt). Comparaison à une référence externe (MERT) reste un besoin secondaire non testé.

**Testé et validé :** [`facebookresearch/audiobox-aesthetics`](https://github.com/facebookresearch/audiobox-aesthetics)
(Meta, 2025) — modèle no-reference, 4 axes (CE/CU/PC/PQ). Installé en **venv Python isolé**
(`.venv-audio-ai/`), **sans Docker** — torch 2.6+ supporte officiellement Python 3.13 nativement,
donc pas besoin de conteneur pour ce package.

**4 frictions rencontrées et résolues (détail complet : `PLAN-TEST-OREILLES-IA.md` avant suppression,
sinon voir commit qui l'a introduit) :**
1. `requests` manquant (dépendance non déclarée par le package) → `pip install requests`
2. `huggingface_hub` 1.19.0 cassé (bug client httpx) → pin `huggingface_hub==0.27.1`
3. SSL `CERTIFICATE_VERIFY_FAILED` → 3 antivirus (Avira/Defender/Avast) font de l'inspection TLS,
   Python ne connaît pas leur certificat racine → `pip install pip-system-certs`
4. `torchaudio` 2.11 exige `torchcodec` → exige FFmpeg système (absent, friction refusée) →
   **contournement : ne pas utiliser la CLI `audio-aes`, charger le WAV avec `soundfile` et passer
   le tensor directement à `predictor.forward([{"path": wav_tensor, "sample_rate": sr}])`**

**Validation perceptive (2026-06-16) :** testé sur 5 exports d'une session réelle (Master, Instrumental,
3 pistes vocales isolées). Le modèle distingue correctement le Master/Instrumental (PC et PQ hauts,
6.0-8.2) des pistes vocales isolées non mixées (PC chute à 1.6-2.2) — confirmé cohérent à l'écoute
par l'utilisateur.

**Décision d'intégration :** sous-processus depuis `server.py` vers `.venv-audio-ai/Scripts/python.exe`
(pas d'import torch dans le venv du serveur MCP principal — isolation délibérée). Nouveau tool prévu :
`fl_evaluate_mix_quality`. Coût ~15-30s/appel (rechargement modèle à chaque sous-processus) — acceptable
en usage asynchrone post-export. Optimisation différée si besoin : transformer le venv en petit serveur
HTTP persistant (modèle chargé une fois) plutôt que de relancer un sous-processus à chaque appel.

**Suite (2026-06-16) — décomposition du feedback : `fl_detect_masking`.** Le score audiobox-aesthetics
(CE/CU/PC/PQ) reste un agrégat — il dit "c'est moyen" sans dire pourquoi. Ajout d'un module DSP pur
(`masking_analysis.py`, pas de ML) qui compare les pistes exportées séparément (workflow Split-export,
même que `fl_analyze_mix_folder`) et détecte par paire de pistes et par bande de fréquence : le %
de temps où les deux sont actives simultanément, et l'écart d'énergie entre elles. Un écart faible
+ chevauchement fort = conflit réel (aucune des deux n'est "devant"). Un écart fort = pas de conflit,
une piste domine déjà.

Testé sur les 4 stems de la session (`INSTRUMENTAL`, `AD LIB`, `EFFET VOIX`, `EFFET VOIX 2`) :
aucun conflit détecté — résultat cohérent et explicable, pas un échec silencieux. Pour AD LIB vs
Instrumental, l'écart d'énergie reste élevé (8-53 dB selon la bande) car les exports sont à leur
niveau brut, pas encore calés au mix final. Pour les deux pistes voix entre elles, le chevauchement
temporel est trop faible (0.3-1.6%) pour qu'il y ait compétition — probablement des ad-libs ponctuels,
pas une doublure continue. Le détecteur a été débogué band par band avant cette conclusion (valeurs
brutes inspectées, pas seulement le résultat filtré) pour écarter l'hypothèse d'un bug.

**Limite connue à garder en tête :** la détection compare les niveaux des fichiers exportés tels
quels. Si l'export se fait avant le gain-staging final (faders pas encore réglés), les écarts mesurés
ne reflètent pas l'équilibre réel du mix fini — à utiliser après un passage Channel Rack/faders
(règle R1), pas avant.

**Pistes écartées pendant cette investigation :**
- **ACE-Step 1.5** (DCAE encoder pour conditionnement de référence) : composant non extractible
  proprement — noyé dans un pipeline ComfyUI + transformer 3.5B, qualifié d'« expérimental et
  incomplet » par les auteurs eux-mêmes ([issue #381](https://github.com/ace-step/ACE-Step/issues/381)).
  Rapport effort/risque mauvais comparé aux alternatives.
- **MERT** (comparaison à une référence, priorité 2) : identifié comme bon candidat (95M/330M
  paramètres, standalone, pas de reverse engineering nécessaire) mais pas encore testé. À reprendre
  si le besoin de comparaison à une référence externe se confirme en usage réel.

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

**Test admin (2026-06-14) — re-prouvé une 2ᵉ fois :** on a relancé FL Studio **en tant
qu'administrateur** puis re-lancé la probe. Résultat **identique** : `file_write → BLOCKED:
SystemError: <class '_io.FileIO'> returned NULL`. L'élévation de privilèges ne change rien.
→ La restriction n'est PAS une question de droits Windows (integrity level / ACL), sinon l'admin
l'aurait corrigée. C'est un **durcissement délibéré d'Image-Line dans le build Windows** :
`_io.FileIO`, `_socket.socket` et `start_new_thread` ont leur constructeur C neutralisé (slot
`tp_new` qui renvoie NULL). Un sous-interpréteur CPython *standard* autorise pourtant file I/O,
sockets et threads — seule la limite `_ctypes` est universelle. Donc le NULL sur `_io.FileIO`
est spécifique au build FL Windows.

**Pourquoi le bus fichier de Calvin marche sur Mac mais pas Windows :** ce n'est pas l'OS, ce
sont les **deux builds FL qui ne sont pas durcis pareil**. Le build macOS laisse `open()` passer
(Calvin l'exploite), le build Windows l'a fermé. Même version 2025, même Python embarqué,
hardening différent par plateforme. → **Ne jamais re-tenter le bus fichier sur Windows**, même
en admin, sauf changement majeur de build FL Studio.

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
