"""Test : le pont complet avec X-Touch + Extender par Ethernet (RTP-MIDI direct), sans USB.

Fausse LV1 + deux faux appareils RTP-MIDI sur ce PC, pont réel (pas --dry-run) : ports reconnus au démarrage, noms des
canaux sur les écrans (Extender à gauche = tranches 1-8), fader de la X-Touch -> LV1, appareil éteint puis rallumé
(« X-Touch perdue » / « reconnectée », écrans renvoyés), arrêt propre (BY). Sans matériel.
Usage : py tests/test_rtpmidi_pont.py <dossier du dépôt>
"""
import contextlib
import io
import os
import socket
import sys
import threading
import time

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lv1_probe as P                     # noqa: E402
import xtouch_lv1_display as D            # noqa: E402
from fake_rtpmidi import FakeDevice       # noqa: E402

import rtpmidi as R                       # noqa: E402


class FastHub(R.RtpHub):                  # mêmes sessions, délais courts pour le test
    def __init__(self, devices, log=print):
        super().__init__(devices, log=log, ck_period=0.3, timeout=1.0, retry=0.5, invite_wait=0.2)


R.RtpHub = FastHub
ok, why = True, []


def check(name, cond):
    global ok
    print("%-58s %s" % (name, "ok" if cond else "ÉCHEC"))
    if not cond:
        why.append(name)
    ok = ok and bool(cond)


def until(cond, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def track(name, g, c):
    return [("s", name), ("i", g), ("i", c), ("d", 0.0), ("d", 0.0)] + [("i", 0)] * 12 + [("h", 0), ("d", 0.0)]


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0))
srv.listen(2)
SETS = []


def lv1():
    c, _ = srv.accept()
    c.settimeout(0.1)

    def send(a, args=()):
        c.sendall(P.frame(a, args))

    def rx():
        buf = b""
        while True:
            try:
                d = c.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not d:
                return
            pk, buf = P.split_frames(buf + d)
            for p in pk:
                a, args = P.osc_decode(p)
                if a.startswith("/Set"):
                    SETS.append((a, args))
    threading.Thread(target=rx, daemon=True).start()
    send("/handshake", [("i", 1)])
    chans = [("i", 16)]
    for k in range(16):
        chans += track("Kick" if k == 0 else "Bass" if k == 8 else "Ch%d" % (k + 1), 0, k)
    send("/Channels", chans)
    lay = [("i", 0), ("i", 0), ("i", 1), ("s", "Ch 1-16"), ("i", 16)]
    for k in range(16):
        lay += [("i", 0), ("i", k)]
    send("/Notify/Layers", lay)
    send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
    for k in range(16):
        send("/Notify/UserKeyInfo", [("i", k), ("s", "None"), ("s", "None"), ("i", 0)])
    while True:
        try:
            send("/ping", [("h", 1), ("i", 1)])
        except OSError:
            return
        time.sleep(0.5)


threading.Thread(target=lv1, daemon=True).start()

P_MAIN, P_EXT = 15108, 15106
main_dev, ext_dev = FakeDevice(P_MAIN), FakeDevice(P_EXT, b"X-Touch-Ext")
main_dev.start()
ext_dev.start()


def texts(dev, dev_id):
    """Texte des SysEx d'écran Mackie reçus par l'appareil."""
    head = bytes([0xF0, 0, 0, 0x66, dev_id, 0x12])
    return b" ".join(m[7:-1] for m in list(dev.midi) if m[:6] == head)


sys.argv = ["x", "--no-journal", "--host", "127.0.0.1", "--port", str(srv.getsockname()[1]), "--x32", "aucun",
            "--reaper", "aucun", "--sans-reaper-lv1", "--sans-gain-recall", "--sans-cadre", "--sans-usb",
            "--rtpmidi", "127.0.0.1:%d,127.0.0.1:%d" % (P_MAIN, P_EXT), "--seconds", "60"]
out = io.StringIO()
result = {}


def bridge():
    with contextlib.redirect_stdout(out):
        result["code"] = D.main()


th = threading.Thread(target=bridge, daemon=True)
th.start()

check("les deux appareils invités par le pont", until(lambda: main_dev.data_addr and ext_dev.data_addr))
check("Extender (à gauche) : « Kick » sur son écran", until(lambda: b"Kick" in texts(ext_dev, 0x15)))
check("X-Touch : « Bass » (tranche 9) sur son écran", until(lambda: b"Bass" in texts(main_dev, 0x14)))

main_dev.send_midi(b"\x03\x90\x68\x7F")                   # toucher du fader 1 de la X-Touch (tranche 9)
main_dev.send_midi(b"\x03\xE0\x00\x40")                   # fader à mi-course
check("fader de la X-Touch -> LV1 (canal 9)",
      until(lambda: any(a == "/Set/Track/Out/Gain" and [v for _t, v in args][:2] == [0, 8] for a, args in SETS)))
main_dev.send_midi(b"\x03\x90\x68\x00")

time.sleep(0.5)
ext_dev.powered = False                                   # Extender éteinte, sans geste ni vumètre à ce moment-là
check("Extender éteinte : « X-Touch perdue »", until(lambda: "X-Touch perdue" in out.getvalue(), 15))
ext_dev.midi.clear()
ext_dev.powered = True
check("Extender rallumée : « X-Touch reconnectée »", until(lambda: "X-Touch reconnectée" in out.getvalue(), 30))
check("écrans renvoyés à l'Extender", until(lambda: b"Kick" in texts(ext_dev, 0x15)))

by = (main_dev.by, ext_dev.by)
D.STOP.set()
th.join(10)
check("fin normale", result.get("code") == 0 and "Arrêté" in out.getvalue())
check("BY envoyé aux deux appareils", until(lambda: main_dev.by >= by[0] + 2 and ext_dev.by >= by[1] + 2, 1))
if not ok:
    print(out.getvalue()[-3000:])
print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
