# XTouch-LV1 — repère pour Claude Code

> Court exprès (tokens). Historique complet, mesures et pièges : `docs/CONTEXTE_DETAILLE.md` (chercher la section
> avec Grep avant toute recherche). Journal lisible : `HISTORIQUE.md`. État du moment : `../ETAT.md`.
> L'installeur Total Control vit ici (`installer.py`, `build.py`) : voir `../total-control/CLAUDE.md`.

## Produit

Behringer **X-Touch + X-Touch Extender** (USB, mode Mackie Control) comme surface de la **LV1**, sans le MCU natif
de la LV1 (contrôleur Mackie RETIRÉ de System Inventory, sinon elle garde les ports) : couleurs et noms des canaux,
vumètres post-fader, faders motorisés, Mute / Solo / Select, couches, sends on fader, trim / phase, gain et 48V X32
(via Gain Recall), transport REAPER LV1, overlay Qt sur l'écran de la LV1. Exe `XTouch-LV1.exe` (admin, sans
console), repo public `thaleosguest/xtouch-lv1`, branche `master`. Python bibliothèque standard (+ PySide6 pour
l'overlay), Windows (winmm par ctypes).

## Fichiers

- `xtouch_lv1_display.py` : le pont (`VERSION`, `App` : `setup` / `run` = `check_ports` -> `tick_input` ->
  `tick_render` -> `tick_integrations` -> `tick_wait`), `LV1Link` (connexion LV1), `LV1State`, menu de l'icône.
- `bridge/` : `faders.py` (toucher, garde-fous, moteurs), `buttons.py`, `gain.py` (X32 / trim / phase), `sends.py`,
  `lv1_watch.py` (clics LV1, suivi du Mixer / mode / sélection), `reaper.py`, `values.py` (courbe de fader, pan),
  `journal.py` (`JOURNAL` = emplacement partagé : ne jamais le réaffecter).
- `surface/` : `xtouch.py` (`Surface`, moteurs, `note_position` = écho), `midi.py` (`WinMidiIn`, `SafeMidi`),
  `display.py`, `notes.py` (notes / CC Mackie).
- `lv1/layout.py` (TOUTE la géométrie de l'écran LV1, 1920x1080), `lv1/screen.py` (fenêtres, captures),
  `lv1_clic.py` (clics PostMessage, `Target`), `lv1_patch.py` (REALIGN Input B), `lv1_db.py` (base LV1 sur copie).
- `osc.py`, `lv1_probe.py` (sonde + découverte), `lv1_finder.py` (0.8.1 : LV1 du réseau, choix, ce PC d'abord),
  `netmidi.py` (0.8.1 : X-Touch par le réseau, TCP 9310), `rtpmidi.py` (X-Touch par Ethernet en RTP-MIDI direct,
  `xtouch_rtpmidi.json` / `--rtpmidi`), `xgr_link.py` (Gain Recall HTTP), `reaper_link.py`,
  `reaper_scenes.py`, `reaper/*.lua`, `xtouch_overlay_qt.py` (overlay, processus `--overlay`), `tray.py`.
- Réglages de Joseph à côté de l'exe : `xtouch_ecran.json`, `xtouch_courbe_fader.json` (calibré : NE PAS écraser),
  `xtouch_lv1_choix.json`, journaux `xtouch_journal_*.txt` (un par lancement : la meilleure source de diagnostic).

## API réseau LV1 (MyFOH, non documentée, LV1 V17)

- Découverte `/zDNS` multicast 225.1.1.1:13337 (port TCP qui change à chaque session) ; trame
  `[taille 4 o BE][00 00 00 02 00 00 00 00][OSC]` ; poignée de main `/handshake 1 -1 1` + `/device_name` en UN envoi ;
  `/ping` -> `/pong` mêmes arguments.
- État initial = `/Channels` seulement (19 args par piste : 1er entier = solo, 2e = mute) ; état complet exige aussi
  `/Notify/Layers` et `/Notify/UserKeyInfo`, sinon redemande / reconnexion (`state_complete`).
- Couches : adopter un jeu SEULEMENT s'il est suivi de `/Notify/CurrentLayer` de la même vue. Couches et sélection
  sont locales au client (MyFOH n'envoie rien).
- Écritures : `/Set/Track/Out/Gain`, `/Set/Track/Out/Mute T|F`, `/Set/Solo`, `/Set/Track/Pan` (-45..45),
  `/SetTrackTrim`, `/SetTrackPhaseState`, `/Set/Aux/Send/*`, `/Set/UserKey k T` puis `F`, `/ClearAllSolo`.
  La LV1 RENVOIE nos propres réglages (~22 ms). Pans / envois de départ : lus dans la base (param 436).
- Groupes : 0 In, 1 Grp, 2 Fx, 3 LR, 4 C, 5 M, 6 Mtx, 7 Cue, 8 TB, 12 DCA, 25 Mon. Aucune commande de sélection
  ni de mode de couche : clics simulés (`lv1_clic`, admin, garde-fous lus à l'écran avant chaque clic).

## X-Touch (Mackie Control)

- SysEx `F0 00 00 66 14` (X-Touch) / `15` (Extender) ; écrans `12`, couleurs `72` ; vumètres `D0` ; faders pitch
  bend 14 bits (`E8` master) ; toucher notes `0x68-0x70`.
- **Au relâchement, la X-Touch ramène le moteur à la dernière position envoyée** -> écho de chaque position reçue.
  Sans toucher détecté (ongle), le moteur reste actif : résistance. Essai 0.8.1 `NAIL_QUIET` (voir `../ETAT.md`).
- Garde-fous des faders (`bridge/faders.py`, ne pas retirer sans raison) : moteur récent (`MOTOR_BUSY` 1,5 s),
  écho moteur, valeur identique, retours LV1 ignorés pendant le toucher + 0,3 s, valeurs périmées 2 s, 1 envoi / 20 ms.
  Master sur LR = lecture seule (Joseph).
- Entrées MIDI winmm exclusives ; X-Touch parfois bloquée après une coupure USB : l'éteindre / la rallumer.

## Choix de Joseph

Extender à GAUCHE ; ◄ CHANNEL ► = sélection ; calibration sur les repères imprimés ; un seul écran 1920x1080, LV1 V17 ;
textes à l'écran du PC en anglais ; stéréo X32 : jamais G et D en même temps ; Flip A/B = User Key seulement ;
overlay : bandeau opaque, pas de transparence en dégradé.

## Publier

Pas de CI. `VERSION` dans `xtouch_lv1_display.py` ET `installer.py` (build.py vérifie), `HISTORIQUE.md`,
`MODE_EMPLOI.html` (à tenir à jour à chaque fonction). `py build.py` -> `dist/Total_Control_LV1_Install.exe` +
`build/stage/xtouch` ; zip de `build/stage/xtouch` sous `XTouch-LV1/` (jamais les réglages / journaux de Joseph) ;
`gh release create vX.Y <fichiers> --notes-file ...` (notes avec SHA-256). Exes de test : `dist\<…>-test`.

## Tester

- Tous les tests : `for t in tests/test_*.py; do py "$t" . || echo "ÉCHEC $t"; done` (fausse LV1 + X-Touch simulée ;
  ils écrivent des journaux dans le dossier). `py tests/test_rendu_reference.py . --maj` après un changement VOULU
  du rendu. Les tests passent `--x32 aucun`.
- Sur le matériel : demander à Joseph un journal court et ciblé (un geste, 5 s d'attente), puis l'analyser.
- L'exe demande l'élévation : essai sans UAC avec `$env:__COMPAT_LAYER='RunAsInvoker'`.

## Index de docs/CONTEXTE_DETAILLE.md

GitHub / releases · Architecture · Étapes faites (couches, sélection, clics LV1, 7 segments, modes de couche, V0.2,
Mixer 2, User Keys, Patch Input B / REALIGN, trim / phase, SoF, Tout quitter, mise à jour) · Refactor (étapes 0-10) ·
Fichiers (installeur, REAPER LV1 portable, logo) · API réseau LV1 · X-Touch · Garde-fous des faders · Choix de Joseph ·
Reste à faire (REAPER : transport, scènes, pistes, Meter Bridge ; PAN ; sends on fader ; F-keys ; jog ; rappel de
pistes / overlay ; FLIP ; gain X32) · Tester.
