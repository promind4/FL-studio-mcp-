# COMMANDS — Registre des commandes métier

> **Point d'entrée :** Si tu arrives ici directement, lis d'abord [`ONBOARDING.md`](ONBOARDING.md).
> **Rôle de ce document :** Couche de routage entre l'intention utilisateur et les méthodologies.
> Chaque commande définit explicitement quoi consulter, quoi vérifier, et quand la tâche est terminée —
> **indépendamment du LLM qui l'exécute.**
> **Lire avant :** [`ONBOARDING.md`](ONBOARDING.md)
> **Lire en complément :** [`MIX-WORKFLOW.md`](MIX-WORKFLOW.md), [`LECONS-APPRISES.md`](LECONS-APPRISES.md), [`PARAM-MAPS.md`](PARAM-MAPS.md)

---

## Pourquoi ce registre existe

Une demande en langage naturel ("mixe la session", "regarde la voix") oblige le LLM à interpréter
l'intention puis à deviner quelles méthodologies charger. Cette interprétation varie d'un modèle à
l'autre et d'une session à l'autre — source d'oublis et de traitements partiels.

Ce registre élimine l'interprétation : chaque commande est un contrat fixe. Si l'utilisateur tape
ou évoque l'intention d'une commande ci-dessous, le comportement attendu est défini ici, pas inventé
à la volée.

**Reconnaissance d'intention :** l'utilisateur n'a pas besoin de taper le nom exact de la commande
(`MIX_SESSION`). Une demande équivalente en langage naturel ("mixe toute la session", "fais un mix
complet") doit être routée vers la même commande. En cas d'ambiguïté entre deux commandes (ex. :
"travaille sur la compression de la voix" → `MIX_TRACK` ou `MIX_PLUGIN` ?), demander confirmation
plutôt que de deviner.

---

## Principe général — avant toute commande

1. Analyser la session (état actuel, contexte du projet).
2. Identifier les pistes concernées par la commande.
3. Identifier tous les plugins présents sur ces pistes.
4. Comprendre le rôle de chaque plugin dans la chaîne.
5. Consulter les méthodologies associées à la commande.
6. Effectuer les modifications pertinentes.
7. Vérifier qu'aucune piste, qu'aucun plugin n'a été oublié (checklist de la commande).

Aucune commande ne doit conduire à une analyse partielle involontaire.

---

## MIX_SESSION

**Intention :** Mixer l'ensemble de la session.

**Portée :** Toutes les pistes mixer du projet, y compris bus et master.

**Documents requis :**
- [`MIX-WORKFLOW.md`](MIX-WORKFLOW.md) — trame complète (étapes ⓪–⑨)
- [`LECONS-APPRISES.md`](LECONS-APPRISES.md) — règles permanentes P1/P2 + pièges
- [`PARAM-MAPS.md`](PARAM-MAPS.md) — index par plugin rencontré
- [`CONTEXT.md`](CONTEXT.md) §5 — outils disponibles

**Méthodologies requises :**
- Étape ⓪ de MIX-WORKFLOW.md : audit exhaustif AVANT toute modification
- Règle R1 (Channel Rack avant faders mixer)
- Règle R2 (couverture exhaustive — zéro plugin ignoré)
- Ordre des étapes ①–⑨ de MIX-WORKFLOW.md (ne jamais sauter une étape)

**Workflow :**
```
Pour chaque piste (dans l'ordre du mixer, master en dernier) :
  1. fl_audit_track(piste) — identifier tous les plugins du slot 0 au dernier
  2. Pour chaque plugin :
     a. Lire ses paramètres clés
     b. Analyser son rôle dans la chaîne et son interaction avec les plugins voisins
     c. Décider explicitement : configurer / laisser / désactiver / reporter
     d. Appliquer si nécessaire
  3. Valider la piste (peak, niveau perçu cohérent avec son rôle)
  4. Passer à la piste suivante — NE PAS s'arrêter avant la dernière

Une fois toutes les pistes traitées :
  5. Vérification globale de cohérence (balance relative entre pistes)
  6. Contrôle des niveaux (Channel Rack en priorité — règle R1)
  7. Contrôle des bus (sends actifs, niveaux de retour)
  8. Contrôle du master (peak, LUFS, présence d'un limiter)
```

