# Historique du développement — X-Touch + Extender pour eMotion LV1

Journal lisible de ce qui a été construit, dans l'ordre, et de ce qui a été vérifié sur le matériel.
Le détail technique (messages, pièges, géométrie) est dans `CLAUDE.md` ; le mode d'emploi dans `LISEZMOI.md`.
Chaque ligne correspond à un ou plusieurs commits git (`git log` pour le détail).

## Avant Claude Code (14/10, discussion précédente)

- Affichage : noms, couleurs, fader en dB, vumètres post-fader, suivi des couches (usine, custom, 80 ch, Spill).
- Faders X-Touch -> LV1 avec toucher, écho Mackie et garde-fous ; fader master -> LR ; calibration sur les repères.
- Mute et Solo -> LV1, LED synchronisées.

## 14/10 — reprise avec Claude Code

| Fonction | Résultat |
|---|---|
| État mute/solo **au démarrage** (2 des 12 entiers de `/Channels`) | vérifié |
| **BANK ◄ ►** : couche précédente / suivante sur la X-Touch | vérifié |
| Capture du trafic **MyFOH** (pktmon + `lv1_capture.py`) : MyFOH ne change ni couche ni sélection de la LV1 | conclusion |
| **Sélection** : Select, CHANNEL ◄ ► (la banque suit), LED Select | vérifié |
| **Clics simulés** (`--clic-lv1`) : la LV1 suit BANK et la sélection | vérifié (146 clics, 0 raté) |
| Sélection faite **sur l'écran LV1** -> LED Select de la X-Touch (liseré jaune lu à l'écran) | vérifié |
| **Gain X32** sur les encodeurs (TRACK) et **48 V** sur Rec tenu 1 s, via X/M32 Gain Recall | vérifié |
| Canaux **stéréo** : jamais G et D en même temps ; appui encodeur = L / R | vérifié |
| **PAN** sur les encodeurs (pan de départ lu dans la base LV1) | codé |
| **Afficheur 7 segments** : canal sélectionné + gain X32, fader LR ; LED SOLO | codé |
| Clic de sélection **sûr** (bande du nom cherchée à sa couleur, modes Top / Middle / Bottom) | vérifié |

## 15/10

| Fonction | Résultat |
|---|---|
| Courbe de fader calibrée récupérée de l'ancien dossier de test | vérifié |
| **Reconnexion** si la LV1 (qui démarre) n'envoie pas son état | codé |
| Fader : descente continue sous -60 dB jusqu'à -∞ (plus de saut -144 -> -78) | vérifié |
| **Sends on fader** : SEND, choix de l'aux par Select, faders = envois, Mute = envoi on/off, encodeur = pan d'envoi | vérifié |
| Pendant le choix de l'aux : faders = masters des aux | codé |
| Mode sends visible : afficheur « SE F3 », ligne du bas « F1 -12 », bandeau puis cadre rouge **Qt** (style Gain Recall v3) | vérifié |
| **F1..F8 = User Keys 1..8** de la LV1 ; un Flip Sends met aussi la X-Touch en sends | vérifié |
| Sélection **depuis l'onglet Channel** (aller-retour d'onglet) | vérifié |
| **Jog wheel** = potard de plugin sélectionné (page Channel), par crans de molette | vérifié |
| Bouton **SOLO** : allumé si un solo est actif ; appui = efface tous les solos | vérifié |
| Bouton **FLIP** = Flip A/B (via la User Key « Flip AB »), LED = entrées sur B | codé |
| Indicateur **FLIP A / FLIP B** posé sur la touche FlipAB de la LV1 (Qt, opaque) | codé |
| **Rappel de pistes** à l'écran, aligné sur la X-Touch + Extender, au toucher d'un fader : couleur, nom, fader,
  vumètres (2 en stéréo), mute / solo / 48V / gain / pan, opaque, fondu ; réglage des blocs à la main ; master compact | codé |

## Décisions de Joseph

- LV1 sur **un seul écran 1920x1080** ; développement sur **80 canaux, Mixer 1, LV1 V17**.
- Le gain X32 passe par **X/M32 Gain Recall** (pas d'OSC direct depuis le pont).
- Textes à l'écran du PC **en anglais**.
- Extender **à gauche** ; master -> LR ; vumètres post-fader de la LV1.

## Pistes en attente

- 64 / 32 / 16 canaux et Mixer 2 : à vérifier.
- Mon 9-16 dans les sends (correspondance de la base supposée).
- Contrôle de **Reaper** (transport, jog, zoom, scrub, marqueurs) pour un virtual soundcheck : prévu plus tard,
  par l'OSC de Reaper ; jog partagé selon la page LV1 (Channel + plugin -> plugin, sinon Reaper).

## 16/10/2026 : V0.1

- Reaper façon Tracks Live 2 : barre de vumètres tactile (`reaper/lv1_meter_bridge.lua`), ARM ALL, monitoring
  OFF/ON/AUTO, hauteur des formes d'onde.
- **V0.1 compilée** : `py build.py` -> `dist/XTouch-LV1/XTouch-LV1.exe` (un seul exe, overlay compris, droits
  administrateur, attend les X-Touch), zip à donner `dist/XTouch-LV1-v0.1.zip`.
- Installeur **LV1 Suite** (`dist/LV1_Suite_Install.exe`) : XTouch-LV1, REAPER LV1 et X32 Gain Recall v3.0.0 au
  choix, dossier au choix, étapes expliquées, désinstalleur ; mode d'emploi de la surface (`MODE_EMPLOI.html`).
- REAPER LV1 : REAPER portable téléchargé sur reaper.fm par l'installeur, réglé façon Tracks Live, lancé par
  XTouch-LV1 ; icône rouge ; installeur bilingue.
- Pack renommé **Total Control for LV1** (`dist/Total_Control_LV1_Install.exe`) ; une installation « LV1 Suite »
  est reprise (versions installées) et son dossier / menu Démarrer retirés.

## 16/10/2026 (suite)

- Afficheur 7 segments : position de REAPER LV1, sinon l'heure (plus le canal sélectionné).
- Notification « LAYER » en bas à droite de la LV1 à chaque changement de couche.
- Boutons Input / Mix / Factory / Custom / Spill de la LV1 relevés (80 et 64 canaux).
- Touches INPUTS / BUSES / USER / GLOBAL VIEW = Input (Factory) / Mix / Custom / Spill de la LV1, voyants selon le mode.
