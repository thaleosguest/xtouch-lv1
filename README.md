<img src="assets/logo.svg" width="96" alt="Logo">

# XTouch-LV1 — Total Control for LV1

*by Joseph Savigny*

Une **Behringer X-Touch + X-Touch Extender** comme surface de contrôle de la **Waves eMotion LV1** : noms et
couleurs des canaux sur les écrans, vumètres, faders motorisés, Mute / Solo / Select, couches, sends, User Keys,
transport vers REAPER — et le **gain des préamplis X32 / M32** sur les encodeurs.

Version courante : **0.3**. Mode d'emploi complet : [MODE_EMPLOI.html](MODE_EMPLOI.html).

## Téléchargement

Dans la page [Releases](../../releases/latest), deux fichiers :

| Fichier | Contenu | Pour qui |
|---|---|---|
| **`Total_Control_LV1_Install.exe`** | le pack **Total Control for LV1** : installeur avec cases à cocher pour **XTouch-LV1**, **REAPER LV1** et **[X/M32 Gain Recall for eMotion LV1](https://github.com/thaleosguest/x32-gain-recall)** | la plupart des gens |
| `XTouch-LV1-v0.3.zip` | XTouch-LV1 seul, sans installation (dézipper, lancer `XTouch-LV1.exe`) | qui veut juste la surface |

### Le pack Total Control for LV1

- **XTouch-LV1** : le pont X-Touch + Extender ↔ LV1 (ce dépôt).
- **REAPER LV1** : un REAPER **portable à part**, réglé façon Tracks Live (transport en haut, barre de vumètres
  tactile, scènes LV1 ↔ marqueurs, pistes = canaux LV1). Votre REAPER habituel n'est pas touché. REAPER est
  téléchargé sur reaper.fm pendant l'installation (installeur officiel Cockos, empreinte et signature vérifiées) ;
  c'est un logiciel Cockos : essai 60 jours, puis licence REAPER.
- **X/M32 Gain Recall for eMotion LV1** : les gains et le 48V de la X32 / M32 sur l'écran de la LV1
  ([dépôt à part](https://github.com/thaleosguest/x32-gain-recall)).

Raccourcis sur le Bureau et dans le menu Démarrer > **Total Control for LV1** (programmes, modes d'emploi,
désinstalleur).

## Ce que fait la surface

- Écrans : nom du canal, valeur du fader en dB, **couleur du canal LV1** ; vumètres post-fader.
- Faders motorisés dans les deux sens, fader master sur LR ; calibration sur les repères imprimés.
- Suit le Mixer affiché sur la LV1 (Mixer 1 ou Mixer 2), tout marche pareil sur les deux.
- Mute, Solo, Select synchronisés avec l'écran de la LV1 ; ◄ BANK ► et ◄ CHANNEL ► suivent les couches
  (usine, custom, 80 canaux, Spill).
- Encodeurs : pan, et **gain des préamplis X32 / M32** (avec X/M32 Gain Recall).
- INPUTS / BUSES / USER / GROUP = boutons Input (Factory) / Mix / Custom / Spill de la LV1, GLOBAL VIEW = onglet All,
  voyants selon l'état de la LV1.
- Afficheur : position de REAPER ou heure (SMPTE pour basculer) ; nom de la couche en notification à l'écran.
- Sends on fader, F1-F8 = User Keys de la LV1, FLIP = Flip A/B, transport et molette vers REAPER.
- Lance tout seul REAPER LV1 et X/M32 Gain Recall ; tourne sans fenêtre, icône près de l'horloge pour quitter.

## Prérequis

- Windows 10 / 11, Waves eMotion LV1 (testé sur V17), X-Touch (+ Extender facultatif) en USB.
- Dans la LV1 : **retirer le contrôleur Mackie** de System Inventory (le programme parle directement aux X-Touch).
- Le programme demande les droits administrateur au lancement (la LV1 tourne en administrateur ; c'est ce qui
  permet de suivre BANK et la sélection).

## Développement

Python 3, bibliothèque standard pour le pont (PySide6 pour l'overlay et la compilation). Tests contre une fausse
LV1 et une X-Touch simulée : `py tests\test_<nom>.py .` ; installeur : `py build.py` →
`dist\Total_Control_LV1_Install.exe`.

## Mentions

Projet indépendant, **non affilié à Waves, Behringer, Midas, Music Tribe ni Cockos**. eMotion LV1, X-Touch,
X32, M32 et REAPER sont des marques de leurs propriétaires respectifs, citées uniquement pour indiquer avec quel
matériel et quels logiciels ce projet fonctionne. L'échange avec la LV1 passe par son interface réseau, non
documentée par Waves : à revérifier après chaque mise à jour de la LV1.
