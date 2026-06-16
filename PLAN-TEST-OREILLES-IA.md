# Plan de test — Oreilles IA (audiobox-aesthetics)

> **Statut : fichier temporaire de suivi.** À supprimer une fois le test conclu (succès → contenu absorbé dans
> `INVESTIGATIONS-FUTURES.md` / `CONTEXT.md` ; échec → conclusion documentée puis fichier supprimé).
> **Objectif du fichier :** survivre à un compactage de conversation. Si le contexte est perdu, reprendre
> directement à la case `[ ]` non cochée la plus haute dans la liste.

---

## Contexte (résumé pour reprise à froid)

Le projet `fl-studio-mcp` analyse l'audio aujourd'hui par métriques mathématiques uniquement (FFT, LUFS,
dynamic range — voir `fl-studio-mcp/MIX-WORKFLOW.md` et `audio_analysis.py`). L'utilisateur veut une couche
supplémentaire de jugement perceptif — un système qui évalue si un mix/mastering "sonne bien" sans nécessiter
de morceau de référence (priorité 1). La comparaison à une référence externe (MERT) est un bonus secondaire,
pas l'objectif principal.

**Décision prise (conversation précédente) :** tester [`facebookresearch/audiobox-aesthetics`](https://github.com/facebookresearch/audiobox-aesthetics)
— modèle Meta 2025, no-reference, 4 axes de qualité (CE/CU/PC/PQ). Pas de Docker : PyTorch supporte
officiellement Python 3.13 depuis la version 2.6, et le package ne fixe aucun plafond de version Python
(`>=3.9`). Isolation prévue via un simple **venv Python**, pas un conteneur — friction minimale.

**Machine cible (mesurée) :** i5-4590 (4 cœurs, 2014), 16 Go RAM, GTX 750 Ti 2 Go VRAM, 17 Go libres sur C:,
210 Go libres sur D:, Python système 3.13.6, Docker présent mais **non utilisé pour ce test**.

**Rien n'a encore été installé.** Ce fichier documente le plan avant exécution.

---

## Phase 0 — Préparation de l'environnement isolé

- [ ] Choisir l'emplacement du venv : `D:\Craft\FL studio LLM\fl-studio-mcp\.venv-audio-ai\`
      (D: a 210 Go libres contre 17 Go sur C: — éviter C: pour les checkpoints)
- [ ] Créer le venv : `python -m venv "D:\Craft\FL studio LLM\fl-studio-mcp\.venv-audio-ai"`
- [ ] Activer le venv et vérifier la version Python isolée (`python --version` → doit rester 3.13.x mais
      dans un environnement de paquets séparé du système)
- [ ] Vérifier l'espace disque disponible sur D: avant et après installation (checkpoint + dépendances
      torch peuvent peser plusieurs Go)

**Critère de validation Phase 0 :** venv actif, isolé, espace disque suffisant confirmé.

---

## Phase 1 — Installation du package

- [ ] `pip install audiobox_aesthetics` dans le venv activé
- [ ] Noter toute erreur de résolution de dépendances (en particulier torch — vérifier qu'un wheel
      CPU existe et s'installe sans tenter de tirer CUDA inutilement vu la VRAM limitée)
- [ ] Si échec : noter le message d'erreur exact dans la section "Journal des résultats" en bas de ce
      fichier avant de chercher une solution alternative (ne pas improviser une autre approche sans
      diagnostic écrit)
- [ ] Vérifier la taille réellement installée (`pip show audiobox_aesthetics`, taille du venv) pour
      confirmer la consommation disque réelle vs estimée

**Critère de validation Phase 1 :** `import audiobox_aesthetics` réussit dans le venv sans erreur.

---

## Phase 2 — Premier test d'inférence (clip de test simple)

- [ ] Choisir un fichier WAV court déjà disponible dans le projet (export existant d'une session de
      mixage précédente — voir dossiers d'export mentionnés dans `LECONS-APPRISES.md`)
- [ ] Lancer l'inférence selon la doc du repo (CLI fournie ou appel Python direct) sur ce fichier
- [ ] Mesurer le temps de premier appel (inclut téléchargement automatique du checkpoint — nécessite
      Internet, à faire une fois) séparément du temps des appels suivants (modèle déjà en mémoire/disque)
- [ ] Noter si l'inférence tourne bien en CPU (aucune erreur liée à CUDA/VRAM) — confirmer ou infirmer
      l'hypothèse "CPU-only viable" formulée dans la conversation précédente
- [ ] Récupérer les 4 scores (CE, CU, PC, PQ) produits

**Critère de validation Phase 2 :** un score JSON à 4 axes est produit sur un fichier réel, en CPU,
dans un temps jugé acceptable pour un usage asynchrone (quelques secondes à ~1 minute — pas de seuil
strict imposé, à juger empiriquement).

---

## Phase 3 — Test de cohérence perceptive (le vrai test)

- [ ] Choisir 2-3 fichiers WAV de qualité perceptive clairement différente si possible (ex : un export
      brut non mixé vs un export après mixage/mastering de la session précédente)
- [ ] Lancer l'inférence sur chacun
- [ ] Comparer les scores obtenus à l'appréciation humaine (l'utilisateur écoute et juge, puis compare
      avec le score du modèle)
- [ ] Documenter si le modèle distingue correctement "moins bon" vs "meilleur" dans le sens attendu

**Critère de validation Phase 3 :** les scores du modèle vont globalement dans le même sens que le
jugement humain sur au moins le cas le plus contrasté (brut vs mixé). Ce n'est pas une exigence de
précision scientifique — juste une confirmation que l'outil n'est pas aléatoire ou inversé.

---

## Phase 4 — Décision d'intégration

- [ ] Si Phases 1-3 validées : rédiger la proposition d'intégration MCP (nouvel outil
      `fl_evaluate_mix_quality`, appelé après export WAV, en complément de `fl_analyze_audio` existant)
- [ ] Si échec à une phase : documenter la cause exacte dans le journal ci-dessous, décider si un
      contournement raisonnable existe (ex: bascule venv → Docker si conflit de dépendance bloquant) ou
      si la piste est abandonnée pour cette machine
- [ ] Mettre à jour `fl-studio-mcp/INVESTIGATIONS-FUTURES.md` avec la conclusion (succès intégré, ou
      échec documenté pour ne pas re-tester inutilement plus tard)
- [ ] Supprimer ce fichier de plan une fois la conclusion actée ailleurs

---

## Journal des résultats (à remplir au fur et à mesure, ne pas attendre la fin)

| Phase | Date | Résultat | Notes |
|---|---|---|---|
| — | — | — | (rien exécuté encore) |

---

## Rappel — ce qui n'est PAS dans ce plan

- Pas de MERT pour l'instant (priorité 2, reporté après validation de la priorité 1)
- Pas d'ACE-Step (écarté — voir conversation précédente, reverse engineering jugé non rentable)
- Pas de Docker pour ce test (réservé en solution de repli uniquement si le venv échoue de façon bloquante)
- Aucune intégration dans le bridge FL Studio / MCP server tant que les Phases 1-3 ne sont pas validées
