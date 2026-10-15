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
| Bouton **SOLO** : allumé si un solo est actif ; appui = efface tous les solos | codé |
| Bouton **FLIP** = Flip A/B (via la User Key « Flip AB »), LED = entrées sur B | codé |
| Indicateur **FLIP A / FLIP B** posé sur la touche FlipAB de la LV1 (Qt) | codé |

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
