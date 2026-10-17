# Tests X-Touch + LV1 (USB)

Deux tests indépendants, Python 3 standard (rien à installer), à lancer sur le PC de la LV1.
Les deux écrivent un rapport `.json` dans ce dossier : c'est ce fichier qu'il faut m'envoyer.


## Installation : Total Control for LV1 (V0.1, plug and play)

**`Total_Control_LV1_Install.exe`** installe, au choix (cases à cocher) :
- **XTouch-LV1** v0.1 : le pont X-Touch + Extender <-> LV1 ;
- **REAPER LV1** : un REAPER 7.82 **portable à part** (ton REAPER habituel n'est pas touché), téléchargé sur reaper.fm
  pendant l'installation (installeur officiel Cockos vérifié : empreinte + signature), réglé façon Tracks Live :
  transport en haut, barre de vumètres, règle en minutes:secondes, table de mixage et master cachés, scènes <->
  marqueurs, synchro des pistes, surface OSC du transport, pas de plugins (tout passe par la LV1), carte son reprise de
  ton REAPER, projets dans `Documents\REAPER LV1 Projects` (jamais effacés). Raccourci à icône rouge. **XTouch-LV1 le
  lance tout seul** (sauf `--sans-reaper-lv1`), ainsi que X/M32 Gain Recall s'il le trouve (installé par le pack, dans
  `%LOCALAPPDATA%\Programs`, à côté de XTouch-LV1 ou via « Lancer avec Windows » ; sauf `--sans-gain-recall`). Il a besoin de XTouch-LV1 (le cocher coche XTouch-LV1). REAPER est un
  logiciel Cockos : essai 60 jours, puis licence REAPER (Help > About REAPER pour entrer sa clé) ;
- **X32 Gain Recall** v3.0.1 (release GitHub).

Fermer REAPER (et les programmes à mettre à jour), double-clic, cocher, choisir le dossier si besoin (**Browse…** ;
défaut `%LOCALAPPDATA%\Programs`), lire les étapes affichées, **Install**.
- XTouch-LV1 : une réinstallation garde la calibration des faders, le réglage de l'écran et les journaux ; les réglages
  posés à côté de l'installeur (ou dans `dist\XTouch-LV1`) sont repris s'il n'en a pas.
- REAPER LV1 : scripts déclarés (anciens chemins remplacés), scènes + barre de vumètres lancées au démarrage de REAPER,
  surface OSC 8000/9000 ajoutée si elle manque.
- X32 Gain Recall : ses scènes et réglages restent dans `%APPDATA%\X32 Gain Recall` (jamais touchés). Si « Lancer avec
  Windows » était coché avec une autre copie de l'exe, le recocher dans l'appli.
- Raccourcis : Bureau (un par programme) et menu Démarrer > **Total Control for LV1** (programmes, modes d'emploi, désinstalleur).
- **Désinstaller** : menu Démarrer > Total Control for LV1 > Uninstall Total Control for LV1 (cases à cocher aussi).

**Lancer XTouch-LV1** : raccourci XTouch-LV1. Windows demande les droits administrateur (pour que la LV1 suive BANK et
la sélection). Pas de fenêtre noire : icône près de l'horloge (clic droit > Quitter XTouch-LV1 ; messages dans `xtouch_console.txt`) ;
avis de mise à jour (bulle + entrée du menu) quand une nouvelle version est publiée sur GitHub. À la fin de
l'installation, le bouton **Lancer XTouch-LV1** le démarre directement. Les X-Touch peuvent être branchées après :
il les attend. Il trouve la LV1 tout seul et se reconnecte si elle redémarre. Dans la LV1 : retirer le contrôleur
Mackie de System Inventory.

Options : sans argument = `--clic-lv1 --attendre` ; les options de `xtouch_lv1_display.py` restent possibles dans un
raccourci (ex. `XTouch-LV1.exe --clic-lv1 --attendre --pilote TracksLive-FL`). Réglage du rappel de pistes : bouton
ADJUST à l'écran, ou `XTouch-LV1.exe --overlay --reglage`.

**Fabriquer l'installeur** (développement) : `py build.py` -> `dist\Total_Control_LV1_Install.exe` (PyInstaller + PySide6 ;
Gain Recall = release GitHub v3.0.1, téléchargée une fois dans `build\gainrecall`, empreinte vérifiée ;
`--gain-recall CHEMIN.exe` = un exe local ; `--sans-gain-recall`).

