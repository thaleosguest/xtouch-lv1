"""Test : X-Touch / Extender en RTP-MIDI direct (prise Ethernet, sans pilote ni relais).

Faux appareils AppleMIDI sur ce PC (esclaves, comme les X-Touch de Joseph : ils attendent l'invitation, et ne répondent
sur le port de données que si le PC parle depuis son port de contrôle + 1) : paquets, invitation, synchro d'horloge,
écrans / moteurs vers l'appareil, faders / toucher vers le pont, paquets perdus ou en retard, appareil éteint puis
rallumé, BY, arrêt propre. Sans matériel ni LV1.
Usage : py tests/test_rtpmidi.py <dossier du dépôt>
"""
import json
import os
import queue
import socket
import struct
import sys
import tempfile
import threading
import time

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rtpmidi as R                   # noqa: E402
from fake_rtpmidi import FakeDevice   # noqa: E402
import xtouch_probe as X              # noqa: E402
from surface.midi import SafeMidi     # noqa: E402

ok = True


def check(what, cond):
    global ok
    print("%-58s %s" % (what, "ok" if cond else "ÉCHEC"))
    ok = ok and bool(cond)


def until(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait()[:4])
        except queue.Empty:
            return out


# ─── Paquets (sans réseau) ────────────────────────────────────────────────────────────────────────────────────────

check("message court : longueur sur 4 bits", R.encode_commands([b"\xE0\x10\x40"]) == b"\x03\xE0\x10\x40")
lcd = bytes([0xF0, 0, 0, 0x66, 0x14, 0x12, 0]) + b"0123456789ABCDEF" + b"\xF7"
check("SysEx d'écran : longueur sur 12 bits", R.encode_commands([lcd]) == bytes([0x80, len(lcd)]) + lcd)
check("deux messages : temps delta 0 entre eux",
      R.encode_commands([b"\x90\x68\x7F", b"\xE0\x00\x40"]) == b"\x07\x90\x68\x7F\x00\xE0\x00\x40")
pk = R.rtp_packet(0x1234, 77, 0xAABBCCDD, [b"\xB0\x10\x01"])
check("en-tête RTP : version 2, marqueur, type 97", pk[:2] == b"\x80\xE1" and R.parse_rtp(pk)
      == (0x1234, 0xAABBCCDD, b"\x03\xB0\x10\x01"))
check("lecture : fader (pitch bend)", R.decode_commands(b"\x03\xE3\x05\x60") == [(0xE3, 0x05, 0x60)])
check("lecture : status courant et temps delta",
      R.decode_commands(b"\x0A\xE0\x01\x02\x00\x03\x04\x81\x00\x05\x06")
      == [(0xE0, 1, 2), (0xE0, 3, 4), (0xE0, 5, 6)])
check("lecture : 1er temps delta (drapeau Z)", R.decode_commands(b"\x24\x05\x90\x68\x7F") == [(0x90, 0x68, 0x7F)])
check("lecture : pression de canal (1 octet de donnée)",
      R.decode_commands(b"\x06\xD0\x1C\x00\x90\x10\x7F") == [(0xD0, 0x1C, 0), (0x90, 0x10, 0x7F)])
check("lecture : SysEx sauté, message suivant lu",
      R.decode_commands(bytes([0x80, 0x0C]) + b"\xF0\x00\x00\x66\x14\x01\xF7\x00\x90\x68\x00\x99")
      == [(0x90, 0x68, 0)])
check("lecture : SysEx en morceaux (F0…F0 puis F7…F7)",
      R.decode_commands(b"\x04\xF0\x01\x02\xF0") == [] and R.decode_commands(b"\x08\xF7\x03\xF7\x00\xB0\x3C\x01")
      == [(0xB0, 0x3C, 1)])
check("lecture : temps réel au milieu", R.decode_commands(b"\x08\xF8\x00\x90\x10\x7F\x00\x11\x00")
      == [(0x90, 0x10, 0x7F), (0x90, 0x11, 0)])