**Vérifications obligatoires (checklist de fin de tâche) :**
- [ ] Toutes les pistes ont été auditées (`fl_audit_track` appelé sur chacune)
- [ ] Chaque plugin de chaque piste a reçu une décision explicite
- [ ] Aucun compresseur/de-esser neutralisé n'est resté tel quel sans justification
- [ ] Les niveaux individuels ont été ajustés via Channel Rack, pas via les faders mixer
- [ ] Les sends vers les bus (reverb, delay) ont été vérifiés pour chaque piste concernée
- [ ] Le master a été contrôlé en dernier (peak, LUFS, limiter)
- [ ] PARAM-MAPS.md et LECONS-APPRISES.md mis à jour si une nouvelle leçon a été apprise
- [ ] Rappel Ctrl+S communiqué à l'utilisateur

**Critère de validation :** Le rapport final liste explicitement chaque piste et chaque plugin
avec sa décision — pas de zone d'ombre. Pas besoin pour l'utilisateur de demander "continue" ou
"tu as oublié X".

---

## MIX_TRACK

**Intention :** Mixer une piste spécifique.

**Portée :** Une piste mixer désignée, intégralement (tous ses plugins).

**Documents requis :**
- [`MIX-WORKFLOW.md`](MIX-WORKFLOW.md) — étapes pertinentes selon les plugins présents
- [`PARAM-MAPS.md`](PARAM-MAPS.md) — index des plugins de cette piste
- [`LECONS-APPRISES.md`](LECONS-APPRISES.md) — pièges connus pour ces plugins

**Méthodologies requises :**
- Audit complet de la piste (`fl_audit_track`) avant toute modification
- Règle R2 appliquée à l'échelle de la piste : tous ses plugins évalués, pas seulement celui visé par la demande
- Règle R1 pour tout ajustement de niveau

**Workflow :**
```
1. fl_audit_track(piste ciblée) — lister tous les slots
2. Pour CHAQUE plugin de la piste (même si la demande semble cibler un seul) :
   a. Lire ses paramètres
   b. Évaluer s'il interagit avec le plugin principalement visé
   c. Décider et appliquer si pertinent
3. Valider la piste dans son ensemble
```

**Vérifications obligatoires :**
- [ ] Tous les plugins de la piste ont été listés, pas seulement celui mentionné dans la demande
- [ ] Les interactions entre plugins ont été considérées (ex. : changer un EQ avant un compresseur change son comportement)
- [ ] Les niveaux ajustés via Channel Rack si pertinent

**Critère de validation :** La piste est cohérente dans son ensemble, pas seulement sur le point demandé.

---

## MIX_PLUGIN

**Intention :** Travailler sur un plugin précis.

**Portée :** Un plugin désigné, mais analysé dans le contexte de sa chaîne complète.

**Documents requis :**
- [`PARAM-MAPS.md`](PARAM-MAPS.md) — index du plugin ciblé
- [`LECONS-APPRISES.md`](LECONS-APPRISES.md) — pièges connus de ce plugin

**Méthodologies requises :**
- Lire la position du plugin dans la chaîne (slot précédent et suivant)
- Règle R3 : ne jamais copier une valeur de PARAM-MAPS sans analyser la situation réelle

**Workflow :**
```
1. fl_get_plugin_params(piste, slot, indices) — lire l'état actuel du plugin ciblé
2. fl_audit_track(piste) — comprendre le reste de la chaîne (slots voisins)
3. Analyser : le réglage du plugin ciblé est-il cohérent avec ce qui le précède/suit ?
4. Ajuster le plugin ciblé
5. Si l'ajustement casse la cohérence avec un plugin voisin, le signaler ou ajuster aussi
```