## Test 1 : la LV1 donne-t-elle les couleurs et les vumètres ?

`lv1_probe.py` se connecte à la LV1 comme le ferait l'app MyFOH, **en lecture seule**.

1. Lance la LV1 normalement.
2. Dans un terminal, dans ce dossier :
   ```
   py lv1_probe.py
   ```
3. Pendant les 60 s d'écoute : envoie du signal sur quelques entrées, change la couleur
   d'un ou deux canaux, renomme un canal.

Ce qu'on mesure : la cadence réelle des vumètres (le module Companion note environ
0,8 trame par seconde, à vérifier), le format des couleurs, et toutes les adresses que la LV1 envoie.

Si la poignée de main échoue : `py lv1_probe.py --style mymon`.
Si la LV1 n'est pas trouvée : regarde son port dans MyRemote ControlPanel, puis
`py lv1_probe.py --host 127.0.0.1 --port <port>`.

## Test 2 : la X-Touch affiche-t-elle couleurs et vumètres ?

`xtouch_probe.py` envoie du texte, des couleurs et des vumètres, puis te demande ce que tu as vu.

1. X-Touch et Extender branchées en USB, **en mode Mackie Control (MC)**.
2. La LV1 ne doit pas tenir les ports MIDI : ferme-la, ou retire le contrôleur Mackie
   dans System Inventory, le temps du test.
3. ```
   py xtouch_probe.py --list     # pour voir les ports
   py xtouch_probe.py            # le test (réponds o / n / ? à chaque étape)
   ```
   Si les ports ne sont pas trouvés tout seuls : `py xtouch_probe.py --main 1 --ext 2`.

Les deux tests sont indépendants : on peut faire le test 1 avec la LV1 ouverte, puis le test 2 LV1 fermée.

## Prototype : la LV1 affichée sur les X-Touch

`xtouch_lv1_display.py` suit la couche affichée dans la LV1 et montre, sur les 16 tranches :
nom du canal (haut), fader en dB (bas), couleur du canal, vumètre post-fader.
**Lecture seule** : rien n'est réglé dans la LV1, les faders et boutons ne font rien pour l'instant.

1. Dans la LV1 : System Inventory, retire le contrôleur Mackie (sinon la LV1 garde les ports MIDI).
2. X-Touch et Extender en mode Mackie Control, en USB.
3. ```
   py xtouch_lv1_display.py              # suit Mixer 1
   py xtouch_lv1_display.py --mixer 2    # Mixer 2 imposé (défaut : --mixer auto = l'onglet affiché)
   py xtouch_lv1_display.py --ext-droite # si l'Extender est à DROITE (par défaut : à gauche)
   ```
4. Change de couche, de couleur, de nom, bouge un fader dans la LV1 : les X-Touch doivent suivre.
   Ctrl+C pour arrêter.

Couleurs : la X-Touch n'en a que 7. Le choix se fait par la teinte ; pour forcer une couleur,
copie `xtouch_couleurs.exemple.json` en `xtouch_couleurs.json` et modifie-le.

Les faders motorisés se placent sur les faders LV1 (courbe provisoire : haut = +10 dB, 0 dB aux 3/4).

### Séquence de test (le journal `xtouch_journal_*.txt` enregistre tout)

Fais ces gestes dans l'ordre, en laissant 3 secondes entre chacun, puis Ctrl+C et envoie-moi le journal :

