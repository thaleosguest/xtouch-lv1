"""Test : renvoi complet à la X-Touch toutes les REFRESH_EVERY s (étape 10, correctif 3, 19/10/2026).
Une X-Touch qui redémarre ou décroche SANS erreur d'envoi restait vide : le pont n'envoie que ce qui change.
- avant REFRESH_EVERY : tours suivants sans rien de neuf -> rien n'est renvoyé ;
- à REFRESH_EVERY : écrans, couleurs, LED, couronnes, 7 segments renvoyés ; AUCUNE commande moteur (faders) ;
- refresh_at None (App(None), test de référence) : jamais de renvoi.

    py tests/test_renvoi_complet.py .
"""
import sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D
import xtouch_probe as X

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond


class Midi:
    def __init__(self):
        self.log = []

    def short(self, h, status, d1, d2=0):
        self.log.append(("C", status))

    def long(self, h, data):
        self.log.append(("S", None))


def app_de_test():
    midi = Midi()
    state = D.LV1State()
    state.connected = True
    xt = D.Surface(midi, [("Extender", X.ID_EXT, "ext"), ("X-Touch", X.ID_MAIN, "main")])
    gain = D.GainControl(state, None, write=False, lv1=None)
    app = D.App(None)
    app.state, app.xt, app.gain = state, xt, gain
    app.sends = D.SendControl(state, None, write=False, gain=gain)
    app.buttons = D.ButtonControl(state, None, write=False, page=0)
    app.master_target = (3, 0)
    app.entries = [None] * xt.strips
    app.shown_view = state.view
    return app, midi


app, midi = app_de_test()
t = 1000.0
app.refresh_at = t + D.REFRESH_EVERY
app.tick_render(t, ())
premier = len(midi.log)
for k in range(1, 20):
    app.tick_render(t + k * D.TICK, ())
check("rien de neuf -> rien renvoyé", len(midi.log) == premier)

avant = len(midi.log)
app.tick_render(t + D.REFRESH_EVERY, ())
renvoi = midi.log[avant:]
sysex = sum(1 for k, _ in renvoi if k == "S")
moteurs = [st for k, st in renvoi if k == "C" and 0xE0 <= st <= 0xE8]
notes = sum(1 for k, st in renvoi if k == "C" and st == 0x90)
print("1er tour : %d envois ; renvoi à %.0f s : %d envois (%d SysEx écrans / couleurs, %d LED, %d moteurs)"
      % (premier, D.REFRESH_EVERY, len(renvoi), sysex, notes, len(moteurs)))
check("écrans et couleurs renvoyés (2 lignes + couleurs x 2 unités)", sysex == 6)
check("LED renvoyées", notes > 30)
check("aucune commande moteur", moteurs == [])
avant = len(midi.log)
app.tick_render(t + D.REFRESH_EVERY + D.TICK, ())
check("puis plus rien jusqu'au prochain", len(midi.log) == avant)

app2, midi2 = app_de_test()                   # refresh_at None : comme le test de référence
app2.tick_render(t, ())
n = len(midi2.log)
app2.tick_render(t + 10 * D.REFRESH_EVERY, ())
check("refresh_at None : jamais de renvoi", len(midi2.log) == n)

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