check("lecture : journal de retransmission ignoré",
      R.decode_commands(b"\x43\x90\x68\x7F\xA0\x12\x34\x56\x78") == [(0x90, 0x68, 0x7F)])
check("lecture : paquet coupé -> ce qui a pu être lu",
      R.decode_commands(b"\x07\x90\x68\x7F\x00\xE0\x01") == [(0x90, 0x68, 0x7F)] and R.decode_commands(b"") == []
      and R.decode_commands(b"\x02\x05\x06") == [])
check("paquets de session relus", R.parse_session(R.session_packet(b"IN", 7, 9, b"abc")) == (b"IN", (7, 9, b"abc"))
      and R.parse_session(R.ck_packet(9, 1, [10, 20])) == (b"CK", (9, 1, [10, 20, 0]))
      and R.parse_session(R.rs_packet(9, 0x4321)) == (b"RS", (9, 0x4321)) and R.parse_session(b"\xff\xffCK") is None)

tmp = tempfile.mkdtemp()
cfg = os.path.join(tmp, R.CONFIG)
check("réglages absents -> aucun appareil", R.load_config(cfg) == [])
with open(cfg, "w", encoding="utf-8") as f:
    json.dump({"devices": [{"name": "X-TOUCH", "ip": "192.168.1.38", "port": 5008},
                           {"name": "ailleurs", "ip": "8.8.8.8", "port": 5004},
                           {"name": "sans port", "ip": "192.168.1.39"},
                           {"name": "X-TOUCH-EXT", "ip": "192.168.1.39", "port": "5006"}]}, f)
check("réglages : adresses locales et entrées complètes seulement",
      R.load_config(cfg) == [{"name": "X-TOUCH", "ip": "192.168.1.38", "port": 5008},
                             {"name": "X-TOUCH-EXT", "ip": "192.168.1.39", "port": 5006}])
with open(cfg, "w", encoding="utf-8") as f:
    f.write("{pas du json")
check("réglages illisibles -> aucun appareil", R.load_config(cfg) == [])

# ─── Sessions ─────────────────────────────────────────────────────────────────────────────────────────────────────

P_MAIN, P_EXT, P_NONE = 15008, 15006, 15020
main_dev, ext_dev = FakeDevice(P_MAIN), FakeDevice(P_EXT, b"X-Touch-Ext")
ext_dev.powered = False                                  # Extender éteinte au départ
main_dev.start()
ext_dev.start()

logs = []
events = queue.Queue()
hub = R.RtpHub([{"name": "X-TOUCH (network)", "ip": "127.0.0.1", "port": P_MAIN},
                {"name": "X-TOUCH-EXT (network)", "ip": "127.0.0.1", "port": P_EXT},
                {"name": "X-TOUCH-EXT 2 (network)", "ip": "127.0.0.1", "port": P_NONE}],
               log=logs.append, ck_period=0.2, timeout=0.7, retry=0.3, invite_wait=0.15)


class UsbOut:                         # un port USB sans rapport, pour vérifier l'empilement
    def __init__(self):
        self.sent = []

    def list(self):
        return [(0, "Microsoft GS Wavetable Synth")]

    def open(self, i):
        return "usb%d" % i

    def short(self, h, st, d1, d2=0):
        self.sent.append((h, st, d1, d2))

    def long(self, h, data):
        self.sent.append((h, bytes(data)))

    def close(self, h):
        self.sent.append((h, "close"))


usb = UsbOut()
out = SafeMidi(R.RtpOut(usb, hub))
cin = R.RtpIn(None, hub, events)
check("avant le démarrage : ports USB seuls", out.list() == [(0, "Microsoft GS Wavetable Synth")])
hub.start()
check("X-Touch connectée (invitation + synchro)", until(lambda: len(out.list()) == 2))
check("port de données du PC = port de contrôle + 1",
      main_dev.data_addr and main_dev.data_addr[1] == main_dev.ctrl_addr[1] + 1 and main_dev.bad_data_port == 0)
