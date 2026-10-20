"""Test : la LV1 passe de 80 à 64, 32, 16 canaux (bug de Joseph du 20/10/2026 : « COULDN'T REALIGN » après 80 -> 64).
/Channels = liste COMPLÈTE des pistes (journal 115527 : 150 pistes en 80 canaux, 126 en 64 : 64 entrées, groupes 16 -> 8) :
- les pistes absentes de la liste sont retirées (entrées 65-80, groupes 9-16), avec leurs envois ; le LR reste ;
- diagonale B : plus de canaux fantômes, patch_target ne demande plus que les lignes des canaux existants ;
- liste tronquée (message coupé) : rien n'est retiré ; retour à 80 canaux : les pistes reviennent.

    py tests/test_nb_canaux.py .
"""
import sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D
from bridge.reaper import AppControl

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond


def piste(g, c, name, stereo=False):
    """Une entrée de /Channels (19 valeurs) : nom, groupe, canal, fader, pan, 12 entiers (12e = 1 mono / 2 stéréo), h, d."""
    ints = [0] * 12
    ints[11] = 2 if stereo else 1
    return [("s", name), ("i", g), ("i", c), ("d", -144.0), ("d", 0.0)] + [("i", v) for v in ints] + \
        [("h", 1099511627776), ("d", 0.0)]


def channels(n_in, n_grp, stereo=()):
    pistes = [piste(0, c, "Channel %d" % (c + 1), c in stereo) for c in range(n_in)]
    pistes += [piste(1, c, "Group %d" % (c + 1)) for c in range(n_grp)]
    pistes += [piste(3, 0, "LR")]
    args = [("i", len(pistes))]
    for p in pistes:
        args += p
    return args


def entrees(st):
    return sorted(c for g, c in st.tracks if g == 0)


st = D.LV1State()
st.driver = ("LV1-PORT", 2)
D.handle(st, "/Channels", channels(80, 16, stereo={0}))
st.send(0, 79, 3)["fader"] = -10.0
st.send(0, 5, 3)["fader"] = -5.0
check("80 canaux lus", entrees(st) == list(range(80)))

# patch du pilote déjà en diagonale pour 64 canaux (Channel 1 stéréo : lignes 0-1, puis une ligne par canal)
st.driver_size = 128
st.routing = {0: {"play": [0, 1]}}
st.routing.update({c: {"play": [c + 1]} for c in range(1, 64)})

D.handle(st, "/Channels", channels(64, 8, stereo={0}))
check("64 : entrées 65-80 retirées", entrees(st) == list(range(64)))
check("64 : groupes 9-16 retirés, LR gardé", sorted(c for g, c in st.tracks if g == 1) == list(range(8))
      and (3, 0) in st.tracks)
check("64 : envois des pistes retirées effacés, les autres gardés", (0, 79, 3) not in st.sends and (0, 5, 3) in st.sends)
check("64 : diagonale OK (plus de Channel 65-80 fantômes)", D.diagonal_problems(st) == [])
app = AppControl.__new__(AppControl)
app.state = st
tile, expect, n, name = app.patch_target()
check("64 : REALIGN ne vise que 65 lignes", n == 65 and max(expect) == 64)

for n_in, n_grp in ((32, 8), (16, 8)):
    D.handle(st, "/Channels", channels(n_in, n_grp, stereo={0}))
    check("%d : entrées 1-%d seulement" % (n_in, n_in), entrees(st) == list(range(n_in)))
    check("%d : diagonale OK" % n_in, D.diagonal_problems(st) == [])
    check("%d : REALIGN vise %d lignes" % (n_in, n_in + 1), app.patch_target()[2] == n_in + 1)

# message tronqué : on ne retire rien
coupe = channels(8, 8)[:1 + 19 * 3]
D.handle(st, "/Channels", coupe)
check("liste tronquée : rien retiré", entrees(st) == list(range(16)))

D.handle(st, "/Channels", channels(80, 16, stereo={0}))
check("retour à 80 : pistes revenues", entrees(st) == list(range(80)))

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
