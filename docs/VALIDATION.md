# Validation v0 — checklist manuelle (sur la machine avec FL Studio 2025)

Pré-requis : `scripts/install_windows.ps1` exécuté, FL Studio redémarré,
bridge activé dans MIDI Settings (Controller type = « fLMCP Bridge »),
serveur MCP configuré dans Claude Desktop.

## Ticket 1 — Bridge TCP
- [ ] `fl_ping` → `{"connected": true}`

## Ticket 2 — Paramètres plugins
- [ ] Charger manuellement FabFilter Pro-Q 3 sur la piste mixer 1, slot 1
- [ ] `fl_discover_plugin_params(1, 0)` → liste des paramètres avec noms
- [ ] `fl_set_plugin_params(1, 0, [{"index": <freq band 1>, "value": 0.3}])`
      → le changement est VISIBLE dans l'UI du plugin
- [ ] Répéter avec un plugin Waves
- [ ] Noter : les noms de paramètres Waves sont-ils exploitables ?
      (certains VST n'exposent que "Param 1", "Param 2"...)

## Ticket 3 — Chargement de plugin
- [ ] `fl_probe_plugin_loading()` → noter quelles fonctions existent
- [ ] Si une stratégie directe existe → la tester
- [ ] Sinon : valider le repli assisté avec `fl_wait_for_plugin`

## Ticket 4 — Export audio
- [ ] `fl_probe_export()` → noter quelles fonctions existent
      (attendu : armTrack, isTrackArmed, getTrackRecordingFileName, getTrackPeaks = true)
- [ ] Stratégie principale — enregistrement disque :
      armer la piste 1 via le bridge (`fl_set_record_arm`) → lancer record+play → stop →
      vérifier que le chemin retourné existe et que le fichier WAV est lisible côté serveur
- [ ] Stratégie secondaire — sur un channel contenant un audio :
      `fl_resolve_track_audio(0)` → chemin du fichier source
- [ ] Si tout échoue : valider le flux assisté (export manuel + chemin fourni)

## Résultats → décisions
Consigner les résultats ici. Ils déterminent l'architecture définitive de
`load_plugin` et `export_track` pour le plan v1 (analyse + orchestration).