check("Extender éteinte : ne bloque pas la X-Touch", [n for _i, n in out.list()][1:] == ["X-TOUCH (network)"])
main_idx, ext_idx = X.pick_ports(out.list(), None, None)
check("reconnue par pick_ports", main_idx == R.RTP_BASE and ext_idx is None)
check("nom annoncé par l'appareil et latence mesurée",
      until(lambda: hub.status()[0]["latency_ms"] is not None) and hub.status()[0]["peer"] == "X-Touch"
      and hub.status()[0]["latency_ms"] < 50)
check("synchro d'horloge répétée", until(lambda: main_dev.ck2 >= 3, 2))

ext_dev.powered = True
check("Extender allumée après coup : connectée", until(lambda: len(out.list()) == 3))
main_idx, ext_idx = X.pick_ports(out.list(), None, None)
check("X-Touch et Extender reconnues", (main_idx, ext_idx) == (R.RTP_BASE, R.RTP_BASE + 1))
h_main, h_ext, h_usb = out.open(main_idx), out.open(ext_idx), out.open(0)
in_main, in_ext = X.pick_ports(cin.list(), None, None)
cin.open(in_ext, 0)                                      # Extender à gauche : unité 0
cin.open(in_main, 1)

out.short(h_main, 0xE0, 0x10, 0x40)                      # moteur du fader 1
out.long(h_main, lcd)
out.short(h_ext, 0xD0, 0x1C)                             # vumètre
out.short(h_usb, 0x90, 1, 2)
check("moteur reçu par la X-Touch", until(lambda: b"\xE0\x10\x40" in main_dev.midi))
check("SysEx d'écran reçu entier", until(lambda: lcd in main_dev.midi))
check("vumètre (2 octets) reçu par l'Extender seule", until(lambda: ext_dev.midi == [b"\xD0\x1C"])
      and b"\xD0\x1C" not in main_dev.midi)
check("port USB : toujours servi par winmm", usb.sent == [("usb0", 0x90, 1, 2)] and not out.lost)
seqs = [struct.unpack(">H", p[2:4])[0] for p in main_dev.raw]
check("séquences RTP qui se suivent", len(seqs) == 2 and seqs[1] == (seqs[0] + 1) & 0xFFFF)

t0 = time.time()
out.short(h_main, 0xB0, 0x30, 0x01)
until(lambda: b"\xB0\x30\x01" in main_dev.midi)
check("aller en moins de 50 ms", time.time() - t0 < 0.05)

main_dev.send_midi(b"\x03\xE0\x05\x60")                  # fader de la X-Touch
ext_dev.send_midi(b"\x03\x90\x68\x7F")                   # toucher sur l'Extender
got = []
check("fader / toucher reçus par le pont", until(lambda: (got.extend(drain(events)) or True) and len(got) >= 2))
check("unités du pont respectées", sorted(got) == [(0, 0x90, 0x68, 0x7F), (1, 0xE0, 0x05, 0x60)])

base = main_dev.seq
main_dev.send_midi(b"\x03\xE0\x01\x10", seq=base + 1)
main_dev.send_midi(b"\x03\xE0\x03\x10", seq=base + 3)    # le paquet 2 est perdu
main_dev.send_midi(b"\x03\xE0\x02\x10", seq=base + 2)    # il arrive en retard : vieille position, jetée
main_dev.send_midi(b"\x03\xE0\x03\x10", seq=base + 3)    # doublon
main_dev.send_midi(b"\x03\xE0\x04\x10", seq=base + 4)
got = []
until(lambda: (got.extend(drain(events)) or True) and len(got) >= 3)
time.sleep(0.1)
got.extend(drain(events))
st = hub.status()[0]
check("paquet perdu compté, retard et doublon jetés", [g[2] for g in got] == [1, 3, 4] and st["lost"] == 1
      and st["late"] == 2 and any("perdu" in m for m in logs))

