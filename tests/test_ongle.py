"""Test : fader poussé à l'ongle (toucher non détecté) : pas d'écho moteur pendant le geste, position finale renvoyée
une fois au lâcher (02/11/2026). Le doigt (toucher détecté) garde l'écho à chaque mouvement.
Usage : py tests/test_ongle.py <dossier du dépôt>
"""
import sys
import threading

sys.path.insert(0, sys.argv[1])
from bridge.faders import FaderControl, HOLD_AFTER   # noqa: E402


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.f, self.stale, self.held_tracks = {}, {}, set()

    def fader_of(self, k):
        return self.f.get(k)

    def set_fader(self, k, db):
        self.f[k] = db


class Surf:
    def __init__(self):
        self.motor, self.sent_fader, self.echo = {}, {(0, 0): 5000, (0, 1): 5000}, []

    def addr(self, s):
        return s // 8, s % 8

    def strip_of(self, u, c):
        return 8 * u + c

    def note_position(self, s, v):
        self.echo.append((s, v))
        self.sent_fader[self.addr(s)] = v


class Link:
    def send(self, *a):
        pass


fc = FaderControl(State(), Link())
fc.seen_touch = True
sf = Surf()
entries = [(0, 0), (0, 1)]
ok = True
t = 100.0
for v in (5200, 5400, 5600):                       # ongle sur le fader 1
    fc.on_midi(0, 0xE0, v & 0x7F, v >> 7, t, entries, sf)
    fc.flush(t)
    t += 0.02
ok &= sf.echo == []
fc.flush(t + HOLD_AFTER + 0.01)
ok &= sf.echo == [(0, 5600)]
print("ongle : pas d'écho pendant, position finale au lâcher", "ok" if ok else "ÉCHEC", sf.echo)
sf.echo = []
fc.on_midi(0, 0x90, 0x69, 0x7F, t, entries, sf)   # doigt sur le fader 2
fc.on_midi(0, 0xE1, 6000 & 0x7F, 6000 >> 7, t, entries, sf)
ok2 = sf.echo == [(1, 6000)]
print("doigt : écho à chaque mouvement", "ok" if ok2 else "ÉCHEC", sf.echo)
sys.exit(0 if ok and ok2 else 1)
