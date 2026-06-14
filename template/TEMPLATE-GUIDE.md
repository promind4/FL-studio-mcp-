# Mega-Template FL Studio — Guide de création

> **Objectif :** créer `MCP_Template.flp` une seule fois sur ta machine principale.
> Le fichier est ensuite commité dans le repo et ouvert directement sur n'importe
> quelle autre machine. Durée estimée : **15-20 min** (installation des plugins comprise
> s'ils sont déjà installés, sinon juste le chargement).

---

## Pourquoi ce template

FL Studio 2025 ne permet pas de charger un plugin dans un slot FX par programme
(pas d'API directe, navigation browser trop lente). Ce template est la solution :
tous les plugins sont **pré-chargés mais bypassés**. L'IA active uniquement ce dont
elle a besoin via `fl_set_slot_enabled` + `fl_set_plugin_params` — sans toucher
le browser, sans interaction manuelle.

---

## Structure à créer

### Track 0 — MASTER (bus principal)

| Slot | Plugin | Rôle |
|------|--------|------|
| 0 | FabFilter Pro-Q 3 | EQ |
| 1 | FabFilter Pro-C 2 | Compression |
| 2 | SSLComp | Bus glue |
| 3 | Vitamin | Enhancement |
| 4 | WLM | Loudness meter |
| 5 | Tonal Balance Control 2 | Référence spectrale |

### Track 1 — VOCAL PRINCIPAL

| Slot | Plugin | Rôle |
|------|--------|------|
| 0 | Auto-Tune | Correction pitch |
| 1 | NS1 | Noise gate |
| 2 | FabFilter Pro-Q 3 | EQ |
| 3 | CLA-76 | Compression rapide |
| 4 | Sibilance | De-esser |
| 5 | PuigTec EQP1A | EQ vintage |
| 6 | S1 Imager | Image stéréo |
| 7 | Vocal Rider | Gain automatique |

### Track 2 — ADLIB

| Slot | Plugin | Rôle |
|------|--------|------|
| 0 | NS1 | Noise gate |
| 1 | FabFilter Pro-Q 3 | EQ |
| 2 | CLA-76 | Compression |
| 3 | RComp | Compression |
| 4 | Sibilance | De-esser |
| 5 | H-Delay | Delay |
| 6 | ValhallaSpaceModulator | Reverb/modulation |

### Track 3 — VOIX FX

| Slot | Plugin | Rôle |
|------|--------|------|
| 0 | FabFilter Pro-Q 3 | EQ |
| 1 | CLA-2A | Compression optique |
| 2 | Reel ADT | Doubling |
| 3 | MetaFlanger | Modulation |

### Track 4 — INSTRUMENTS

| Slot | Plugin | Rôle |
|------|--------|------|
| 0 | FabFilter Pro-Q 3 | EQ |
| 1 | FabFilter Pro-C 2 | Compression |
| 2 | RComp | Compression parallèle |

### Track 5 — REVERB BUS

| Slot | Plugin | Rôle |
|------|--------|------|
| 0 | FabFilter Pro-Q 3 | EQ pré-reverb |
| 1 | FabFilter Pro-R | Reverb |
| 2 | ValhallaSpaceModulator | Modulation |

### Track 6 — DELAY BUS

| Slot | Plugin | Rôle |
|------|--------|------|
| 0 | FabFilter Pro-Q 3 | EQ pré-delay |
| 1 | H-Delay | Delay |
| 2 | C1Comp | Ducking |

---

## Étapes de création dans FL Studio

### 1. Ouvrir un projet vide

`Fichier → Nouveau` (ou `Ctrl+N`). Ne pas sauvegarder encore.

### 2. Nommer les pistes du Mixer

Dans le Mixer (F9) :
- Double-clic sur le nom de chaque Insert → renommer
- Insert 1 → `VOCAL PRINCIPAL`
- Insert 2 → `ADLIB`
- Insert 3 → `VOIX FX`
- Insert 4 → `INSTRUMENTS`
- Insert 5 → `REVERB BUS`
- Insert 6 → `DELAY BUS`
- Le Master est déjà nommé `Master`

### 3. Charger les plugins (pour chaque piste)

Pour chaque piste :
1. Clic sur la piste dans le Mixer
2. Dans la zone FX à droite, clic sur le premier slot vide
3. Choisir le plugin dans la liste qui apparaît
4. **⚠️ Immédiatement après chargement : clic sur le bouton vert (bypass)** pour bypasser le slot
5. Répéter pour chaque slot dans l'ordre du tableau ci-dessus

> **Tip :** Tu peux aussi glisser-déposer les plugins depuis le Browser FL Studio
> (Ctrl+B) directement dans les slots FX. Cherche le nom du plugin dans la barre
> de recherche du browser.

### 4. Vérifier que tout est bypassé

Chaque slot doit avoir son **bouton vert éteint** (gris = bypassé).
L'IA se chargera d'activer ce dont elle a besoin.

### 5. Sauvegarder dans le dossier template

`Fichier → Sauvegarder sous` → naviguer vers :
```
D:\Craft\FL studio LLM\fl-studio-mcp\template\MCP_Template.flp
```

---

## Utilisation avec le MCP

Une fois le template ouvert dans FL Studio :

```python
# L'IA sait ce qui est chargé via template_layout.json
# Elle active uniquement ce dont elle a besoin :

fl_set_slot_enabled(track=1, slot=2, enabled=True)   # Active Pro-Q 3 sur VOCAL
fl_set_plugin_params(track=1, slot=2, changes=[
    {"index": 2,  "value": 0.260},  # LP cut @ 80 Hz
    {"index": 8,  "value": 0.25},   # Shape Low Cut
])

fl_set_slot_enabled(track=1, slot=3, enabled=True)   # Active CLA-76
# ... configure compression ...
```

---

## Sur une nouvelle machine (après git clone)

1. **Cloner le repo** et installer : `pip install -e .`
2. **Lancer le script d'install** : `.\scripts\install_windows.ps1`
   (copie le bridge + vérifie LoopMIDI)
3. **Ouvrir le template** : double-clic sur `template/MCP_Template.flp`
4. Si des plugins sont manquants : FL Studio affiche une alerte →
   clic droit sur le slot rouge → *Remplacer* → choisir l'équivalent installé
5. **Configurer FL Studio MIDI** une seule fois (voir `README.md` §3)

**Portabilité des plugins :** Waves, FabFilter et VST standard sont retrouvés
automatiquement par FL Studio via sa base de données plugins — les chemins ne
sont pas hardcodés dans le `.flp` tant que les plugins sont installés dans leurs
emplacements standards.

---

## Ajouter de nouvelles pistes au template

Le template peut évoluer. Pour ajouter une piste :
1. L'ajouter manuellement dans FL Studio (même procédure que ci-dessus)
2. Mettre à jour `template_layout.json` avec le nouveau track/slots
3. Sauvegarder le `.flp` et committer les deux fichiers

L'IA lit `template_layout.json` pour savoir ce qui est disponible — toujours
maintenir ce fichier synchronisé avec le `.flp` réel.