**Vérifications obligatoires :**
- [ ] Le plugin ciblé a été lu avant modification (pas de readback supposé)
- [ ] Le contexte de la chaîne (plugins voisins) a été pris en compte
- [ ] Aucune valeur de PARAM-MAPS copiée sans analyse de la situation réelle

**Critère de validation :** Le plugin ciblé est réglé ET reste cohérent avec le reste de la chaîne.

---

## MASTER

**Intention :** Effectuer le mastering du projet.

**Portée :** Chaîne master (T0) et résultat global du mix.

**Documents requis :**
- [`MIX-WORKFLOW.md`](MIX-WORKFLOW.md) §11 (Étape ⑨ — Master)
- [`PARAM-MAPS.md`](PARAM-MAPS.md) — section bus/master (C1 comp-sc, Fruity Limiter)
- [`LECONS-APPRISES.md`](LECONS-APPRISES.md) — formule fader mixer, pièges compresseur master

**Méthodologies requises :**
- Stabiliser TOUTES les pistes avant de toucher au master (anti-pattern documenté : ne jamais commencer par le master)
- Vérifier la présence et l'état d'un limiter avant d'exporter

**Points prioritaires à contrôler :**
- Équilibre spectral global (bandes de fréquence du mix complet)
- Dynamique (dynamic_range_db — ni trop compressé ni trop lâche)
- Niveau perçu (LUFS intégré)
- Contrôle du loudness : -14 LUFS streaming / -9 à -10 LUFS radio/club
- Contrôle des crêtes : peak_dbfs ne doit jamais dépasser -1 dBFS sans limiter actif
- Compatibilité plateformes (streaming vs radio — cibles différentes)
- Cohérence du rendu final (le mix sonne pareil sur le master que piste par piste)

**Workflow :**
```
1. Vérifier que toutes les pistes ont déjà été mixées (MIX_SESSION complété ou pistes stables)
2. fl_audit_track(0) — auditer la chaîne master complète
3. fl_analyze_audio(export_master.wav) — LUFS, peak, dynamic_range, bandes
4. Comparer aux cibles (streaming -14 LUFS / radio -9 à -10 LUFS)
5. Ajuster EQ master, compression bus, limiter selon l'écart constaté
6. Re-exporter et re-analyser pour confirmer
```

