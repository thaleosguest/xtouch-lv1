"""Test : Sends on Fader activé SUR LA LV1 -> la X-Touch et le bandeau suivent (demande de Joseph, 19/10/2026).
Séquences relevées dans le journal 195719 (/Notify/InternalAssign, type 7 = bus sur les faders) :
- menu Fx « Reverb Hall » : LR off, Fx 1 on -> X-Touch en sends vers l'aux 0, bandeau « FX 1 » ; LV1 revient sur LR -> normal ;
- menu Mon « Mon 3 » -> aux 10 (Mon 3) ; LED F de la User Key « Flip Sends: MX1: Mon 1 » seulement pour Mon 1 ;
- états de passage (F6 : LR off, Fx 1 on, Fx 2 on, Fx 1 off) : seul l'état final compte, après SOF_SETTLE ;
- aucun appui de User Key envoyé par le suivi ; fader tenu : attendre le lâcher ;
- mode SEND local de la X-Touch (LV1 restée sur LR) : pas touché ;
- Mixer 2 affiché : même état (la LV1 envoie le même message, 4e nombre 0) ;
- InternalAssign suit le SOLO : une entrée en solo (0 n) est ignorée, pendant ou hors sends.

    py tests/test_sof_lv1.py .
"""
import sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

envoyes = []
class Link:
    def send(self, address, args=()):
        envoyes.append(address)

st = D.LV1State()
fx = [(2, k, "Fx %d" % (k + 1)) for k in range(8)]
mon = [(25, k, "Mon %d" % (k + 1)) for k in range(16)]
st.aux_tracks = fx + mon
st.user_keys = {0: ("Mon 1", "Flip Sends: MX1: Mon 1", True), 4: ("RvrHll", "Flip Sends: MX1: Fx 1", True)}
sends = D.SendControl(st, Link(), write=True)


def ia(g, c, on):
    D.handle(st, "/Notify/InternalAssign", [("i", g), ("i", c), ("i", 7), ("i", 0), ("i", on), ("i", 1)])


def suivre(busy=False):
    """Un tour de boucle après stabilisation."""
    sends.follow_lv1(D.time.time() + 1.0, busy=busy)


# état de départ annoncé par la LV1 : LR sur les faders -> rien ne change
ia(3, 0, 1); suivre()
check("départ LR : mode normal", sends.aux is None)

# menu Fx « Reverb Hall »
ia(3, 0, 0); ia(2, 0, 1)
sends.follow_lv1(D.time.time(), busy=False)          # trop tôt (états de passage possibles)
check("pas avant SOF_SETTLE", sends.aux is None)
suivre()
check("Fx 1 sur la LV1 -> X-Touch en sends aux 0", sends.aux == 0 and not sends.picking)
check("bandeau à l'écran", sends.overlay_info()[0] == "FX 1")
check("LED F5 (User Key Flip Sends Fx 1)", sends.fkey_leds()[4] and sum(sends.fkey_leds()) == 1)

# retour LR sur la LV1
ia(2, 0, 0); ia(3, 0, 1); suivre()
check("LR sur la LV1 -> mode normal", sends.aux is None and sends.overlay_info() == (None,))

# menu Mon « Mon 3 »
ia(3, 0, 0); ia(25, 2, 1); suivre()
check("Mon 3 -> aux 10, pas de LED F", sends.aux == 10 and not any(sends.fkey_leds()))
ia(25, 2, 0); ia(3, 0, 1); suivre()

# états de passage (X-Touch F6 du journal) : LR off, Fx 1 on, Fx 2 on, Fx 1 off -> Fx 2
ia(3, 0, 0); ia(2, 0, 1); ia(2, 1, 1); ia(2, 0, 0); suivre()
check("états de passage : Fx 2 au final", sends.aux == 1)
ia(2, 1, 0); ia(3, 0, 1); suivre()

# fader tenu : attendre le lâcher
ia(3, 0, 0); ia(2, 3, 1)
suivre(busy=True)
check("fader tenu : pas encore", sends.aux is None)
suivre()
check("lâché : Fx 4", sends.aux == 3)
ia(2, 3, 0); ia(3, 0, 1); suivre()

# Mixer 2 affiché (essai de Joseph) : même message, 4e nombre 0 -> suivi aussi
st.view = 1
ia(3, 0, 0); ia(25, 3, 1); suivre()
check("Mixer 2 : Mon 4 suivi", sends.aux == 11)
ia(25, 3, 0); ia(3, 0, 1); suivre()
check("Mixer 2 : retour normal", sends.aux is None)
st.view = 0

# solo d'une entrée pendant les sends (capture MyFOH : InternalAssign 0 n) : ignoré ; fin du solo : on reste en sends
ia(3, 0, 0); ia(2, 2, 1); suivre()
check("Fx 3 en sends", sends.aux == 2)
ia(0, 4, 1); suivre()
check("solo d'une entrée : on reste en sends", sends.aux == 2)
ia(0, 4, 0); ia(2, 2, 1); suivre()
check("fin du solo d'entrée : toujours Fx 3", sends.aux == 2)
ia(2, 2, 0); ia(3, 0, 1); suivre()
check("LR : normal", sends.aux is None)
# hors sends, solo d'une entrée : rien
ia(3, 0, 0); ia(0, 1, 1); suivre()
check("solo d'entrée hors sends : rien", sends.aux is None)
ia(0, 1, 0); ia(3, 0, 1); suivre()

check("le suivi n'a envoyé aucune User Key", envoyes == [])

# mode SEND local de la X-Touch (LV1 restée sur LR) : pas touché par le suivi
sends.aux = 5
suivre(); suivre()
check("SEND local gardé", sends.aux == 5)

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