1. Couches d'usine : Ch 1-16, puis Ch 17-32, puis une couche Groups ou Fx.
2. Allume **Custom**, choisis Page-1 puis Page-2, éteins Custom.
3. Sélectionne un Link (ou DCA) et allume **Spill**, puis éteins-le.
4. Passe en config **80 canaux**, montre une couche Input puis une couche Mix (Groups, Mon…).
5. Bouge un fader dans la LV1.

Note pour chaque étape ce que la X-Touch affiche (juste ou faux).


## Étape 1 : les faders de la X-Touch pilotent la LV1

Même script, même lancement : `py xtouch_lv1_display.py`.
Bouger un fader de la X-Touch règle maintenant le fader du canal dans la LV1.
`py xtouch_lv1_display.py --lecture-seule` revient à l'affichage seul (rien n'est envoyé).

**Prudence** : à tester hors concert. Les boutons et encodeurs ne font toujours rien.

### À tester et à me dire
1. La console affiche-t-elle « Toucher des faders détecté » quand tu poses le doigt ?
2. Le fader de la LV1 suit-il la X-Touch, sans à-coups ?
3. Pendant que tu tiens un fader, le bouger sur l'écran de la LV1 : le moteur doit rester sous ton doigt.
   Après l'avoir lâché, il doit rejoindre la valeur de l'écran.
4. Courbe : mets le fader de la X-Touch sur les repères imprimés **0**, **-10**, **-20**, **-40** et tout en
   haut, et note la valeur dB que montre la LV1 pour chacun.
5. Appuie sur quelques boutons (Mute, Solo, Select, banques) : ils sont notés dans le journal pour l'étape 2.

Envoie-moi le journal `xtouch_journal_*.txt` et tes relevés de courbe.

### Fader master (9e fader de la X-Touch)
Il **suit** le **LR** de la LV1 par défaut, en **lecture seule** : le toucher ou le bouger n'envoie rien, le moteur
reprend la position de la LV1 au relâchement (fader critique, il sert au monitoring).
En **sends on fader** (SEND ou F1-F8), il passe sur le **master de l'aux** choisi, et là il le **règle**.
`py xtouch_lv1_display.py --master 5:0` pour une autre piste (groupe:canal ; 3 = LR, 4 = C, 5 = M, 1 = groupes…),
`--master aucun` pour le désactiver.

Un fader monté **sans toucher détecté** (ongle, gant…) règle quand même la LV1, et fait apparaître le rappel à
l'écran (sauf si son moteur vient de bouger : c'est alors le moteur, pas la main).

## Calibration des faders

`py xtouch_calibrer.py` (ferme d'abord xtouch_lv1_display.py, la LV1 n'est pas nécessaire).