main_dev.send_midi(b"\x03\xE0\x08\x10", seq=0x7F00)      # sauts de séquence (comptés comme pertes)
main_dev.send_midi(b"\x03\xE0\x09\x10", seq=0xFEFF)
main_dev.send_midi(b"\x03\xE0\x0A\x10", seq=0xFFFE)      # puis retour à zéro
main_dev.send_midi(b"\x03\xE0\x0B\x10", seq=0xFFFF)
main_dev.send_midi(b"\x03\xE0\x0C\x10", seq=0)
got = []
until(lambda: (got.extend(drain(events)) or True) and len(got) >= 5)
check("séquence qui repasse par zéro", [g[2] for g in got] == [8, 9, 0x0A, 0x0B, 0x0C])

main_dev.d.sendto(b"\x80\xE1" + b"\0" * 10 + b"\x03\xE0\x7F\x7F", ("127.0.0.1", 9))   # rien ne doit planter
src = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
src.sendto(b"\xff\xffBY" + struct.pack(">III", 2, 0, 1), ("127.0.0.1", main_dev.data_addr[1]))
src.sendto(b"\x00garbage", ("127.0.0.1", main_dev.data_addr[1]))
src.sendto(b"\xff\xff", ("127.0.0.1", main_dev.ctrl_addr[1]))
time.sleep(0.2)
check("paquets parasites sans effet", len(out.list()) == 3 and hub.is_alive())

main_dev.powered = False                                 # X-Touch éteinte
check("X-Touch éteinte : port retiré", until(lambda: len(out.list()) == 2, 3))
check("Extender toujours là", dict(out.list()).get(R.RTP_BASE + 1) == "X-TOUCH-EXT (network)")
out.short(h_ext, 0x90, 0x10, 0x7F)
check("l'Extender reçoit encore", until(lambda: b"\x90\x10\x7F" in ext_dev.midi) and not out.lost)
out.short(h_main, 0xE0, 0, 0)
check("ancienne poignée refusée -> lost", out.lost is not None)
out.lost = None
try:
    out.open(R.RTP_BASE)
    refused = False
except OSError:
    refused = True
check("ouverture refusée tant qu'elle est éteinte", refused)

main_dev.powered = True
check("X-Touch rallumée : reconnectée toute seule", until(lambda: len(out.list()) == 3, 4))
out.short(h_main, 0xE0, 0, 0)
check("poignée d'avant toujours refusée", out.lost is not None)
out.lost = None
h_main = out.open(R.RTP_BASE)
main_dev.midi.clear()
out.short(h_main, 0xE1, 0x22, 0x33)
check("nouvelle poignée : envoi reçu", until(lambda: b"\xE1\x22\x33" in main_dev.midi))
cin.close_all()
cin.open(R.RTP_BASE, 1)
main_dev.send_midi(b"\x03\x90\x69\x7F")
got = []
check("entrée rouverte : toucher reçu", until(lambda: (got.extend(drain(events)) or True) and got
                                              == [(1, 0x90, 0x69, 0x7F)]))

ext_dev.bye()
check("BY de l'Extender : port retiré tout de suite", until(lambda: len(out.list()) == 2, 0.3))
check("puis invitée de nouveau", until(lambda: len(out.list()) == 3, 3))

by_before = (main_dev.by, ext_dev.by)
hub.stop()
check("arrêt : BY envoyé aux deux appareils",
      until(lambda: main_dev.by >= by_before[0] + 2 and ext_dev.by >= by_before[1] + 2, 1))
check("après l'arrêt : plus de port RTP", out.list() == [(0, "Microsoft GS Wavetable Synth")] and not hub.is_alive())
check("appareil absent : un seul avertissement", sum("X-TOUCH-EXT 2" in m for m in logs) == 1)

main_dev.stop = ext_dev.stop = True
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
