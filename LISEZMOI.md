# Tests X-Touch + LV1 (USB)

Deux tests indépendants, Python 3 standard (rien à installer), à lancer sur le PC de la LV1.
Les deux écrivent un rapport `.json` dans ce dossier : c'est ce fichier qu'il faut m'envoyer.

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
   py xtouch_lv1_display.py --mixer 2    # suit Mixer 2
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
Il pilote le **LR** de la LV1 par défaut, et suit sa position.
`py xtouch_lv1_display.py --master 5:0` pour une autre piste (groupe:canal ; 3 = LR, 4 = C, 5 = M, 1 = groupes…),
`--master aucun` pour le désactiver.

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