1. Pose le fader 1 sur le repère imprimé le plus haut, tape sa valeur (ex. `10`), Entrée.
2. Recommence pour chaque repère imprimé (5, 0, -5, -10, -20, -30, -40, -60…).
   Pour le repère ∞ (moins l'infini), tape `-inf` : toute position en dessous vaudra -∞.
3. Tape `fin`. La courbe est enregistrée dans `xtouch_courbe_fader.json`.
4. Le moteur pose ensuite le fader sur chaque repère : vérifie qu'il tombe pile.

La courbe vaut pour les 16 faders et le master. Si un fader précis est décalé : `py xtouch_calibrer.py --fader 9`
(master) ou un autre numéro, mais un seul fichier de courbe est utilisé pour l'instant.

## Étape 2 : boutons Mute et Solo

Même script. **Mute** et **Solo** de chaque tranche pilotent la LV1 ; leurs LED suivent l'état réel
(un mute fait sur l'écran allume aussi la LED). **Rec** et **Select** n'ont pas encore de fonction
(ils sont notés dans le journal). `--lecture-seule` désactive aussi les boutons.

L'état mute/solo **de départ** est lu à la connexion : les LED sont justes dès le lancement.

### Test
1. Appuie sur Mute et Solo de quelques tranches, puis mute / démute depuis l'écran de la LV1.
2. Envoie-moi le journal.

## Étape 3 : banques (◄ BANK ►)

Même script. **◄ BANK ►** sur la X-Touch passe à la couche précédente / suivante du jeu affiché
(Ch 1-16 -> Ch 17-32 -> …), en sautant les couches vides. C'est **local à la X-Touch** : l'écran de la
LV1 ne change pas (aucune commande LV1 connue pour ça). La console affiche alors « (banque X-Touch) ».
Un clic de couche sur l'écran de la LV1 reprend la main. Banque bloquée tant qu'un fader est touché.
Fonctionne aussi en `--lecture-seule` (rien n'est envoyé à la LV1).

### Test
1. Lance `py xtouch_lv1_display.py`, appuie 3 fois sur BANK ►, puis 1 fois sur BANK ◄.
   Les noms et faders doivent suivre (Ch 17-32, Ch 33-48, …).
2. Clique une couche sur l'écran de la LV1 : la X-Touch doit la reprendre.
3. Appuie aussi une fois sur ◄ CHANNEL ► et sur FLIP (pas encore de fonction, notés dans le journal).
4. Envoie-moi le journal.

## Sélection (Select, ◄ CHANNEL ►)

**Select** d'une tranche sélectionne son canal (LED Select allumée). **◄ CHANNEL ►** passe au canal
affiché précédent / suivant ; au bout de la couche, la banque suit (couche voisine). Si le canal
sélectionné n'est plus affiché (après BANK ou un clic LV1), CHANNEL repart du 1er canal affiché.
La sélection est **propre au pont**, comme dans MyFOH : l'écran de la LV1 ne la voit pas.
Elle servira à l'étape 4 (gain X32, EQ…).

### Test
1. Select sur une tranche, puis CHANNEL ► / ◄ plusieurs fois : une seule LED Select, qui suit.
2. Sur la dernière tranche, CHANNEL ► : on passe à la couche suivante, 1er canal sélectionné.
3. BANK ► puis BANK ◄ : la LED Select revient sur le même canal.
4. Envoie-moi le journal.

## Étape 4 : gain et 48 V des préamplis X32 (via X/M32 Gain Recall)

**X/M32 Gain Recall doit tourner** et être connecté à la console : le pont lui passe les réglages
(il connaît déjà quel préampli X32 alimente quel canal LV1).
- **TRACK** : encodeurs en mode **gain** (LED TRACK allumée). Chaque encodeur règle le gain du préampli
  de sa tranche, 0,5 dB par cran (canal stéréo : les deux préamplis ensemble). La ligne du bas affiche le
  gain, la couronne le montre. Re-TRACK : retour à l'affichage des faders.
- **Canal stéréo** : on règle **un seul côté à la fois** (gain comme 48 V). L'encodeur règle **L** ; un appui
  sur l'encodeur passe à **R**, un autre revient à L. Écran : « L+12.0 » / « R+11.5 ». Rec (tenu 1 s) agit
  sur le côté affiché, et la LED Rec montre le 48 V de ce côté.
- **Rec** : 48 V du préampli de la tranche. **Tenir 1 s** (un appui bref ne fait rien : protection des
  micros à ruban). LED Rec = 48 V réel, tout le temps.
- Tranche sans préampli X32 (pas d'EXP, Fx, bus…) : « - », couronne éteinte.
- `--x32 aucun` désactive ; `--x32 http://…` autre adresse de Gain Recall.

### Test (hors concert, micros débranchés pour le 48 V)
1. Lance Gain Recall, puis `py xtouch_lv1_display.py`.
2. TRACK, tourne l'encodeur de In 1 : le gain doit bouger dans Gain Recall et sur la X32.
3. Tiens Rec d'une tranche 1 s : 48 V allumé (Gain Recall, X32, LED). Appui bref : rien.
4. Envoie-moi le journal.

## PAN

**PAN** : encodeurs sur le pan des tranches (LED PAN ; TRACK et PAN s'excluent). 1 cran = 1 pas de la LV1,
**appui sur l'encodeur = centre**. Écran : « L45 », « C », « R12 ». Le pan de départ des entrées est lu dans la
base de la LV1 ; s'il est inconnu (« ? », ex. bus), l'encodeur ne fait rien tant que le pan n'a pas bougé une fois.

## Rappel de pistes à l'écran

Les X-Touch sont plus larges que l'écran : quand tu **touches un fader**, un bandeau apparaît en bas de l'écran
(zone des faders de la LV1) avec **17 cases alignées sur la surface** (8 Extender, 8 X-Touch + master) : couleur et
nom du canal, valeur, vumètre ; le fader touché est entouré de blanc. En sends : « SEND > FX 1 ». Il disparaît
0,5 s après avoir lâché, en fondu. Chaque case : couleur et nom, MUTE / SOLO / 48V, gain X32 et pan, fader,
vumètre (deux en stéréo), valeur ; contour jaune = tranche sélectionnée, blanc = fader touché.

**Régler l'alignement** (même pendant que le pont tourne) :

    py xtouch_overlay_qt.py --reglage

Trois blocs à l'écran : EXTENDER (8), X-TOUCH (8), MASTER (1). Glisse un bord pour l'étirer, l'intérieur pour le
déplacer, la ligne du haut ou du bas pour la hauteur ; ENREGISTRER (ou Entrée) / ANNULER (ou Échap).

**Deux tailles mémorisées** : *petit* (nom, couleur, valeur, diode de vumètre) et *grand* (tout : fader, vumètres,
mute / solo / 48V, gain, pan). Bascule (le pont suit tout de suite) :

    py xtouch_overlay_qt.py --taille petit
    py xtouch_overlay_qt.py --taille grand

Le réglage (`--reglage`) modifie la taille en cours.

**Boutons à l'écran** : avec le bandeau apparaissent deux boutons en bas à gauche de la LV1 (sous Output L/R ;
remontés au-dessus du bandeau en taille grand) : ▲ LARGE / ▼ SMALL bascule la taille, ⚙ ADJUST ouvre le réglage.
Ils font partie du bandeau (même apparition, même disparition) : on tient un fader et on appuie sur le bouton.

## Sends on fader (SEND)

1. **SEND** : les écrans affichent les aux (Fx 1-8 sur l'Extender, Mon 1-8 sur la X-Touch ; BANK = Mon 9-16).
   Pendant ce choix, les faders règlent les **masters des aux** ; les boutons de tranche ne font rien.
2. **Select** sous l'aux voulu : les faders règlent les **envois** de chaque canal vers cet aux ; le fader
   master règle le master de l'aux. Afficheur : « SE » et le nom court de l'aux (F3, M2…).
3. **Mute** = envoi on/off (LED allumée = envoi coupé ; monter un envoi l'allume, c'est la LV1 qui le fait). **Encodeur** = pan de l'envoi, appui = centre.
4. **SEND** à nouveau : retour aux faders des canaux.

On sait qu'on est en mode sends : bouton SEND allumé, afficheur « SE » + aux, **ligne du bas des écrans =
aux + niveau** (« F1 -12 »), et à l'écran du PC un bandeau « SEND ON FADER : FX 1 … » puis un **cadre rouge** autour de la LV1 qui
clignote doucement (les clics passent au travers), au style de X/M32 Gain Recall v3 (Qt/PySide6 ; sans PySide6,
version simple). `--sans-cadre` retire bandeau et cadre.

## Touches F1 à F8 = User Keys 1 à 8 de la LV1

**F1..F8** appuient sur les User Keys 1..8 de la LV1 (assigne-les dans la LV1). Si une User Key est un
**Flip Sends** (ex. « Flip Sends: MX1: Mon 1 »), la X-Touch passe aussi en sends on fader vers cet aux (bandeau,
cadre, « M1 -12 ») et la LED de la touche F s'allume ; un 2e appui ramène la LV1 et la X-Touch en mode normal.
Autre fonction : la LV1 la fait, la X-Touch ne change pas de mode.

## La LV1 suit BANK et la sélection (`--clic-lv1`)

L'API réseau de la LV1 n'a pas de commande de couche ni de sélection. Avec `--clic-lv1`, le pont **clique
pour toi dans la fenêtre de la LV1** (la souris ne bouge pas) : BANK clique la case de couche, Select et
CHANNEL cliquent le nom de la tranche. Conditions :
- lancer le pont dans un **PowerShell en administrateur** (la LV1 l'est ; sinon Windows bloque) ;
- la LV1 doit être **affichée** sur la page Mixer suivie, ou sur **Channel** (le pont passe un instant sur
  Mixer, clique, puis revient sur Channel) (onglet lu à l'écran avant chaque clic) ;
  sinon aucun clic, la X-Touch continue en local et la raison s'affiche.

    py xtouch_lv1_display.py --clic-lv1

Outil d'essai séparé : `py lv1_clic.py verifier | couche N | tranche N`.

## Jog wheel = potard de plugin (page Channel, avec `--clic-lv1`)

Sur la page **Channel**, touche un potard de plugin dans la LV1 : son réglage apparaît en bas en fader horizontal.
Le **jog wheel** de la X-Touch le règle, un cran = un cran de molette. Rien ne se passe si la LV1 n'est pas sur
Channel ou si aucun potard n'est sélectionné. Si la LV1 ne réagit pas : `--jog-methode souris`.

## Bouton FLIP = Flip A/B

Assigne une User Key de la LV1 à **« Flip AB Input channel »** (ex. User Key 16) : **FLIP** de la X-Touch appuie
dessus. La LED FLIP est allumée quand des entrées sont sur **B** (virtual soundcheck).
La LV1 demande une confirmation : clique-la à l'écran. Sur l'écran du PC, la touche FlipAB affiche en permanence
**FLIP A** (bleu) ou **FLIP B** (rouge).

## Bouton SOLO

Le bouton **SOLO** de la X-Touch s'allume dès qu'un solo est actif dans la LV1 ; un appui **retire tous les solos**.

## Transport → Reaper

Dans Reaper : Préférences > Control/OSC/web > Add > **OSC (Open Sound Control)** :
- Mode : *Configure device IP+local port* ;
- Device IP **127.0.0.1**, Device port **9000** (Reaper y renvoie son état : LED) ;
- Local listen port **8000** (Reaper y reçoit les commandes) ;
- Pattern config : *Default*.

Le pont s'y connecte tout seul (autre réglage : `--reaper hôte:8000:9000`, `--reaper aucun` pour couper).

| Bouton X-Touch | Reaper |
|---|---|
| ► ■ ● | lecture, stop, enregistrement (LED = état de Reaper) |
| ◄◄ ►► (tenus) | retour / avance rapide |
| CYCLE / CLICK | boucle / métronome |
| DROP / REPLACE | **In / Out de la boucle** au curseur (pendant la lecture : à la position jouée) |
| MARKER seul | pose un marqueur |
| ◄ ► (flèches) | marqueur précédent / suivant |
| ▲ ▼ | piste précédente / suivante |
| ZOOM (allumé) + flèches | ◄ ► zoom horizontal, ▲ ▼ zoom vertical |
| Jog | déplace le curseur (SCRUB allumé : pas fin) — sauf page Channel de la LV1 avec un fader de plugin en bas : là il règle le plugin |

Essai sans X-Touch : `py reaper_link.py play`, `py reaper_link.py stop`, `py reaper_link.py marker`.

## Scènes LV1 ↔ marqueurs Reaper (comme Tracks Live)

Une fois dans Reaper : Actions › Show action list › New action › **Load ReaScript…** ›
`reaper/lv1_scenes.lua` (dans ce dossier), puis **Run**. L'action reste allumée tant que le lien tourne ; la relancer
l'arrête. Pour qu'il démarre avec Reaper : SWS (Startup actions) ou `__startup.lua`.

- **Enregistrement** : rappeler une scène sur la LV1 pose un **marqueur vert** au nom de la scène.
- **Lecture** : quand la lecture passe sur un marqueur vert, la scène est **rappelée sur la LV1**. Sauter dans la
  timeline ne rappelle rien.
- **Arrêt** : rappeler une scène sur la LV1 place le curseur sur le marqueur du même nom.

Ne change pas la couleur des marqueurs de scène à la main : c'est elle qui les fait reconnaître.

## Pistes Reaper = entrées LV1 (synchro)

Le **routage** suit aussi (lu dans la base de la LV1 toutes les 5 s) : sur chaque piste, l'**entrée d'enregistrement**
= les canaux du pilote SoundGrid de ce PC qui reçoivent la source de l'entrée A du canal, et une **sortie matérielle**
vers les canaux de lecture branchés sur l'**entrée B** (virtual soundcheck). Ça suppose que Reaper utilise ce pilote
comme carte son. Les autres envois de la piste ne sont pas touchés ; le routage ne change que Reaper à l'arrêt.

**Reaper sur un autre ordinateur** : `--pilote NOM` (le pilote SoundGrid de cet ordinateur, tel qu'il est nommé dans
l'inventaire de la LV1, ex. `--pilote TracksLive-FL`), `--reaper IP-DU-PC:8000:9000` pour le transport, et
`--dossier-reaper //PC-REAPER/lv1` : un dossier partagé où tu copies aussi les scripts `reaper/*.lua`, chargés dans
Reaper depuis ce dossier.

Charger aussi `reaper/lv1_sync_tracks.lua` (Load ReaScript…) et le lancer à chaque synchro : il propose **OUI** =
toutes les entrées, **NON** = seulement celles renommées (pas « Channel N »), puis crée / met à jour une piste par
entrée, dans l'ordre de la LV1, avec son nom et sa couleur. Il ne touche jamais à tes autres pistes et ne supprime
rien. Ensuite, tant que `lv1_scenes.lua` tourne, un nom ou une couleur changés sur la LV1 suivent tout seuls, et
une nouvelle entrée (ou, en mode NON, une entrée que tu renommes) a sa piste ajoutée toute seule, **Reaper à l'arrêt
seulement**. Attention : une piste synchronisée que tu supprimes dans Reaper revient à l'arrêt suivant (relance la
synchro en mode NON et laisse l'entrée en « Channel N » sur la LV1 pour qu'elle ne revienne pas).

## Reaper façon Tracks Live 2 : barre de vumètres

Charger `reaper/lv1_meter_bridge.lua` (Actions > New action > Load ReaScript…) et le lancer. La fenêtre
« LV1 Meter Bridge » s'ancre dans le docker. Pour la mettre en haut comme dans Tracks Live : clic droit sur l'onglet du
docker > Attach docker to: Top. Tout se fait au doigt (écran tactile) ; le clic droit marche aussi mais n'est pas nécessaire.

- Une colonne par piste : n° du canal LV1, couleur, nom court, vumètre (2 barres si stéréo) avec maintien de crête et
  voyant rouge d'écrêtage (toucher le haut de la colonne = effacer).
- Toucher une colonne = sélectionne la piste et la montre dans la vue ; glisser le doigt = faire défiler les colonnes.
- Case **R** en bas de chaque colonne : arme ou désarme cette piste (rouge = armée).
- Boutons à gauche :
  - **ARM ALL** : arme toutes les pistes affichées (rouge « ARMED ») ; 2e appui = tout désarmer ;
  - **MON** : monitoring d'entrée de toutes les pistes, OFF -> ON -> AUTO -> OFF (« MON ? » = réglages mélangés,
    l'appui les remet à OFF) ;
  - **WAVE - / WAVE +** : hauteur des formes d'onde (affichage seulement, le son ne change pas) ; « ? » = action
    introuvable dans ce Reaper ;
  - **FIT** : toutes les colonnes tiennent dans la fenêtre (bleu) ou largeur fixe ;
  - **SYNC TRACKS** : synchronise les pistes avec la LV1 (lance `lv1_sync_tracks.lua` : OUI = canaux enregistrés,
    NON = tous) ; à faire au début (un nouveau projet est vide) et quand des canaux changent ;
  - **MENU** : Show mixer / Show master track (les décocher = vue « pistes seulement »), hauteur de toutes les pistes
    (Micro … Extreme), pistes LV1 seulement, effacer les écrêtages, ancrer / détacher.
- Les pistes créées par la synchro sont désarmées, monitoring OFF.
- Relancer l'action = fermer la fenêtre.

À vérifier : sur une piste armée, le vumètre montre-t-il bien le signal d'ENTRÉE (avant de lancer l'enregistrement) ?

## Diagonale B (virtual soundcheck)

Entrée B de la n-ième ligne (voie) de la grille = canal n du pilote SoundGrid de Reaper. Quand un canal passe de mono
à stéréo, les lignes se décalent : la touche **FLIP** de l'écran prend un contour rouge et devient **« FLIP ! »**. Le plus rapide : refaire la
diagonale à la main (un glisser de la première case jusqu'en bas à droite).
Ouvre **Patch › Input › Input B** (vignette du pilote sélectionnée, grille en haut à gauche) et appuie sur **ENTER**
de la X-Touch : la grille est dézoomée et la diagonale refaite. En ligne de commande (PowerShell administrateur) :
`py lv1_patch.py lire`, `py lv1_patch.py diagonale` (voir), `py lv1_patch.py diagonale --go` (faire).

## DISPLAY et SAVE

- **DISPLAY** : met Reaper au premier plan (si la LV1 est devant), sinon la LV1. LED allumée = Reaper devant.
- **SAVE** : Reaper devant -> *Save project as* ; LV1 devant -> appuie sur la User Key de la LV1 dont la fonction
  contient « Store » (à assigner dans la LV1 à l'enregistrement de scène) ; autre fenêtre devant -> rien.
  Essai sans X-Touch : `py fenetres.py` (qui est devant), `py fenetres.py reaper` / `py fenetres.py lv1`.

## Affichage à l'écran

La pastille FLIP n'apparaît **que quand la LV1 est au premier plan**. Le rappel de pistes et le bandeau / cadre
SEND restent affichés même quand une autre fenêtre est devant.

## Capture du trafic MyFOH (recherche des commandes couche / sélection)

`lv1_capture.py` décode une capture réseau tablette <-> LV1 en messages lisibles. La capture se fait avec
**pktmon**, intégré à Windows (rien à installer), dans un **PowerShell lancé en administrateur**.
Le port LV1 (ex. 56397) est celui affiché par `xtouch_lv1_display.py` (« LV1 trouvée : … port … ») ;
il change quand on change la config du mixer.

```
pktmon filter remove
pktmon filter add LV1 -t TCP -p 56397
pktmon start --capture --comp nics --pkt-size 0 -f "$env:USERPROFILE\Documents\xTouchController_LV1_workspace\myfoh.etl"
   ... gestes dans MyFOH, 5 s entre chaque ...
pktmon stop
pktmon etl2pcap "$env:USERPROFILE\Documents\xTouchController_LV1_workspace\myfoh.etl" -o "$env:USERPROFILE\Documents\xTouchController_LV1_workspace\myfoh.pcapng"
pktmon filter remove
```

Puis : `py lv1_capture.py myfoh.pcapng` (option `--tout` pour voir aussi vumètres et ping).
