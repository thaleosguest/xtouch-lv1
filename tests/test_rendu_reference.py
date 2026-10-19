"""Test de référence du rendu X-Touch (étape 0 du refactor, 19/10/2026).

Rejoue un VRAI journal LV1 (`data/journal_reference.txt`, extrait du journal du 17/10 : 1740 messages, seules les
22 adresses que `handle()` traite) et compare TOUT ce qui part vers la X-Touch — écrans, couleurs, moteurs de
faders, vumètres, LED, couronnes, afficheur 7 segments — à `data/rendu_reference.txt`.

Le but n'est pas de dire si l'affichage est JUSTE (les autres tests s'en chargent) mais qu'il ne CHANGE PAS pendant
le refactor : un seul octet de différence et le test échoue en nommant la ligne.

Pas de matériel, pas de fil, pas de socket : horloge figée (`Clock`, avance de TICK par tour comme la vraie boucle),
`Surface` branchée sur une sortie MIDI qui enregistre, rendu = `App.tick_render` (étape 9). Deux exécutions
donnent le même fichier.

    py tests/test_rendu_reference.py .            # compare
    py tests/test_rendu_reference.py . --maj      # réenregistre la référence (changement VOULU seulement)
"""
import ast
import os
import re
import sys
import time as vraie_horloge

sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D
import xtouch_probe as X

HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(HERE, "data", "journal_reference.txt")
REF = os.path.join(HERE, "data", "rendu_reference.txt")
MAJ = "--maj" in sys.argv


# ── horloge figée : le rendu ne doit dépendre ni de l'heure ni de la vitesse de la machine ────────────────────
class Clock:
    """Remplace le module `time` dans xtouch_lv1_display ET les modules bridge/ (étape 8 : les contrôleurs y sont
    partis) ; le test ne lance aucun fil."""
    now = 1000000.0
    FIXE = vraie_horloge.struct_time((2026, 10, 17, 15, 9, 46, 4, 290, 1))

    def time(self):
        return Clock.now

    def monotonic(self):
        return Clock.now

    def sleep(self, _s):
        pass

    def localtime(self, _t=None):
        return Clock.FIXE

    def strftime(self, fmt, t=None):
        return vraie_horloge.strftime(fmt, t or Clock.FIXE)


D.time = Clock()
for _nom, _mod in list(sys.modules.items()):
    if _nom.startswith("bridge.") and hasattr(_mod, "time"):
        _mod.time = D.time


# ── sortie MIDI qui enregistre au lieu d'envoyer ──────────────────────────────────────────────────────────────
class MidiEnregistre:
    def __init__(self):
        self.log = []

    def short(self, h, status, d1, d2=0):
        self.log.append("%-4s C %02X %02X %02X" % (h, status, d1, d2))

    def long(self, h, data):
        self.log.append("%-4s S %s" % (h, bytes(data).hex()))


# ── lecture du journal (même analyseur que tests/rejouer_couches.py) ──────────────────────────────────────────
TOK = re.compile(r"([a-zA-Z]):('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\S+)")


def parse_args(rest):
    out = []
    for t, v in TOK.findall(rest):
        if t == "s":
            v = ast.literal_eval(v)
        elif t in "ih":
            v = int(v)
        elif t in "fd":
            v = float(v)
        elif t in "TF":
            v = t == "T"
        out.append((t, v))
    return out


def messages():
    for line in open(JOURNAL, encoding="utf-8"):
        p = line.rstrip("\n").split(" ", 2)
        if len(p) >= 2 and p[1].startswith("/"):
            yield p[1], parse_args(p[2] if len(p) > 2 else "")


