"""Géométrie de l'écran de la LV1 : positions, tailles et couleurs relevées sur des captures.

C'est LE fichier à revérifier après une mise à jour de la LV1 : tout ce que le pont clique ou lit à l'écran, et
tout ce que l'overlay pose dessus, passe par ces valeurs. Déplacé tel quel de `lv1_clic.py` (étape 3a du
refactor, 19/10/2026) et de `xtouch_overlay_qt.py` (étape 3b) : AUCUNE valeur n'a changé, les commentaires
d'origine suivent (date et capture de chaque relevé).

Repère : pixels d'un écran 1920x1080 en plein écran. `lv1_clic.Target` les met à l'échelle de la zone client
réelle (fenêtre réduite, autre résolution) : x * largeur / REF_W, y * hauteur / REF_H. Couleurs en RVB simples :
ce fichier ne dépend pas de Qt (l'overlay en fait des QColor).
"""

REF_W, REF_H = 1920.0, 1080.0

# ── Barre du haut : onglets ───────────────────────────────────────────────────────────────────────────────────
# Les 7 onglets (relevé du 14/10, capture lv1_channel) : centres x, couleur lue en y 14 (au-dessus du texte),
# actif = bleu, autres = gris clair (231, 231, 231). Clic au centre (y 28).
TABS = {"Mixer 1": 652, "Mixer 2": 750, "All": 848, "Channel": 946, "Show": 1044, "Patch": 1142, "Setup": 1240}
TAB_READ_Y = 14
TAB_Y = 28
TAB_ACTIVE = (56, 201, 255)
TAB_X = {1: 651, 2: 749}           # INUTILISÉ (remplacé par TABS) ; gardé pour que l'étape 3 reste un pur déplacement

# ── Colonne de droite : couches ───────────────────────────────────────────────────────────────────────────────
LAYER_X, LAYER_Y0, LAYER_PITCH = 1847, 537, 72
LAYER_EDGE = (1782, 1789)        # bord gauche des cases de couche (contour en x 1784 sur 1920, captures du 16/10)

# ── Colonne de droite : boutons de mode de couche ─────────────────────────────────────────────────────────────
# Boutons de mode de couche, au-dessus des couches (captures du 16/10/2026, page Mixer 1, 1920x1080) : 80 canaux =
# Input + Mix ; 16 / 32 / 64 = un seul bouton Factory centré ; Custom et Spill partout. Colonne des couches identique
# dans les deux cas. Actif = rempli de bleu (56, 201, 255), inactif = fond sombre + texte clair : garde-fou = texte ou
# bleu présent dans les boutons Custom et Spill (mode_row_why ; 8 à 11 points clairs sur les captures, 0 ailleurs).
MODE_BUTTONS = {"input": (1814, 442), "mix": (1881, 442), "factory": (1847, 442), "custom": (1814, 479),
                "spill": (1881, 479)}
MODE_ROW_Y, MODE_SPANS = 479, ((1786, 1843), (1853, 1910))     # rangée Custom / Spill (garde-fou)
MODES_80 = ("input", "mix", "custom", "spill")
MODES_64 = ("factory", "custom", "spill")
SPILL_ON = (140, 255, 0)          # bouton Spill allumé (capture du 16/10) ; éteint = fond sombre (17)
SPILL_PTS = ((1860, 479), (1900, 488), (1858, 486))

# ── Tranches ──────────────────────────────────────────────────────────────────────────────────────────────────
STRIP_X0, STRIP_PITCH, STRIP_NAME_Y = 142 + 46, 96, 433

# Bande du nom de tranche : sa position dépend des modes Top / Middle / Bottom / Big Fader (question de Joseph,
# 14/10). On la CHERCHE dans la colonne de la tranche : pixels de la couleur exacte du canal (/Notify/TrackColor),
# hauteur 12..34 px sur 1080, entre y 300 et 700 (la case de source en haut et le pied de tranche ont aussi la
# couleur du canal, mais hors de cette plage ou d'une autre hauteur). Introuvable = pas de clic.
NAME_SCAN = (300, 700)
NAME_H = (12, 34)
NAME_DX = 3                      # colonne lue : 3 px après le bord gauche de la bande (le texte n'y arrive pas)

# Tranche sélectionnée sur la LV1 (sens LV1 -> X-Touch) : liseré jaune pur en haut de sa case de source, présent
# dans tous les modes (relevé par x32-gain-recall, `lv1_selected_column_top`, et sur la capture du 14/10).
SEL_TOP_ROWS = (98, 100, 102)      # /1080
SEL_YELLOW = (255, 242, 0)         # un canal de couleur jaune est (243, 250, 29) : distinct
SEL_X0, SEL_PITCH = 143, 96        # /1920

# ── Page Channel : fader horizontal du bas ────────────────────────────────────────────────────────────────────
# Page Channel : quand on touche un potard de plugin, son réglage apparaît en bas en fader horizontal
# (« Comp Attack 6.91 », capture du 15/10). La molette de la souris au-dessus le fait bouger (essai de Joseph ;
# pas le clavier). Piste grise (54, 54, 54) x 690..1572, y 1040..1049 ; poignée claire (231, 231, 231).
BOTTOM_Y = 1044
BOTTOM_X = (690, 1572)
BOTTOM_GREY = (54, 54, 54)

# ── Barre du haut : User Keys (pastille A/B de l'overlay, posée sur la touche « FlipAB ») ─────────────────────────
# Pastille A/B posée sur la User Key « FlipAB » de la LV1 (demande de Joseph, 15/10 : voir à tout moment si les
# entrées sont sur A ou B). Rangée des User Keys, visible sur toutes les pages : touche k = x 145+96k .. 229+96k,
# y 62..90 (1920x1080, relevé du 15/10). Pastille dans la partie droite de la touche.
UK_X0, UK_PITCH, UK_W, UK_Y0, UK_H = 145, 96, 84, 62, 28   # seul UK_PITCH sert ; les 4 autres : relevé gardé
# Touche d'origine relevée au pixel (15/10) : contour clair (160) x 144+96k .. 230+96k, y 61..90, coins ~5 px, intérieur
# (17,17,17), fond de la rangée (71,71,71).
KEY_L, KEY_T, KEY_W, KEY_H, KEY_R = 144, 61, 87, 30, 5
ROW_BG, KEY_BG, KEY_LINE = (71, 71, 71), (17, 17, 17), (160, 160, 160)
A_BLUE = (56, 201, 255)          # bouton A/B actif de la LV1 (même bleu que l'onglet actif, TAB_ACTIVE)

# ── Zones libres de l'écran où l'overlay se pose ──────────────────────────────────────────────────────────────
# Notification de couche : coin bas-droit = juste à gauche de la colonne des couches (x 1785) et au-dessus de la
# rangée SOLO (y 1018).
TOAST_RIGHT, TOAST_BOTTOM = 1772, 1010
# Boutons du rappel de pistes : zone vide en bas à gauche de la LV1 (sous Output L/R, endroit montré par Joseph sur
# sa capture du 15/10) : x, y, largeur, hauteur des deux boutons ensemble.
BTN_RECT = (38, 862, 54, 134)