**Vérifications obligatoires :**
- [ ] Toutes les pistes étaient stables avant de commencer le mastering
- [ ] Un limiter est présent et actif sur le master (ou son absence est signalée explicitement)
- [ ] peak_dbfs < -1 dBFS sur l'export final
- [ ] LUFS dans la cible choisie (streaming ou radio, à clarifier avec l'utilisateur si ambigu)
- [ ] Le rendu a été comparé avant/après (pas de dégradation du mix sous-jacent)

**Critère de validation :** L'export master respecte les cibles de loudness et de peak sans avoir dégradé l'équilibre du mix.

---

## ANALYZE_SESSION

**Intention :** Analyser sans modifier.

**Portée :** Toutes les pistes concernées par la demande (ou toute la session si non précisé).

**Documents requis :**
- [`CONTEXT.md`](CONTEXT.md) §5 — outils de lecture/analyse disponibles
- [`MIX-WORKFLOW.md`](MIX-WORKFLOW.md) — seuils d'alerte (étape ①)

**Méthodologies requises :**
- Audit en lecture uniquement (`fl_audit_track`, `fl_analyze_audio`) — aucune écriture
- Détection des pièges connus (threshold neutralisé, ratio 1:1, etc.) sans les corriger

**Workflow :**
```
1. fl_audit_track sur chaque piste concernée (lecture seule)
2. fl_analyze_audio / fl_analyze_mix_folder si des fichiers audio sont disponibles
3. Pour chaque plugin : détecter s'il est neutralisé ou mal calibré (sans corriger)
4. Produire un rapport : pistes, plugins, problèmes potentiels, actions proposées
```

**Vérifications obligatoires :**
- [ ] Aucun outil d'écriture (`fl_set_*`) n'a été appelé
- [ ] Le rapport couvre toutes les pistes demandées
- [ ] Chaque problème détecté est accompagné d'une action proposée (mais non appliquée)

**Critère de validation :** L'utilisateur reçoit un diagnostic complet et peut décider des actions à appliquer ensuite (typiquement via `MIX_SESSION` ou `MIX_TRACK`).

---

## DOCUMENTATION

**Intention :** Mettre à jour la base documentaire.

**Portée :** Les fichiers Markdown de méthodologie (`MIX-WORKFLOW.md`, `LECONS-APPRISES.md`, `PARAM-MAPS.md`, `CONTEXT.md`, `ONBOARDING.md`, `COMMANDS.md`).

**Documents requis :**
- [`ONBOARDING.md`](ONBOARDING.md) — carte documentaire pour savoir où ranger la nouvelle connaissance

**Méthodologies requises :**
- Respecter la règle R3 : PARAM-MAPS reste documentaire, ne jamais y écrire une valeur comme "recommandation"
- Ajouter les références croisées (liens vers les autres docs concernés)
- Maintenir la cohérence : si une règle change, la mettre à jour partout où elle apparaît (docs + mémoire persistante)

**Workflow :**
```
1. Identifier la nouvelle connaissance (bug trouvé, règle établie, calibration confirmée)
2. Déterminer le document approprié :
   - Bug/piège → LECONS-APPRISES.md
   - Calibration plugin → PARAM-MAPS.md (avec mention "valeur observée", pas "valeur recommandée")
   - Règle de fonctionnement → ONBOARDING.md + LECONS-APPRISES.md + mémoire persistante
   - Outil ou architecture → CONTEXT.md
   - Nouvelle commande → COMMANDS.md
3. Ajouter les références croisées nécessaires
4. Vérifier que le bloc de navigation en tête du document modifié reste cohérent
5. Commit + push si demandé
```

**Vérifications obligatoires :**
- [ ] La connaissance est dans le bon document (pas de duplication incohérente)
- [ ] Les références croisées sont à jour
- [ ] Si la connaissance est une règle permanente, elle est aussi sauvegardée en mémoire persistante

**Critère de validation :** Un autre LLM qui consulterait les docs après cette mise à jour trouverait l'information au bon endroit, avec les liens nécessaires.

---

## Routage rapide — table de référence

| Commande | Documents principaux | Vérification clé |
|----------|----------------------|-------------------|
| `MIX_SESSION` | MIX-WORKFLOW + LECONS-APPRISES + PARAM-MAPS | Zéro plugin ignoré sur zéro piste |
| `MIX_TRACK` | MIX-WORKFLOW + PARAM-MAPS | Tous les plugins de la piste évalués |
| `MIX_PLUGIN` | PARAM-MAPS + LECONS-APPRISES | Cohérence avec les plugins voisins |
| `MASTER` | MIX-WORKFLOW §11 + PARAM-MAPS (bus/master) | Peak < -1 dBFS, LUFS dans la cible |
| `ANALYZE_SESSION` | CONTEXT §5 + MIX-WORKFLOW (seuils) | Aucune écriture effectuée |
| `DOCUMENTATION` | ONBOARDING (carte) | Connaissance au bon endroit + références croisées |

---

## Vérification finale obligatoire — toutes commandes

Avant de considérer une tâche terminée, quelle que soit la commande :

- [ ] Toutes les pistes concernées par la commande ont été analysées
- [ ] Tous les plugins concernés ont été évalués (pas seulement modifiés — évalués)
- [ ] Aucune étape de la méthodologie associée n'a été oubliée
- [ ] La documentation applicable a été consultée (pas juste supposée connue)
- [ ] La demande utilisateur a été couverte dans son intégralité
- [ ] Si des changements ont été appliqués dans FL Studio : rappel Ctrl+S communiqué

**Objectif :** réduire au minimum les oublis, les traitements partiels, et la nécessité pour
l'utilisateur de relancer la tâche avec "continue" ou "tu as oublié X".
