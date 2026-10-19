"""Notes MIDI, numéros de CC et couleurs de la X-Touch (+ Extender).

Déplacé tel quel de `xtouch_lv1_display.py` (étape 1 du refactor, 19/10/2026) : AUCUNE valeur n'a changé, les
commentaires d'origine suivent — ils disent ce qui a été vérifié sur le matériel de Joseph et ce qui vient
seulement de la norme Mackie. Quand une note est « à confirmer », c'est qu'elle n'a encore jamais été vue dans
un journal.

Protocole : appui = vélocité 127, relâchement = 0 ; LED = même note, 127 allumée / 0 éteinte.
"""

# Couleurs X-Touch (validées par xtouch_probe le 14/10/2026) : 0 vide, 1 rouge, 2 vert,
# 3 jaune, 4 bleu, 5 violet, 6 cyan, 7 blanc.
XT = {"vide": 0, "rouge": 1, "vert": 2, "jaune": 3, "bleu": 4, "violet": 5, "cyan": 6, "blanc": 7}

TOUCH_NOTES = range(0x68, 0x71)   # notes de toucher : 0x68-0x6F faders 1-8, 0x70 master (norme Mackie)
MASTER = 16                       # numéro interne du fader master (9e fader de la X-Touch)

# Boutons de tranche, notes Mackie (à confirmer sur la X-Touch) : Rec 0x00-07, Solo 0x08-0F,
# Mute 0x10-17, Select 0x18-1F. Appui = vélocité 127, relâchement = 0.
NOTE_REC, NOTE_SOLO, NOTE_MUTE, NOTE_SELECT = 0x00, 0x08, 0x10, 0x18

# Navigation, norme Mackie (vérifié le 14/10/2026) : ◄ BANK ► 0x2E/0x2F, ◄ CHANNEL ► 0x30/0x31.
NOTE_BANK_LEFT, NOTE_BANK_RIGHT = 0x2E, 0x2F
NOTE_CHANNEL_LEFT, NOTE_CHANNEL_RIGHT = 0x30, 0x31

# Jog wheel (cranté sur la X-Touch) : CC 0x3C relatif, 0x01 = un cran horaire, 0x41 = anti-horaire (Mackie, à confirmer).
# Page Channel : il règle le potard de plugin sélectionné (fader horizontal du bas) par crans de molette.
CC_JOG = 0x3C

NOTE_FLIP = 0x32                  # FLIP (vérifié le 14/10) -> User Key « Flip AB Input channel » de la LV1

# Touches View (norme Mackie ; 0x33 et 0x3F vues dans les journaux de Joseph, 0x43 et 0x45 par la suite de la norme)
# -> boutons de mode de couche de la LV1 (demande de Joseph du 16/10) : INPUTS = Input (Factory en 16/32/64),
# BUSES = Mix (80 canaux), USER = Custom, GROUP (0x4F, vue dans les journaux) = Spill ; GLOBAL VIEW = onglet All
# (aller-retour avec Mixer N, Joseph 16/10). Voyants = mode lu dans la base / onglet lu à l'écran. Notes vérifiées le 16/10 (journal 175539).
# SMPTE/BEATS (0x35) : afficheur 7 segments = timecode REAPER ou heure (Joseph, 16/10) ; LED SMPTE (0x71) = timecode.
NOTE_GLOBAL_VIEW, NOTE_INPUTS, NOTE_BUSES, NOTE_USER = 0x33, 0x3F, 0x43, 0x45
NOTE_GROUP = 0x4F
NOTE_SMPTE, NOTE_LED_SMPTE = 0x35, 0x71

NOTE_SOLO_ALL = 0x5A             # bouton SOLO (groupe Marker..Click..Solo, Mackie, à confirmer) : allumé si un solo
                                 # est actif dans la LV1 ; appui = /ClearAllSolo (demande de Joseph, 15/10)

# Assignation des encodeurs (norme Mackie, à confirmer) : TRACK 0x28. Encodeurs : CC 0x10-0x17 relatifs
# (bit 6 = sens, bits 0-3 = vitesse), couronnes : CC 0x30-0x37.
NOTE_TRACK = 0x28
NOTE_PAN = 0x2A                   # PAN/SURROUND (vérifié le 14/10, journal 183905)
NOTE_VPOT_PUSH = 0x20             # appui sur l'encodeur n : 0x20 + n (vérifié le 14/10, journal 183905)
CC_VPOT, CC_RING = 0x10, 0x30

# Afficheur 7 segments (norme Mackie, à confirmer) : timecode = 10 caractères, CC 0x40 + i (i = 0 le plus à
# DROITE) ; « Assignment » = 2 caractères, CC 0x4B (gauche) et 0x4A (droite).
CC_TIMECODE, CC_ASSIGN_L, CC_ASSIGN_R = 0x40, 0x4B, 0x4A
NOTE_RUDE_SOLO = 0x73             # LED « SOLO » près de l'afficheur (norme Mackie, à confirmer)

NOTE_SEND = 0x29                  # SEND (norme Mackie ; « sends on fader »)
NOTE_F1 = 0x36                    # F1..F8 = 0x36..0x3D (norme Mackie, à confirmer) -> User Keys 1..8 de la LV1

# Transport X-Touch -> REAPER (demande de Joseph, 15/10 : la surface coupée en deux, tranches = LV1,
# transport / navigation = Reaper pour le virtual soundcheck). Notes Mackie (norme, non vérifiées sur la X-Touch).
NOTE_MARKER, NOTE_NUDGE, NOTE_CYCLE, NOTE_DROP, NOTE_REPLACE, NOTE_CLICK = 0x54, 0x55, 0x56, 0x57, 0x58, 0x59
NOTE_REW, NOTE_FF, NOTE_STOP, NOTE_PLAY, NOTE_RECORD = 0x5B, 0x5C, 0x5D, 0x5E, 0x5F
NOTE_UP, NOTE_DOWN, NOTE_LEFT, NOTE_RIGHT, NOTE_ZOOM, NOTE_SCRUB = 0x60, 0x61, 0x62, 0x63, 0x64, 0x65
TRANSPORT_NOTES = {NOTE_MARKER, NOTE_CYCLE, NOTE_CLICK, NOTE_DROP, NOTE_REPLACE, NOTE_REW, NOTE_FF, NOTE_STOP, NOTE_PLAY, NOTE_RECORD,
                   NOTE_UP, NOTE_DOWN, NOTE_LEFT, NOTE_RIGHT, NOTE_ZOOM, NOTE_SCRUB}

# Bascule LV1 <-> Reaper et SAVE (demande de Joseph, 15/10)
NOTE_DISPLAY = 0x34      # DISPLAY (NAME/VALUE, Mackie, non vérifié) : met Reaper ou la LV1 au premier plan
NOTE_SAVE = 0x50         # SAVE (Mackie, non vérifié) : selon la fenêtre active
NOTE_ENTER = 0x53        # ENTER (Mackie, non vérifié) : refait la diagonale B (page Patch > Input B ouverte)