# ── le pont, sans matériel ────────────────────────────────────────────────────────────────────────────────────
midi = MidiEnregistre()
# Ordre de l'installation de Joseph : Extender à GAUCHE (tranches 1-8), X-Touch à droite (master).
units = [("Extender", X.ID_EXT, "ext"), ("X-Touch", X.ID_MAIN, "main")]
state = D.LV1State()
xt = D.Surface(midi, units)
gain = D.GainControl(state, None, write=False, lv1=None)
sends = D.SendControl(state, None, write=False, gain=gain)
buttons = D.ButtonControl(state, None, write=False, page=0)
MASTER_CIBLE = (3, 0)          # fader master -> LR, comme le défaut --master 3:0
# Étape 9 : le VRAI tour de rendu du pont (App.tick_render), plus une imitation. App(None) ne démarre rien : on y
# branche nos objets (pas de REAPER, de Gain Recall, d'overlay ni de bascule d'appli, comme dans le test d'avant).
app = D.App(None)
app.state, app.xt, app.gain, app.sends, app.buttons = state, xt, gain, sends, buttons
app.master_target = MASTER_CIBLE
app.entries = [None] * xt.strips
app.shown_view = state.view
sortie = []


def rendu(etiquette):
    """Un tour de rendu de la boucle principale (App.tick_render), sans doigt sur un fader."""
    Clock.now += D.TICK
    avant = len(midi.log)
    app.tick_render(Clock.now, ())
    nouveau = midi.log[avant:]
    if nouveau:                                            # Surface n'envoie que ce qui change : rien = rien à noter
        sortie.append("# %s | couche=%s" % (etiquette, app.last_layer))
        sortie.extend("    " + l for l in nouveau)


# 1) le vrai journal, message par message. La connexion est posée à la main : c'est LV1Link (réseau) qui la fait
# en vrai, et sans elle build_frame n'affiche que l'écran d'attente (210 envois au lieu de ~6000).
state.connected = True

for n, (addr, args) in enumerate(messages(), 1):
    D.handle(state, addr, args)
    rendu("msg %d %s" % (n, addr))

# 2) ce que le journal ne contient pas (vumètres filtrés, gestes de la xt, états lus à l'écran)
state.connected = True
for g, ch, sub, db in ((0, 0, 0, -6.0), (0, 1, 0, -18.0), (0, 2, 0, -60.0), (3, 0, 0, -3.0)):
    D.handle(state, "/Notify/Meters", [("i", 1), ("i", g), ("i", ch), ("i", sub), ("f", db)])
rendu("vumètres")
gain.mode = True
rendu("mode TRACK")
gain.mode, gain.pan_mode = False, True
rendu("mode PAN")
gain.pan_mode = False
buttons.reaper_tc = False
rendu("afficheur = heure")
for mode, tab, spill in ((0, "Mixer 1", False), (4, "Mixer 1", False), (5, "Mixer 1", False), (1, "Mixer 1", False),
                         (4, "Mixer 1", True), (4, "All", False)):
    state.layer_mode[state.view] = mode
    state.lv1_tab, state.spill_lit = tab, spill
    rendu("voyants mode=%s onglet=%s spill=%s" % (mode, tab, spill))
state.view = 1
rendu("Mixer 2")
state.view = 0
state.selected = (0, 1)
rendu("sélection In 2")

texte = "\n".join(sortie) + "\n"
if MAJ or not os.path.exists(REF):
    with open(REF, "w", encoding="utf-8", newline="\n") as f:
        f.write(texte)
    print("Référence enregistrée : %s (%d lignes, %d envois MIDI)" % (REF, len(sortie), len(midi.log)))
    print("OK")
    sys.exit(0)

attendu = open(REF, encoding="utf-8", newline="\n").read()
if texte == attendu:
    print("Rendu identique à la référence : %d lignes, %d envois MIDI." % (len(sortie), len(midi.log)))
    print("OK")
    sys.exit(0)

a, b = attendu.split("\n"), texte.split("\n")
for i in range(max(len(a), len(b))):
    if i >= len(a) or i >= len(b) or a[i] != b[i]:
        print("Première différence, ligne %d :" % (i + 1))
        print("  référence : %s" % (a[i] if i < len(a) else "(fin du fichier)"))
        print("  maintenant : %s" % (b[i] if i < len(b) else "(fin du fichier)"))
        for k in range(max(0, i - 3), i):
            print("  contexte  : %s" % a[k])
        break
print("lignes : %d attendues, %d obtenues" % (len(a), len(b)))
print("ÉCHEC : le rendu X-Touch a changé (si c'est voulu : py tests/test_rendu_reference.py . --maj)")
sys.exit(1)
