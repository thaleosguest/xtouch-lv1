"""Test étape 1 : faders X-Touch -> LV1 contre une fausse LV1, toucher simulé."""
import socket, sys, threading, time
sys.path.insert(0, sys.argv[1]); ARGS = sys.argv[2:]
import lv1_probe as P
import xtouch_probe as X
import xtouch_lv1_display as D

# ── fausse LV1
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0)); srv.listen(1)
PORT = srv.getsockname()[1]
got = []
T0 = time.time()

def track(name, g, c, fader):
    return [("s", name), ("i", g), ("i", c), ("d", fader), ("d", 0.0)] + [("i", 0)] * 12 + [("h", 0), ("d", 0.0)]

def server():
    c, _ = srv.accept(); c.settimeout(0.1)
    send = lambda a, args=(): c.sendall(P.frame(a, args))
    def rx():
        buf = b""
        while True:
            try: d = c.recv(65536)
            except socket.timeout: continue
            except OSError: return
            if not d: return
            buf += d
            pk, buf = P.split_frames(buf)
            for p in pk:
                a, args = P.osc_decode(p)
                if a.startswith("/Set"):
                    got.append((round(time.time() - T0, 2), a, args))
    threading.Thread(target=rx, daemon=True).start()
    time.sleep(0.1)
    send("/handshake", [("i", 1)])
    send("/Channels", [("i", 3)] + track("Ch1", 0, 0, -144.0) + track("Kick", 0, 1, -20.0) + track("Snare", 0, 2, -5.0))
    lay = [("i", 0), ("i", 0), ("i", 1), ("s", "Ch 1-16"), ("i", 16)]
    for k in range(16): lay += [("i", 0), ("i", k)]
    send("/Notify/Layers", lay); send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
    time.sleep(1.0 - (time.time() - T0))
    send("/Notify/Track/Out/Mute", [("i", 0), ("i", 2), ("i", 1), ("T", True)])       # mute fait sur l'écran (In 3)
    send("/Notify/Track/Out/Mute", [("i", 13), ("i", 0), ("i", 1), ("T", True)])      # groupe de mute : ignoré
    time.sleep(1.55 - (time.time() - T0))
    send("/Notify/Track/Out/Gain", [("i", 0), ("i", 1), ("d", -20.0), ("T", True)])   # retour tardif ancienne valeur
    time.sleep(2.7 - (time.time() - T0))
    send("/Notify/Track/Out/Gain", [("i", 0), ("i", 1), ("d", -10.0), ("T", True)])   # après : le moteur doit suivre
    time.sleep(3.5)
    c.close()
threading.Thread(target=server, daemon=True).start()

# ── capture des sorties MIDI
pb_out = []
ECHO = "--echo" in sys.argv
NOTOUCH = "--notouch" in sys.argv
HOST_LAST = {}
SNAPBACK = "--snapback" in sys.argv
LEDS = []
class Cap(X.DryOut):
    def short(self, h, st, d1, d2=0):
        if st == 0x90 and d1 <= 0x1F and h == 1:
            LEDS.append((round(time.time() - T0, 2), hex(d1), d2))
        if st & 0xF0 == 0xE0:
            HOST_LAST[(h, st & 0x0F)] = d1 | (d2 << 7)
        if st & 0xF0 == 0xE0 and h == 0 and (st & 0x0F) == 1:
            pb_out.append((round(time.time() - T0, 2), d1 | (d2 << 7)))
        if st & 0xF0 == 0xE0 and ECHO:
            D.EVENTS.put((h, st, d1, d2, time.time()))   # écho moteur simulé
    def long(self, h, data): pass
X.DryOut = Cap

def inject():
    def put(t, *ev):
        time.sleep(max(0, t - (time.time() - T0)))
        D.EVENTS.put(ev + (time.time(),))
    put(0.5, 0, 0x90, 0x11, 127); put(0.55, 0, 0x90, 0x11, 0)    # Mute tranche 2 (In 2)
    put(0.7, 0, 0x90, 0x08, 127); put(0.75, 0, 0x90, 0x08, 0)    # Solo tranche 1 (In 1)
    put(1.2, 0, 0x90, 0x11, 127); put(1.25, 0, 0x90, 0x11, 0)    # Mute tranche 2 : démute
    put(1.4, 0, 0x90, 0x00, 127)                                 # Rec : pas de fonction
threading.Thread(target=inject, daemon=True).start()

sys.argv = ["x", "--dry-run", "--host", "127.0.0.1", "--port", str(PORT), "--seconds", "3.3"]
D.main()
print("\n/Set envoyés à la LV1 :")
for g in got: print("  ", g[0], g[1], P.short_args(g[2]))
print("LED (instant, note, état) hors initialisation :", [l for l in LEDS if l[0] > 0.3])
