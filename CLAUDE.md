# xtouch-lv1-bridge — contexte projet

> Fichier pour Claude Code, exécuté en local sur le PC de Joseph. Il résume ce qui a été établi
> et testé le 14/10/2026 dans une discussion précédente (hors Claude Code), pour ne pas refaire
> les recherches. Tout ce qui est marqué « vérifié » l'a été sur le matériel réel de Joseph.

## GitHub (publié le 16/10/2026)

- Dépôt public `https://github.com/thaleosguest/xtouch-lv1` (branche `master`), release `v0.1` : `Total_Control_LV1_Install.exe`
  + `XTouch-LV1-v0.1.zip` (zip de `build/stage/xtouch`, SANS les réglages ni journaux de Joseph de `dist/XTouch-LV1`).
  Pas de CI : compiler (`py build.py`), zipper, puis `gh release create vX.Y <fichiers> --notes-file ...`.
- Page de profil `thaleosguest/thaleosguest` (README : tableau des 3 produits). Gain Recall garde son nom et son dépôt.
- Ne jamais versionner « Manuel Livetrack 2/ » (manuel d'un tiers), journaux, captures.

## Objectif

Faire de la **Behringer X-Touch + X-Touch Extender** une surface de contrôle pour la **Waves eMotion
LV1**, mieux qu'un FIT Controller : couleurs des canaux sur les écrans, vumètres, faders motorisés,
boutons, et à terme le gain des préamplis **X32** sur les encodeurs (ce que ni le MCU natif ni le FIT
ne font). Projet voisin : `x32-gain-recall` (X/M32 Gain Recall for eMotion LV1, même auteur).

## Architecture décidée

- **Pas de MCU natif de la LV1.** Le script parle **directement** aux deux côtés :
  - à la LV1 par son **API réseau privée** (celle des apps MyFOH/MyMon) ;
  - aux X-Touch en **MIDI USB** (winmm par ctypes), le script est seul propriétaire des ports.
- Dans la LV1, le contrôleur **Mackie doit être retiré** de System Inventory, sinon elle garde les ports MIDI.
- Python 3 **bibliothèque standard uniquement** (rien à installer), Windows. Joseph lance avec `py`.

## État : étapes faites (toutes vérifiées sur le matériel)

- Affichage : nom (haut), fader en dB (bas), couleur du canal (7 couleurs X-Touch), vumètres post-fader ~23 Hz.
- Suivi des couches : usine, custom, mix 80 canaux, Spill.
- **Étape 1** : faders X-Touch -> LV1 (écriture), toucher, écho, garde-fous ; **fader master -> LR** ; calibration.
- **Étape 2** : boutons **Mute** et **Solo** -> LV1, LED synchronisées (y compris changements faits à l'écran).
- **Étape 3 (vérifiée le 14/10, journal 174216)** : ◄ BANK ► (0x2E/0x2F, notes vérifiées le 14/10) = couche
  précédente/suivante **locale** (`LV1State.local`, sauts des couches vides, effacé par `/Notify/CurrentLayer`,
  bloquée pendant un toucher de fader). Test `tests/test_banque.py`.
- **Sélection locale (vérifiée le 14/10, journal 180730, LED OK, BANK OK)** : Select = sélection (`LV1State.selected`, LED Select), ◄ CHANNEL ►
  = canal affiché préc./suiv., banque qui suit au bout de couche. Test `tests/test_selection.py`.
- **Clics simulés dans la LV1** (`lv1_clic.py`, option `--clic-lv1`, classe `LV1Clicker`) : PostMessage
  WM_LBUTTON* à la fenêtre enfant sous le point (souris immobile). **Vérifié le 14/10** : `couche 3` et `tranche 5`
  marchent (PowerShell administrateur obligatoire : LV1 en admin, PrintWindow/clics refusés sinon).
  Géométrie (1920x1080, fractions de la zone client) : couches x 1847, y 537+72k (bord x 1782..1789) ;
  noms des tranches : bande CHERCHÉE à l'écran (sa position change avec Top/Middle/Bottom/Big Fader) dans la colonne
  x 145+96i (3 px du bord, hors texte), y 300..700, couleur exacte du canal (/Notify/TrackColor), hauteur 12..34,
  la plus proche de y 433 ; introuvable = PAS de clic (sinon risque de cliquer un MUTE) ; couleur passée en
  MOT-CLÉ `rgb=` (bug du 15/10 : en 3e position elle tombait dans `method` -> plus aucune sélection cliquée) ; onglet Mixer 1 x 651 / Mixer 2 x 749, y 28, actif (56,201,255).
  Garde-fous avant chaque clic : admin, fenêtre non réduite, onglet lu à l'écran, cadre de case présent.
  Tranche cliquée seulement si la couche LV1 courante la contient ; sélections en rafale regroupées.
  Intégration pont **vérifiée le 14/10** (journal 182527 : 146 clics, 0 refus, LV1 réagit en ~50 ms, max 123).
  Test `tests/test_clic_lv1.py`.
- État mute/solo **initial** lu dans `/Channels` (test `tests/test_etat_initial.py`, LED au démarrage à vérifier sur le matériel).

- **Afficheur 7 segments (16/10, Joseph : « assez d'indices avec l'écran »)** : `time_display` remplace l'option C
  (canal sélectionné / gain / LR) : position de REAPER LV1 (`/time f`, `ReaperLink.time`, `alive()` = réponse < 12 s,
  car à l'arrêt REAPER ne répond qu'à la demande de rafraîchissement) en h.mm.ss.mmm, sinon heure du PC (= horloge LV1).
  Modes sends inchangés (« SE »). Test `tests/test_heure_couche.py`.
- **Notification de couche (16/10)** : `layer_toast` -> `overlay.set_layer(nom, sous-titre)` -> `LayerToast` (Qt) en bas à
  droite de la LV1 (`TOAST_*`, à gauche de la colonne des couches, 2,5 s, traversée par les clics). Couche « par défaut »
  ignorée ; « X-Touch bank » / « empty » / « Mixer 2 » en sous-titre. tk : rien.
- **Boutons de mode de couche (relevés le 16/10, captures 1920x1080, page Mixer)** : 80 canaux : Input (1814, 442),
  Mix (1881, 442) ; 16/32/64 : un seul bouton Factory (1847, 442) ; partout : Custom (1814, 479), Spill (1881, 479).
  Actif = bleu clair. Colonne des couches IDENTIQUE en 64 et 80 (Ch 1-16 à y 515..567, `LAYER_Y0` 537 bon). Mode lisible
  dans `CurrentLV1.dat` (prop 12, `ovv_track_mapping_type` : 0 Factory, 1 CustomL, 3 SpillMd, 4 InptChn, 5 BussChn ;
  `config_info` track_type 0 = nb de canaux). Aucune commande réseau de mode (seul `/Set/SpillButton`, non essayé) :
  changer de mode = clic simulé (`lv1_clic.click_mode`, garde-fou = cadre de la 1re couche, le bouton inactif étant
  sombre). **Touches View (Joseph, 16/10, notes vérifiées journal 175539)** : INPUTS 0x3F = Input (Factory hors 80),
  BUSES 0x43 = Mix, USER 0x45 = Custom ; GROUP 0x4F = Spill ; GLOBAL VIEW 0x33 = onglet All <-> Mixer N (`toggle_all_tab`).
  Input / Mix / Factory = radio ; Custom / Spill = bascules de la LV1 (2e clic -> dernier Input / Mix).
  **Piège (1er essai, 16/10)** : en mode Custom la colonne des couches change d'allure, (1795, 537) devient sombre -> tous
  les clics de mode ET de couche refusés (« bloqué sur USER »). Garde-fou des modes = `mode_guard_why` : rangée Custom / Spill
  (`mode_row_why`, y 479, somme RVB >= 300 : violet de Custom actif = 413 ; 2e essai : seuil 450 -> Custom / Spill actifs
  non reconnus, tout bloqué) OU bord de la 1re couche. **Lenteur (2e essai : 1 à 2 s par clic)** : GetPixel = 15-30 ms par
  point -> `Target.reader(box)` = une capture `screen_rows` (onglet ~30 ms, garde-fou ~35 ms). File des clics : appuis
  répétés regroupés (radio = 1 clic, bascules Custom / Spill / All = parité). Clics de COUCHE : garde-fou = bord gauche des cases (x 1782..1789,
  `layer_edge_why`) : contour gris 160 inactive, bleu / violet (Custom) active ; l'ancien point (1795) était dans l'aperçu
  gris, absent des pages Custom vides (capture Custom du 16/10 : mêmes boutons et mêmes cases, Custom en violet). Voyants `view_leds(mode, onglet)` depuis `LayerModeWatcher` (base relue quand
  `db_stamp` change, onglet lu à l'écran, 0,5 s). SMPTE 0x35 = afficheur timecode REAPER / heure (`ButtonControl.reaper_tc`),
  LED 0x71 = timecode affiché. Notification = nom seul, une fois par couche. Test `tests/test_modes_couche.py`.

- **V0.2 (16/10)** : exe SANS console (`--noconsole`) : `redirect_output_to_log` -> `xtouch_console.txt`, `tray.py`
  (copie de x32-gain-recall) : Mode d'emploi / Dossier des journaux / Quitter (`STOP`, fin propre), une seule instance
  (mutex `Local\XTouchLV1_Bridge`, exe seulement). Voyant GROUP = Spill lu à l'écran (`lv1_clic.spill_on`, vert
  (140, 255, 0)) : la base garde le mode d'avant (4) avec Spill allumé (vérifié, aucune propriété ne change).

- **V0.2.1 (18/10)** : plantage de la 0.2 chez Joseph (fenêtre « Unhandled exception » : « envoi court : There is no
  driver installed on your system », X-Touch disparue) -> `SafeMidi` (sorties : erreur notée dans `lost`, pas d'exception),
  la boucle ferme tout, attend la X-Touch (`open_units(wait=True)`), rouvre sorties + entrées, nouveau `Surface` (tout
  renvoyé). `WinMidiIn.close_all` vide la liste. Test `tests/test_xtouch_perdue.py`.

## Fichiers

- **V0.1 = installeur « Total Control for LV1 » (16/10/2026, ex « LV1 Suite » : nom choisi par Joseph ; « Total Control »
  seul écarté = contrôleur Numark ; « for LV1 » = usage descriptif de la marque Waves, mention « non affilié »)** :
  `py build.py` -> `dist/Total_Control_LV1_Install.exe` (installer.py en
  onefile qui embarque build/stage/{xtouch,gainrecall}). Cases à cocher (demande de Joseph) : XTouch-LV1, REAPER LV1
  (intégration REAPER, sans dossier propre, dépend de XTouch-LV1 : cocher l'un coche l'autre, désinstaller XTouch-LV1
  la retire), X32 Gain Recall (release GitHub GR_TAG v3.0.1 téléchargée par build.py dans build/gainrecall, SHA-256
  comparé au « digest » de l'API ; mode d'emploi = MODE_EMPLOI.md du dépôt x32-gain-recall-workspace au même tag,
  converti en HTML par build.md_to_html ; version.txt). Dossier choisi (Browse…, défaut %LOCALAPPDATA%\Programs,
  dossier non inscriptible refusé) ; étapes expliquées dans la fenêtre selon les cases.
  Un seul exe pour le pont : `--overlay` = processus overlay Qt (xtouch_overlay.py lance `sys.executable --overlay` si
  `sys.frozen`). Fichiers de Joseph à côté de l'exe (HERE / CFG_FILE / FOLDER = dossier de sys.executable si compilé).
  Sans argument : `--clic-lv1 --attendre` (attend les ports USB). `VERSION` dans xtouch_lv1_display.py ET installer.py
  (build.py vérifie). Installé : <dossier>/XTouch-LV1, <dossier>/X32 Gain Recall, <dossier>/Total Control for LV1
  (Uninstall Total Control for LV1.exe = copie de l'installeur, racine = dossier parent ; installed.json). Raccourcis : Bureau + menu Démarrer
  « Total Control for LV1 » (anciens dossier et menu « LV1 Suite » retirés à l'installation : `OLD_SUITES`) (PowerShell WScript.Shell). REAPER fermé obligatoire : reaper-kb.ini (lignes « Custom: lv1_*.lua »
  remplacées, id RS+sha1(chemin)), Scripts/__startup.lua (bloc marqué), surface OSC 8000/9000 si absente. Données de
  Gain Recall (%APPDATA%) jamais touchées ; sa clé Run retirée à la désinstallation si elle vise l'exe installé.
  Test `tests/test_installer.py` ; essai de l'exe : `--silencieux --no-shortcuts --root DIR --reaper DIR [--apps]`.
  Essai du pont sans élévation : `__COMPAT_LAYER=RunAsInvoker`.
- **REAPER LV1 = REAPER portable (16/10, Joseph : « un vrai pack »)** : l'installeur TÉLÉCHARGE
  reaper782_x64-install.exe (REAPER_URL, SHA-256 épinglé + signature Authenticode « Cockos Incorporated » vérifiés ;
  la licence de REAPER n'autorise la redistribution qu'avec un accord de distribution) et l'installe `/S /PORTABLE
  /D=<dossier>\REAPER LV1` (NSIS : /D= en dernier, SANS guillemets ; reaper.ini/kb/extstate sauvegardés et remis lors
  d'une mise à jour). `reaper_portable_config` : kb + __startup.lua (dofile lv1_firstrun.lua puis scènes + vumètres),
  OSC, dockermode1=2 (docker du haut) + extstate dock=257, newprojtmpl = ProjectTemplates\LV1 Multitrack.RPP (écrit
  par l'installeur : un modèle absent = erreur au démarrage), defsavepath = Documents\REAPER LV1 Projects,
  vstpath64/clap/lv2 = dossier vide NoPlugins (Joseph : pas de plugins ; vides = REAPER scanne quand même), carte son
  ([audioconfig], [asiochan]) reprise du REAPER habituel ; anciennes lignes lv1_* retirées du REAPER habituel.
  `reaper/lv1_firstrun.lua` (une fois, ExtState lv1_suite/firstrun — clé gardée malgré le nouveau nom, ~30 cycles defer après le démarrage, noms
  d'actions SANS tenir compte de la casse : « Transport: Show transport docked to top of main window ») : mixage et
  master cachés, transport en haut, règle minutes:secondes. Vérifié le 16/10 sur un REAPER portable (capture). Le pont
  lance REAPER LV1 (`suite.json` écrit par l'installeur, `start_reaper_lv1` par explorer.exe = droits normaux, pas si
  déjà ouvert, `--sans-reaper-lv1`). **Gain Recall lancé aussi (16/10, « sur toutes les options »)** : `find_gain_recall`
  (suite.json "gainrecall" écrit par `installer.gainrecall_link`, dossier voisin, %LOCALAPPDATA%\Programs, à côté du pont,
  clé Run de Gain Recall), `start_gain_recall` : rien si une copie tourne (tasklist ; une 2e instance ouvrirait le
  navigateur), sinon `--at-login` détaché (hérite des droits admin du pont) ; `--sans-gain-recall`, ou `--x32 aucun`.
  Test `tests/test_lancer_gain_recall.py`. Icône rouge `assets/reaper_lv1.ico` (on ne modifie pas reaper.exe : licence).
  Barre de vumètres : bouton SYNC TRACKS (dofile de lv1_sync_tracks.lua, à côté ; vérifié le 16/10 dans le REAPER
  portable : 9 pistes créées). Liste des plugins (reaper-vstplugins64.ini, vstshells, clap) reprise du REAPER habituel
  : REAPER rajoute de lui-même les dossiers VST3 standards à vstpath64 (vu le 16/10), la liste évite le scan.
  Restent : rappel « About » de la version d'évaluation, scan VST3 du dossier commun de Windows au 1er démarrage.
- **Logo (16/10, Joseph : le même que X/M32 Gain Recall, autre couleur)** : `tools/make_icon.py` (repris de
  x32-gain-recall-workspace, bloc de droite bleu LV1 #38C9FF au lieu de l'ambre) -> `assets/logo.svg`, `assets/icon.ico`
  (exe du pont, installeur et sa fenêtre, MODE_EMPLOI.html). Relancer après toute retouche : `py tools/make_icon.py`.
- `xtouch_lv1_display.py` : le programme principal (affichage + faders + master + Mute/Solo).
  Options : `--mixer 1|2`, `--ext-droite` (Extender à gauche par défaut), `--master g:c` (défaut `3:0` = LR,
  `aucun`), `--lecture-seule`, `--no-journal`, `--dry-run`, `--host/--port`, `--main/--ext`, `--seconds`.
  Écrit un journal `xtouch_journal_*.txt` (messages LV1 complets + gestes X-Touch + envois).
- `lv1_probe.py` : sonde LV1 en lecture seule (rapport JSON). Contient l'OSC, le cadrage, la découverte zDNS.
- `xtouch_probe.py` : test X-Touch (texte, couleurs, vumètres) + sortie MIDI winmm + construction des messages.
- `xtouch_calibrer.py` : calibration des faders sur les repères imprimés -> `xtouch_courbe_fader.json`
  (format `[[dB, course 0..1], ..., ["-inf", course]]`). **Le fichier calibré est sur le PC de Joseph : ne pas l'écraser.**
- `xtouch_couleurs.exemple.json` : forçage couleur LV1 (index palette) -> couleur X-Touch.
- `tests/` : tests contre une **fausse LV1** et une X-Touch simulée (voir « Tester »).
- `lv1_capture.py` : décode une capture pcap/pcapng (pktmon) du trafic MyFOH <-> LV1 en messages OSC
  (réassemblage TCP, doublons pktmon). Test : `py tests/test_capture.py .`.
- `LISEZMOI.md` : notes d'installation et de test (français). `MODE_EMPLOI.html` : mode d'emploi de la surface
  (toutes les fonctions, « à confirmer » = non vérifié), livré par l'installeur (raccourci « XTouch-LV1 Manual ») —
  à tenir à jour à chaque nouvelle fonction.

## API réseau LV1 (LV1 V17, ServiceVersion v.17.6.26.456)

Source de départ : module Companion communautaire `bitfocus/companion-module-waves-lv1` (MIT, non affilié à
Waves, rétro-ingénierie). **Non documentée par Waves : à revérifier après chaque mise à jour LV1.**

- Découverte : paquet OSC `/zDNS` en multicast UDP `225.1.1.1:13337` (service `_waveslv113._tcp`, port TCP variable,
  change quand on change la config du mixer).
- Trame TCP : `[taille 4 o BE (OSC seul)][en-tête 8 o 00 00 00 02 00 00 00 00][OSC]`.
- Poignée de main MyFOH : `/handshake i:1 i:-1 i:1` + `/device_name s s` **dans un seul envoi TCP**, réponse `/handshake i:1`.
- Maintien : la LV1 envoie `/ping h i` ~1/s, répondre `/pong` avec les mêmes arguments.
- À la connexion : `/Get/Aux/Tracks`, `/Get/Layers ii 0 0`.
- **Piège (15/10)** : juste après un redémarrage de la LV1 (port TCP changé, nouveau `CurrentSessionID`), elle peut
  accepter la connexion SANS envoyer son état (/Channels, /Notify/Layers, TrackColor) -> plus de couleurs ni de
  banques. `LV1Link` redemande à 5 s puis se reconnecte à 10 s (test `tests/test_reconnexion.py`).
  **État INCOMPLET (journal 230733, 15/10)** : après « /Device/LinkSettings/NewSession », canaux + couleurs puis plus
  rien (ni couches, ni scènes, ni User Keys -> SAVE sans « Store New Scene ») : l'état n'est complet qu'avec /Channels
  ET /Notify/Layers, sinon même redemande / reconnexion.

Messages vérifiés :
- `/Channels` : `i:N` puis 19 args par piste (`s` nom, `i` groupe, `i` canal, `d` fader dB (-144 = -inf), `d`, 12 `i`, `h`, `d`).
  Des 12 entiers : **1er = solo, 2e = mute** (0|1, vérifié le 14/10 : seule différence entre deux
  connexions avant/après mute In 6 + solo In 7). Le 12e vaut 1/2 (mono/stéréo ?), `h` = champ de bits inconnu.
  **Rappel de scène (15/10, journal 155042)** : la LV1 renvoie un état complet ; les nouveaux niveaux de fader n'y
  sont QUE dans /Channels -> fader repris à CHAQUE /Channels (sauf sous le doigt) ; pans / envois relus dans la base
  ~1 s après (non vérifié que la base est déjà à jour).
  C'est la **seule** source de l'état initial : à la connexion, ni `/Notify/Solo` ni mute par piste.
- `/Notify/TrackColor ii i f f f` : groupe, canal, **index palette** (= celui de `CurrentLV1.dat`, ex. 13 = #0FA2AB), RVB 0..1.
- `/Notify/Track/Name ii s T`.
- `/Notify/Meters` : `i:N` puis (groupe, canal, voie, dB float) ; **~23 trames/s** (le « 0,8 Hz » du code Companion est faux),
  134 valeurs/trame ; **post-fader** (confirmé par Joseph).
- `/Notify/Track/Out/Gain ii d T` ; écriture `/Set/Track/Out/Gain ii d` (plage -144..+10).
  **La LV1 RENVOIE nos propres réglages** (~1 message/22 ms pendant un geste), contrairement à la doc du module.
- `/Notify/Track/Out/Mute ii i T` (groupe 13 = groupes de mute) ; écriture `/Set/Track/Out/Mute ii T|F`.
- `/Notify/Solo ii i` ; écriture `/Set/Solo ii i(0|1)`.
- Couches : à chaque clic, la LV1 envoie `/Notify/Layers` (le jeu affiché) PUIS `/Notify/CurrentLayer i:vue i:index`.
  `/Notify/Layers` = vue, flag, nb, puis (nom, n, (groupe, canal)×n) ; (-1,-1) = vide. **Règle retenue (corrigée le 15/10) : adopter
  un jeu SEULEMENT quand il est suivi de /Notify/CurrentLayer pour la même vue** — dans un état complet (connexion,
  rappel de scène, Flip A/B) les pages Custom arrivent en dernier SANS CurrentLayer (journal 155042 : la X-Touch
  sautait sur Custom Page-1). Tests `tests/test_couches_etat.py`, `py tests/rejouer_couches.py . journal`. Le flag (2e nombre) n'indique pas fiablement « custom » ; `/Notify/CustomButton`
  et `/Notify/SpillButton` **ne changent pas** quand on allume Custom/Spill (vérifié) : ne pas s'en servir.
- **Capture MyFOH du 14/10 (myfoh.pcapng)** : changer de couche dans MyFOH n'envoie **rien** à la LV1 ;
  sélectionner un canal envoie seulement `/GetEQ ii` + `/GetGEQ ii` (groupe, canal), la LV1 répond par
  `/Notify/EQ/Band/{Shape,ShapeRange,Q,Freq,Gain,On} ii i …`, `/Notify/EQ/Graphs`, `/Notify/GEQ/*`.
  => couches et sélection sont **locales au client** : pas de commande LV1 attendue, faire pareil dans le pont.
  pktmon sur Wi-Fi écrit des trames 802.11 annoncées Ethernet (géré dans `lv1_capture.py`).
- Groupes : 0 In, 1 Grp, 2 Fx/Aux, 3 LR, 4 C, 5 M, 6 Mtx, 7 Cue, 8 TB, 12 DCA, 25 Mon.
- Aucune commande de **sélection** de canal trouvée. 48 V LV1 : `/SetTrackPhantomState i:0 i:ch i:0 i:on`
  (n'agit pas sur les préamplis X32 de Joseph).

## X-Touch / Extender (USB, mode Mackie Control)

- Ports Windows : « X-Touch » et « X-Touch-Ext » (sortie 3 et 5 chez Joseph, à titre indicatif).
- SysEx : en-tête `F0 00 00 66 <id>`, **id 0x14 X-Touch, 0x15 Extender** (vérifié).
  - Couleurs écran : `<en-tête> 72 c1..c8 F7`, 0 vide, 1 rouge, 2 vert, 3 jaune, 4 bleu, 5 violet, 6 cyan, 7 blanc (vérifié).
  - Texte : `<en-tête> 12 <pos> <ascii> F7`, 7 car./tranche, ligne 2 à 56 (vérifié).
- Vumètres : channel pressure `D0`, valeur = tranche×16 + niveau 0..12 (vérifié ; échelle dB provisoire `METER_STEPS`).
- Faders : pitch bend 14 bits `E0+tranche` (`E8` = master), course complète 0..16380 atteinte (vérifié).
- Toucher : notes `0x68-0x6F` (faders 1-8), `0x70` master, vélocité 127/0 (vérifié).
- **Piège majeur (vérifié)** : au relâchement, la X-Touch ramène le moteur à la **dernière position envoyée par
  l'ordinateur**. Il faut donc **renvoyer chaque position reçue de la main** (écho Mackie), sinon le fader revient
  en arrière et l'ancienne valeur repart vers la LV1 (bug vu et corrigé le 14/10).
- Boutons : Rec 0x00-07, Solo 0x08-0F, Mute 0x10-17, Select 0x18-1F ; LED = note on 127/0 (Mute/Solo vérifiés).
  ◄ BANK ► 0x2E/0x2F, ◄ CHANNEL ► 0x30/0x31, FLIP 0x32 (vérifié, unité X-Touch). Erreur winmm « not enough memory »
  à l'ouverture = port déjà pris (souvent une autre instance du script encore lancée).
- Prise Ethernet des X-Touch = RTP-MIDI (fiches produit). Non testé ; USB pour l'instant.

## Garde-fous des faders (ne pas retirer sans raison)

1. Fader non touché alors que le toucher a déjà été vu = moteur -> ignoré, SEULEMENT si son moteur a reçu une
   commande depuis moins de 1,5 s (`MOTOR_BUSY`) ; moteur au repos = geste sans toucher détecté (ongle, remarque de
   Joseph du 15/10), accepté s'il s'écarte de plus de 80 (`UNTOUCHED_MIN`) ; il déclenche aussi le rappel à l'écran
   (`faders.held`).
0. **Écho immédiat** : la boucle principale ATTEND les messages X-Touch (`events.get(timeout)`, plus de sommeil fixe de
   50 ms) -> l'écho d'un fader part en ~1 ms. Résistance du moteur sentie par Joseph (15/10) à l'ongle et en geste très
   rapide : sans toucher détecté, le moteur de la X-Touch reste actif et vise la dernière position envoyée (pas de
   commande Mackie pour couper les moteurs) ; on ne peut que le faire suivre plus vite.
0. **Vumètres périmés** : `state.meter(g, ch, voie)` rend None si la voie n'est plus reçue depuis 1 s (`METER_STALE`) ;
   piste stéréo remise en mono -> 1 seul vumètre dans l'overlay (remarque de Joseph du 15/10). Suppose que
   /Notify/Meters envoie toutes les voies à chaque trame (134 valeurs constantes) : à revoir si l'overlay montre en
   mono une piste stéréo silencieuse.
0. **Master sur LR = lecture seule** (Joseph, 15/10 : fader critique, monitoring) : `FaderControl.readonly`, rien
   n'est envoyé, `sent_fader` oublié au relâchement -> le moteur reprend la position LV1. En sends on fader (SEND ou
   F-keys), master = master de l'aux, ÉCRITURE (test_sends). Libellé aux (`aux_short`) tiré du groupe/canal, pas du
   nom (Fx 1 renommé « Reverb Hall » affichait « M1 »).
2. Position proche d'une commande moteur récente (< 1,5 s) = écho moteur -> ignorée.
3. Position identique à la dernière connue -> ignorée (évite toute boucle d'écho).
4. Pendant le toucher (+0,3 s) : retours LV1 de cette piste ignorés (`held_tracks`).
5. Pendant 2 s après relâchement : retour LV1 égal à l'ancienne valeur ou à une valeur intermédiaire du geste ignoré
   (`stale`) ; une vraie nouvelle valeur passe tout de suite.
6. Envoi limité à 1 valeur / 20 ms / fader ; mise à jour locale optimiste.

## Choix de Joseph

- Extender **à gauche** de la X-Touch (tranches 1-8 sur l'Extender). Master -> LR (lecture seule).
- Calibration sur les **repères imprimés** de la X-Touch (pas sur l'écran LV1). Un seul fichier de courbe pour tous.
- Vumètres : il préfère ceux de la LV1 (post-fader).
- ◄ CHANNEL ► = **sélection** canal suivant / précédent (pas de décalage de tranches, il n'en veut pas).
- Il a **MyFOH sur sa tablette** : source pour trouver les commandes couche / sélection (`lv1_capture.py` + pktmon).
- **Décision du 15/10/2026** : la LV1 sur **un seul écran en 1920x1080** (comme la LV1 classique) — pas de travail
  de compatibilité multi-écrans / autres résolutions. Développement sur **80 canaux, Mixer 1, LV1 V17** ; 64/32/16 ch
  et Mixer 2 à vérifier plus tard (le suivi des couches est générique ; `--mixer 2` et l'onglet Mixer 2 sont prévus).
- Avancer par petites étapes testées, hors concert ; journal + rapport à chaque test.

## À reprendre (fin de session du 15/10/2026)

- À vérifier sur le matériel : rappel de pistes avec les vrais faders (alignement réglé par Joseph : ext 0-911, xt
  953-1867, master 1884-1920 ; tailles petit / grand), FLIP A/B (LED + pastille), PAN plus sensible,
  afficheur 7 segments option C, Mon 9-16 dans les sends, faders = masters des aux pendant le choix SEND.
- Plus tard : 64/32/16 ch et Mixer 2. Reaper : transport codé (à vérifier avec Reaper).
- Tests : `for t in tests/test_*.py; do py $t .; done` (15 tests, tous OK au 15/10).

## Reste à faire / idées

- **Reaper (prototype décidé « plus tard », 15/10)** : couper la surface en deux — faders/tranches/Extender = LV1,
  bloc transport + navigation = Reaper (virtual soundcheck sur mesure), via l'**OSC de Reaper** (Control/OSC/web,
  UDP, l'OSC de `lv1_probe` suffit). Proposé : ◄◄ ►► ■ ► ● = transport (LED = état renvoyé par Reaper), jog = position,
  SCRUB = scrub, ZOOM + flèches, MARKER + flèches = marqueur préc./suiv., MARKER seul = poser, CLICK = métronome.
  **Jog : choix de Joseph = selon la page LV1** (Channel + fader de plugin en bas -> plugin ; sinon -> Reaper).
  Reaper sur la même machine que la LV1 (pilote SoundGrid) : plausible (TracksLive-FL / LV1-PORT déjà dans le rack),
  à essayer.

- **Transport -> Reaper (codé le 15/10, test `tests/test_reaper.py`, à vérifier avec Reaper)** : `reaper_link.py`
  (OSC UDP, envoi 127.0.0.1:8000, retours écoutés sur 9000, pattern Default.ReaperOSC : /play /stop /record /repeat
  /click déclencheurs, /rewind /forward tenus 1/0, /action i:n) ; `TransportControl` (notes Mackie 0x54-0x65, non
  vérifiées sur la X-Touch) ; Reaper n'envoie son état qu'aux changements -> action 41743 (Refresh all surfaces)
  au démarrage et toutes les 5 s sans réponse (vérifié le 15/10 : état complet reçu) ; MARKER seul = action 40157, flèches = marqueurs 40172/40173 et pistes 40286/40285,
  DROP / REPLACE = In / Out de la boucle (40434 curseur d'édition sur la lecture, puis 40222 / 40223), ZOOM = 1011/1012/40111/40112, jog = 40084/40085 (SCRUB : 40104/40105 au pixel). Jog : LV1Clicker essaie le
  fader de plugin, sinon `jog_fallback` -> Reaper. LED = retours /play /record /repeat /click. `--reaper aucun`.
  Rien en --dry-run (tests) sauf `--reaper` explicite.
- **Scènes LV1 <-> marqueurs Reaper (codé le 15/10, test `tests/test_scenes.py` côté pont ; script Lua et
  /Set/CurSceneIndex à vérifier)** — comme « Create/Recall Scenes » de Tracks Live (manuel fourni par Joseph,
  `Manuel Livetrack 2/`). LV1 : /Notify/SceneList i:N (i, s)×N, /Notify/CurSceneIndex i, /Notify/Scene/Name s ;
  rappel /Set/CurSceneIndex i (module Companion). CurSceneIndex dans un état complet (< 2 s après /Channels) ne compte
  que s'il change. `reaper_scenes.py` (SceneBridge) <-> `reaper/lv1_scenes.lua` (defer) par fichiers
  lv1_to_reaper.txt / reaper_to_lv1.txt (« n°	index	nom ») : enregistrement = marqueur vert (couleur = signature),
  lecture = marqueur franchi (pas de saut > 0,5 s) -> rappel par NOM, arrêt = curseur sur le marqueur. Tracks Live
  lui-même n'est pas pilotable (ni MIDI ni OSC ; raccourcis envoyés refusés, `tracks_live.py`).
- **Synchro des pistes Reaper (a) (codée le 15/10, scripts Lua non essayés)** : le pont écrit `reaper/lv1_tracks.txt`
  (entrées g=0 : canal, nom, r g b, stéréo = 12e entier de /Channels == 2, vérifié) chaque seconde s'il change ;
  `reaper/lv1_sync_tracks.lua` (à la main, OUI = toutes, NON = renommées seulement) crée / met à jour les pistes,
  marquées P_EXT:lv1_in = canal (jamais d'autres pistes touchées, rien supprimé) ; `lv1_scenes.lua` fait suivre nom et
  couleur en direct, et ajoute les pistes manquantes Reaper à l'ARRÊT selon le dernier choix (ProjExtState lv1/sync_mode
  all|named, demande de Joseph). ROUTAGE (b, codé le 15/10, Lua non essayé) : `lv1_db.routing()` lit la table `routes` (clusters 0 = canal,
  section 0 A / 1 B ; 10 = Inputs, 11 = Outputs d'un appareil, index = device.assign ; pilote de ce PC =
  device_daw.is_local -> device.assign, ex. LV1-PORT assign 1) -> rec = canaux du pilote recevant la source de l'entrée
  A, play = lecture du pilote sur l'entrée B ; relu toutes les 5 s (copie 10 ms), ajouté à lv1_tracks.txt ;
  `reaper/lv1_common.lua` (module commun) règle I_RECINPUT (1024+n = paire) et une sortie matérielle marquée
  P_EXT:lv1 (I_DSTCHAN, 1024 = mono), à l'ARRÊT seulement. Test `tests/test_routage.py`.
  **Autre PC pour Reaper (remarque de Joseph du 15/10)** : `--pilote NOM` (nom du pilote dans l'inventaire LV1, ex.
  TracksLive-FL ; `lv1_db.devices()` les liste) au lieu du pilote du PC de la LV1 ; `--dossier-reaper` = dossier
  d'échange (partage réseau contenant aussi les .lua) ; transport : `--reaper IP:8000:9000`.
  **Diagonale B** (Joseph) : patch B = LV1-PORT n pour la n-ième voie ; casse quand un canal passe mono <-> stéréo
  (les lignes de la grille se décalent, vu le 15/10 : P170 X2) -> à refaire ; automatisation par clics dans la page
  Patch : `lv1_patch.py` (16/10) — lit la grille Input B dans l'image de la fenêtre LV1 (PrintWindow, admin ; sinon
  écran), lignes de grille (120,120,120), case (56,201,255), refuse si pas Patch / Input B / grille défilée (curseurs
  d'ascenseurs (1891,230) et (131,1055) = (231,231,231)) ; DÉZOOME d'abord (loupe « − » (148,244)) ; un clic REMPLACE
  la source de la ligne (vérifié par Joseph) -> on clique seulement les cases voulues ; `fix_diagonal()`. Vérifié le
  16/10 (diagonale refaite). Pont : alerte « B PATCH / n OFF » (`diagonal_problems` : lignes = voies, stéréo du
  /Channels, jusqu'à `lv1_db.driver_size`) = touche FLIP de l'overlay avec contour rouge + « FLIP ! » (la barre du
  haut est occupée chez Joseph) ; Joseph refait la diagonale À LA MAIN (un glisser de la 1re case en bas à droite, plus
  rapide) ; **ENTER (0x53, non
  vérifié) = refait la diagonale** (page Patch > Input B ouverte).
- **Reaper façon Tracks Live 2 (16/10, demande de Joseph : pistes + vumètres seulement ; non essayé)** :
  `reaper/lv1_meter_bridge.lua` (gfx, defer, bascule) = « Meter Bridge » de Tracks Live :
  - une colonne par piste visible : n° LV1 (P_EXT:lv1_in + 1), couleur, nom, Track_GetPeakInfo, stéréo = P_EXT:lv1_stereo ;
  - crête 1,5 s, écrêtage mémorisé, R armée ;
  - clic = sélection + 40913 ; losange = tout voir / largeur fixe (molette) ;
  - clic droit : mixer (40078), master (SetMasterTrackVisibility), hauteur des pistes (I_HEIGHTOVERRIDE), LV1 seulement, dock.
  ARM ALL (I_RECARM de toutes les pistes affichées) et MON OFF/ON/AUTO (I_RECMON 0/1/2) à gauche, R de colonne =
  armer une piste (Joseph, 16/10) ; nouvelles pistes de la synchro : désarmées, monitoring OFF (lv1_common.new_track).
  ÉCRAN TACTILE (Joseph) : boutons 70x40 à gauche (ARM ALL, MON, WAVE -/+ = « Peaks: Increase/Decrease peaks display zoom for
  project » (Reaper 7.82) cherchées par nom via kbd_enumerateActions, FIT, MENU), case R 28 px, glisser = défiler, colonnes au relâché, pas d'info-bulle.
  Réglages en ExtState lv1_meter_bridge. Pas de Lua sur le PC : syntaxe non vérifiée hors Reaper.
- **DISPLAY = bascule LV1 <-> Reaper au premier plan, SAVE selon la fenêtre active (codé le 15/10, test
  `tests/test_apps.py`, notes Mackie 0x34 / 0x50 non vérifiées)** — choix du bouton : DISPLAY (NAME/VALUE), FLIP étant
  pris par Flip A/B. `fenetres.py` (front_app, bring : AttachThreadInput + SetForegroundWindow) ; `AppControl` :
  LED DISPLAY = Reaper devant ; SAVE : Reaper -> action 40022 (Save project as), LV1 -> User Key dont la fonction
  contient « Store » (aucune commande réseau de scène à enregistrer dans le module Companion), autre -> rien.
- **Pastille FLIP visible seulement si la LV1 est au premier plan** (Joseph, 15/10 : elle restait devant les autres
  programmes ; rappel de pistes et sends on fader restent affichés LV1 en arrière-plan, choix de Joseph) : processus de la fenêtre de premier plan = celui de la LV1 (fenêtres détachées et
  boîtes de dialogue comprises) ou l'overlay lui-même (réglage).
- **PAN (codé, à tester)** : bouton PAN (0x2A) = encodeurs sur le pan LV1 (exclusif avec TRACK). `/Set/Track/Pan ii d`
  (**-45..+45**, corrigé le 15/10 : envoyé en -1..+1, « tout à gauche » donnait L1 ; interne -1..+1, `LV1_PAN_SCALE`), retour `/Notify/Track/Pan ii d i` (-45..+45) envoyé SEULEMENT aux changements (rien à la connexion, rien dans
  /Channels) -> pan de départ lu dans la base : `lv1_db.py`, copie de CurrentLV1.dat(+wal), snapshot -1, param 436
  PARAM_OUTPUT_BALANCE -45..+45 (absent = centre), chainer_id = object.id (obj_type 0 = entrées). Vérifié le 14/10 :
  In 4 tout à gauche = -45. 1 cran = 3/45 (x2 si crans < 80 ms ; 1/45 jugé pas assez sensible) ; appui encodeur = centre ; pan inconnu (« ? ») = encodeur sans effet ;
  retours LV1 ignorés 0,5 s après un envoi (`pan_hold`). Affichage « L45 / C / R12 », couronne mode 0. Test `tests/test_pan.py`.
- **Sélection sur l'onglet Channel (vérifiée le 15/10, Select et CHANNEL ◄ ►)** : `lv1_clic.Target.on_mixer` = aller-retour d'onglet (clic Mixer N,
  attente qu'il soit affiché, vérif case, clic, retour Channel). Onglets (relevé 14/10) : centres x 652 + 98k
  (Mixer 1, Mixer 2, All, Channel, Show, Patch, Setup), lus en y 14, actif = (56,201,255). La case « ‹ nom › » en
  haut à gauche (nom du canal sélectionné, flèches) existe sur toutes les pages : piste de secours.
- Master : la X-Touch n'a ni écran ni vumètre master ; afficheur 7 segments (2 + 10 car.) et LED SOLO libres.
  **Option C choisie (codée, à tester)** : assignment = n° du canal sélectionné (D1, G3… hors entrées) ; timecode =
  gain X32 du sélectionné (L/R si stéréo) + fader LR (`master_display`, `seg_codes`). CC Mackie non vérifiés :
  timecode 0x40-0x49 (0x40 = à droite), assignment 0x4B/0x4A, point = +0x40 ; LED SOLO note 0x73 (clignote si solo).
- **Sends on fader (vérifié en partie le 15/10 : SEND, liste des aux, Select -> envois OK)** — choix de Joseph : SEND (0x29, non vérifié) puis Select de l'aux ; Mute = envoi
  on/off ; encodeur = pan de l'envoi. `SendControl` : écrans = aux (Fx 1-8 tranches 1-8, Mon 1-8 tranches 9-16, BANK =
  Mon 9-16) ; pendant le choix, faders = masters des aux affichés (demande de Joseph), boutons de tranche bloqués ; ensuite faders = envois
  (`/Set/Aux/Send/Gain iii d`, clé (g, ch, aux), mêmes garde-fous que les pistes), Mute = `/Set/Aux/Send/On iii T|F`
  (LED allumée = envoi coupé), encodeur = `/Set/Aux/Send/Pan iii d` (si connu ; appui = centre), master = master de
  l'aux ; afficheur « SE » + « F3 ». Index aux = ordre de `/Aux/Tracks` (i canal, i groupe, s nom ; Fx = groupe 2,
  Mon = 25). Retours : `/Notify/Aux/Send/Gain iii d T`, `/On iii T T`, `/Pan iii d B`. Rien n'est envoyé à la
  connexion -> niveaux/on de départ lus dans la base (`lv1_db.input_sends`, voir ce fichier). Test `tests/test_sends.py`.
  La LV1 ALLUME d'elle-même un envoi quand on monte son niveau (LED Mute qui s'éteint : normal).
  Indication du mode (choix de Joseph) : afficheur « SE » + « SEL » (choix) / « F3 » + niveau du master de l'aux ;
  ligne du bas = aux + niveau d'envoi « F1 -12 » (`send_label`) — le NÉGATIF (couleur + 0x20) n'a aucun effet en
  mode Mackie (essai du 15/10), ne pas y revenir ;
  écran du PC : **Qt** (`xtouch_overlay_qt.py`, processus à part piloté en JSON sur stdin, style X/M32 Gain Recall
  v3 : #111213 / #3a3e43 / #e9edf0, Segoe UI gras, pastille rouge 48 V en dégradé, liseré couleur de l'aux,
  `Qt.WindowTransparentForInput`) si PySide6 est là (6.12 chez Joseph), sinon repli tkinter (`xtouch_overlay.py`) : bandeau 2,5 s « SEND ON FADER : FX 1  <nom de la piste> » puis
  cadre rouge clignotant doucement autour de la fenêtre LV1, fenêtres traversées par les clics. Piège : une fenêtre
  WS_EX_LAYERED sans attribut -alpha n'est PAS dessinée. Option `--sans-cadre`. Textes à l'écran du PC : en ANGLAIS (demande de Joseph).
- Fader : sous -60 dB, descente continue jusqu'à -144 (plus de saut -144 -> -78) — vérifié le 15/10.
- **F1..F8 -> User Keys 1..8 de la LV1 (vérifié le 15/10)** — demande de Joseph (accès rapide aux envois en live) :
  `/Set/UserKey i:k T` puis `F` (comme MyFOH). Fonctions lues dans `/Notify/UserKeyInfo i s s i` (n°, nom court, fonction,
  assignée), envoyées à la connexion. Si la fonction est « Flip Sends: MX1: <aux> » : la X-Touch passe AUSSI en sends
  on fader vers cet aux (`flip_target`, `SendControl.on_fkey`), LED de la touche F allumée ; 2e appui (ou SEND) =
  User Key à nouveau + retour normal. Notes F1..F8 0x36..0x3D (Mackie, non vérifiées). Non vérifié : qu'un 2e appui
  sur la User Key ramène bien la LV1 ; si Joseph quitte le Flip sur l'écran LV1, le pont ne le voit pas (pas de
  notification connue). Test `tests/test_fkeys.py`.
- **Jog wheel -> potard de plugin (vérifié le 15/10 avec la X-Touch)** — demande de Joseph : page Channel, un potard de plugin touché
  affiche son réglage en fader horizontal en bas (piste grise (54,54,54) x 690..1572, y 1040..1049, poignée claire).
  La MOLETTE souris dessus le règle (essai de Joseph ; le clavier non). Jog = CC 0x3C relatif (Mackie, non vérifié),
  -> `LV1Clicker.jog` (crans regroupés) -> `lv1_clic.jog_bottom_fader` : admin, onglet Channel lu, piste présente,
  puis WM_MOUSEWHEEL à la fenêtre (souris immobile) ou `--jog-methode souris` (pointeur déplacé un instant).
  Outil d'essai : `py lv1_clic.py molette 5` / `-5` (`--methode souris`).
  Vérifié le 15/10 : `py lv1_clic.py molette 5` (message WM_MOUSEWHEEL, souris immobile) fait bouger le réglage.
- **Bouton SOLO** (0x5A, Mackie, non vérifié) : LED allumée si un solo est actif ; appui = `/ClearAllSolo` (sans argument,
  commande du module Companion). Test dans `tests/test_buttons.py`.
- `HISTORIQUE.md` : journal lisible du développement (à tenir à jour à chaque étape).
- **Rappel de pistes à l'écran (codé, à tester)** — demande de Joseph (photo du 15/10 : X-Touch + Extender plus larges que
  l'écran, tranches non alignées). Toucher un fader -> bandeau Qt sur la zone des faders LV1 (y 745..1076/1080),
  17 cases ALIGNÉES SUR LA SURFACE : 8 (Extender) de 0 à `split` (0,49 de la largeur, mesuré sur la photo), 8 + master
  à droite. Case : bandeau couleur + nom, valeur (fader ou envoi), vumètre vertical, contour blanc = fader touché ;
  mode sends : pastille « SEND > FX 1 ». Reste 0,5 s après le relâchement (`RECALL_HOLD`), 20 rafraîchissements/s.
  Fondu d'apparition / disparition (~0,2 s, sans dépasser la cible : bug d'oscillation 84 % <-> 100 % corrigé) ;
  bandeau ENTIÈREMENT OPAQUE (dégradé de transparence essayé puis refusé par Joseph). Case : bandeau couleur + nom,
  pastilles SEND > aux / OFF / MUTE / SOLO / 48V, gain X32 (côté L/R en stéréo) + pan, petit fader avec repères
  (courbe calibrée), 1 ou 2 vumètres (stéréo), valeur en grand ; contour jaune = sélection, blanc = fader touché.
  Case de moins de 70 px (`COMPACT_W`, ex. master réglé à 36 px par Joseph) : version compacte = vumètres sur toute
  la largeur, capuchon du fader PAR-DESSUS, nom sur 3 lettres, « M » rouge si mute, valeur en petit.
  **Grande case = tranche LV1 au plus près (15/10, demande de Joseph)** : `paint_lv1` — bouton de pan + arc bleu
  (pan de l'envoi en sends), MUTE (rouge), valeur #38c9ff sur #363636, niveau du vumètre, fader posé SUR le vumètre
  (#8cff00), échelle LV1 à droite, bandeau couleur + nom + n°, bouton casque = solo (jaune), « Send Level » vertical
  en sends ; couleurs relevées sur ses captures (LV1_*). Gain X32 / 48V / pastilles retirés de la grande case.
  Options d'affichage (`RECALL_OPTIONS`, interrupteurs dans le réglage ADJUST, `options` de xtouch_ecran.json) :
  bouton vert SELECT (défaut) / cadre jaune + fond gris de la LV1, capuchon transparent, POINT BLEU au-dessus de la
  tranche touchée (bande transparente DOT_PAD au-dessus du bandeau ; les flèches ont été refusées ; point et contour =
  doigt posé SEULEMENT, `FaderControl.touch_display`, envoi immédiat au changement), contour
  blanc. Master étroit au même style (`paint_compact`, `lv1_meter`, `lv1_cap`).
  **Deux hauteurs mémorisées** (demande de Joseph, futur bouton « agrandir / rapetisser » de l'appli) : `taille`
  petit | grand dans `xtouch_ecran.json`, chacune avec son [y0, y1] ; `--taille petit|grand` bascule (à chaud),
  `--reglage` règle le profil en cours. Pendant le CHOIX de l'aux (SEND), l'overlay montre les aux de la page (comme les écrans X-Touch). **Boutons à l'écran** (`RecallButtons`, demande de Joseph) : ▲ LARGE / ▼ SMALL + ⚙ ADJUST,
  en bas à gauche (BTN_RECT x 38, y 862, 54x134 sur 1920x1080, zone rouge de Joseph ; remontés au-dessus du bandeau
  en grand), FONT PARTIE DU BANDEAU (même fondu, disparaissent avec lui ; on tient un fader et on appuie au tactile),
  seule fenêtre cliquable (sans focus) ; ADJUST ouvre
  `RecallSetup` dans le même processus (`on_done`). Bandeau < 140 px (`MINI_H`) = présentation « petit » : couleur + nom en haut,
  valeur + diode(s) de vumètre (verte / ambre > -12 / rouge > -3, éteinte < -50 ; 2 en stéréo), « M » si mute.
  Réglage de Joseph : petit = 1017-1076, grand = 745-1076, master 1884-1920 (trop étroit pour la valeur en petit).
  **Réglage à la main** : `py xtouch_overlay_qt.py --reglage` (3 blocs Extender 8 / X-Touch 8 / master 1, bords =
  étirer, intérieur = déplacer, haut/bas = hauteur ; Entrée = enregistrer, Échap = annuler) -> `xtouch_ecran.json`
  ({ext, xt, master: [x0, x1] sur 1920, y0, y1 sur 1080}), relu à chaud par le pont. `recall_payload`, `StripRecall`,
  `RecallSetup`.
- **FLIP (0x32) = Flip A/B (codé, à tester)** : appui sur la User Key dont la fonction contient « Flip AB » (Joseph :
  User Key 16 = « FlipAB » / « Flip AB Input channel »). Pas de commande réseau A/B connue. **À chaque Flip A/B, la LV1
  renvoie TOUT son état** (comme une connexion : /Channels, couches, couleurs, User Keys…) et Joseph voit un message
  sur la LV1. LED FLIP = entrées sur B, lue dans la base (`lv1_db.input_ab`, param 0, 1 = B) au démarrage et ~1 s
  après chaque /Channels (`state.channels_at`). Test dans `tests/test_fkeys.py`.
  Le Flip A/B de la LV1 demande une CONFIRMATION à l'écran (Joseph clique lui-même, ok pour lui).
  **Indicateur A/B à l'écran** (Qt, demande de Joseph) : pastille qui RECOUVRE la User Key « FlipAB » (rangée des User
  Keys, visible sur toutes les pages ; touche k = x 145+96k..229+96k, y 62..90) : « FLIP » + A bleu (56,201,255) /
  B rouge 48 V, TOUJOURS OPAQUE (la respiration en semi-transparence a été refusée) ; recopie la touche au pixel
  (contour 160 x 144+96k..230+96k, y 61..90, fond de rangée (71,71,71), débord 2 px) ; clics traversants (`AbBadge`).
- Sens LV1 -> X-Touch de la sélection (vérifié le 14/10, journal 185026) : `LV1SelectionWatcher` (avec --clic-lv1) lit le liseré
  jaune (255,242,0) y 98-102/1080, x 143+96i (`lv1_clic.selected_strip`, sans admin) toutes les 0,15 s ; ne réagit
  qu'aux changements. Test `tests/test_selection_lv1.py`.
- **Étape 4 (vérifiée le 14/10, journal 185026 : gain, stéréo L/R, 48 V tenu, appuis brefs ignorés)** : gain/48 V X32 **via x32-gain-recall** (choix de Joseph : pas d'OSC direct),
  `xgr_link.py` (GET /api/state 2x/s : gains, phantom, exp_map idx->EXP, lv1_sources canal LV1 1-based->[EXP] ;
  POST /api/gain {idx, db}, /api/phantom {idx, on} ; localhost sans code ; -12..+60 dB pas 0,5).
  `GainControl` : **TRACK** (0x28, vérifié) bascule le mode gain ; encodeurs CC 0x10-17 relatifs (bit 6 = sens),
  couronnes CC 0x30-37 (mode 2) ; ligne du bas = gain ; stéréo = 2 préamplis ensemble ; **Rec tenu 1 s = 48 V**
  (appui bref ignoré, protection rubans), LED Rec = 48 V réel. Option `--x32 URL|aucun`. Test `tests/test_gain.py`.
  Gain vérifié sur le matériel le 14/10 (journal 183905 : TRACK + encodeur 1, 45 crans OK).
  **Stéréo, règle de Joseph : JAMAIS G et D en même temps (gain comme 48 V).** Appui sur l'encodeur (note 0x20+n,
  vérifiée) = L <-> R (défaut L, remis à L en quittant TRACK) ; Rec tenu agit sur le côté choisi ; LED Rec et
  couronne = côté choisi ; écran « L+12.0 » / « R+11.5 » (`gain_label`).
  Les autres tests passent `--x32 aucun` (sinon ils liraient le vrai Gain Recall sur 8032).
- **Étape 4** : encodeurs -> **gain X32** (OSC UDP 10023, via la logique de `x32-gain-recall` : table EXP -> canal LV1),
  48 V X32 sur Rec ?
- Select : pas de commande LV1 connue. Piste : `/Notify/SelectedLinkTrackID i:vue i i` et `/Notify/LinkButton`
  vus à la connexion (non décodés). Le module Companion (29/09/2026) n'a aucune commande de couche ni de sélection ;
  il a `/Set/UserKey i:k T` puis `F` (appui momentané) et `/Set/SpillButton ii i`.
- Écran master / vumètre master, couleur forcée par fichier, échelle des vumètres à ajuster.
- Ethernet (RTP-MIDI), exe PyInstaller, intégration éventuelle dans `x32-gain-recall` (décision non prise).

## Tester

- Simulation (Linux ou Windows, sans matériel) : `py tests/test_faders.py .` (options `--echo`, `--notouch`,
  `--snapback`), `py tests/test_master.py .`, `py tests/test_buttons.py .`, `py tests/test_etat_initial.py . [journal]`.
  `py tests/analyser_channels.py journal.txt` : dump des 19 champs de `/Channels`. Attention : les tests écrivent
  aussi des journaux `xtouch_journal_*` (pistes « Ch1/Kick/Snare ») dans le dossier. Ils lancent une fausse LV1 locale,
  injectent des messages X-Touch dans `xtouch_lv1_display.EVENTS` et vérifient les `/Set` envoyés et les moteurs/LED.
- Rejouer un journal réel : analyser `/Notify/Layers` + `/Notify/CurrentLayer` avec `handle()` + `build_frame()`
  (méthode utilisée pour valider le suivi des couches).
- Sur le matériel : demander à Joseph un journal court et ciblé (un geste, 5 s d'attente).
