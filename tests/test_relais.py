"""Test : X-Touch par le réseau (0.8.1, LV1 de Joseph dans une VM sans écran, vue en RDP).

Hôte (RelayHub + CombinedOut / CombinedIn, comme le pont du PC de la LV1) et relais (Relay, PC de la X-Touch) sur ce
PC, X-Touch simulée : ports listés côté hôte, écrans / moteurs vers la X-Touch, faders vers l'hôte, débranchement USB,
relais coupé puis revenu. Sans matériel ni LV1.
Usage : py tests/test_relais.py <dossier du dépôt>
"""
import queue
import sys
import threading
import time

sys.path.insert(0, sys.argv[1])
import netmidi as N                   # noqa: E402
import xtouch_probe as X              # noqa: E402
from surface.midi import SafeMidi     # noqa: E402

ok = True


def check(what, cond):
    global ok
    print("%-52s %s" % (what, "ok" if cond else "ÉCHEC"))
    ok = ok and cond


def until(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class FakeOut:
    def __init__(self):
        self.ports = [(0, "Microsoft GS Wavetable Synth"), (1, "X-Touch-Ext"), (2, "X-TOUCH_INT")]
        self.sent = []

    def list(self):
        return list(self.ports)

    def open(self, i):
        return "h%d" % i

    def short(self, h, st, d1, d2=0):
        self.sent.append((h, st, d1, d2))

    def long(self, h, data):
        self.sent.append((h, bytes(data)))

    def close(self, h):
        pass


class FakeIn:
    ports = [(0, "X-TOUCH_INT"), (1, "X-Touch-Ext")]

    def __init__(self):
        self.opened = {}

    def list(self):
        return list(FakeIn.ports)

    def open(self, i, unit):
        self.opened[i] = unit

    def close_all(self):
        self.opened = {}


class NoLocal:                       # PC de la LV1 : pas de X-Touch USB
    def list(self):
        return []

    def close_all(self):
        pass


def iter_q(q):
    while True:
        try:
            yield q.get_nowait()
        except queue.Empty:
            return


PORT = 9399
host_events = queue.Queue()
hub = N.RelayHub(port=PORT, log=lambda m: None)
hub.start()
out = SafeMidi(N.CombinedOut(NoLocal(), hub))
cin = N.CombinedIn(NoLocal(), hub, host_events)
check("hôte sans relais : aucun port", out.list() == [] and cin.list() == [])

stop = threading.Event()
relay_events = queue.Queue()
fake_out = FakeOut()
ins = []


def make_in():
    f = FakeIn()
    ins.append(f)
    return f


relay = N.Relay(["127.0.0.1"], "portable-test", "0.8.1", fake_out, make_in, X.pick_ports, stop,
                log=lambda m: None, port=PORT)
threading.Thread(target=relay.run, args=(relay_events,), daemon=True).start()
check("ports du relais listés par l'hôte", until(lambda: len(out.list()) == 2))
main_idx, ext_idx = X.pick_ports(out.list(), None, None)
names = dict(out.list())
check("X-Touch / Extender reconnues (pick_ports)", names.get(main_idx) == "X-TOUCH_INT"
      and names.get(ext_idx) == "X-Touch-Ext")
h_main = out.open(main_idx)
in_main, in_ext = X.pick_ports(cin.list(), None, None)
cin.open(in_main, 0)
cin.open(in_ext, 1)

out.short(h_main, 0xE0, 0x10, 0x40)                      # moteur du fader 1
out.long(h_main, [0xF0, 0x00, 0x20, 0x32, 0x14, 0x4C, 0xF7])
check("moteur reçu par la X-Touch", until(lambda: ("h2", 0xE0, 0x10, 0x40) in fake_out.sent))
check("SysEx (écran) reçu par la X-Touch",
      until(lambda: ("h2", bytes([0xF0, 0x00, 0x20, 0x32, 0x14, 0x4C, 0xF7])) in fake_out.sent))

relay_events.put((0, 0xE0, 0x05, 0x60, time.time()))     # fader de la X-Touch (entrée 0 du relais = X-TOUCH_INT)
relay_events.put((1, 0x90, 0x68, 0x7F, time.time()))     # toucher sur l'Extender
got = []
check("fader / toucher reçus par l'hôte",
      until(lambda: (got.extend(iter_q(host_events)) or True) and len(got) >= 2))
check("unités du pont respectées", [(u, st, d1, d2) for u, st, d1, d2, _t in got[:2]]
      == [(0, 0xE0, 0x05, 0x60), (1, 0x90, 0x68, 0x7F)])



t0 = time.time()
out.short(h_main, 0xB0, 0x30, 0x01)
until(lambda: ("h2", 0xB0, 0x30, 0x01) in fake_out.sent)
check("aller en moins de 50 ms", time.time() - t0 < 0.05)

FakeIn.ports = [(0, "X-Touch-Ext")]                       # X-Touch débranchée côté relais
fake_out.ports = [(1, "X-Touch-Ext")]
check("débranchement vu par l'hôte", until(lambda: len(out.list()) == 1, 5))
out.short(h_main, 0xE0, 0, 0)
check("ancienne poignée refusée -> lost", out.lost is not None)

FakeIn.ports = [(0, "X-TOUCH_INT"), (1, "X-Touch-Ext")]
fake_out.ports = [(1, "X-Touch-Ext"), (2, "X-TOUCH_INT")]
check("rebranchement vu par l'hôte", until(lambda: len(out.list()) == 2, 5))

with hub.lock:
    s = hub.sock
s.close()                                                # coupure réseau
check("relais reconnecté tout seul", until(lambda: hub.sock is not None and hub.sock is not s and len(out.list()) == 2, 8))

stop.set()
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
