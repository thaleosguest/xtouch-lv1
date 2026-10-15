"""Test : transport X-Touch -> Reaper (OSC UDP) contre une fausse LV1 et un faux Reaper.
PLAY / STOP / REC / CYCLE / CLICK, ◄◄ tenu, MARKER seul = marqueur, MARKER + flèche, ZOOM + flèches, jog,
LED PLAY allumée par le retour /play 1 de Reaper."""
import contextlib, io, socket, sys, threading, time
sys.path.insert(0, sys.argv[1])
import lv1_probe as P
import xtouch_probe as X
import xtouch_lv1_display as D
import reaper_link as R

# ── fausse LV1 (juste de quoi se connecter)
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0)); srv.listen(1)
T0 = time.time()

def lv1():
    c, _ = srv.accept()
    c.sendall(P.frame("/handshake", [("i", 1)]))
    time.sleep(4)
    c.close()
threading.Thread(target=lv1, daemon=True).start()

# ── faux Reaper : reçoit les commandes, renvoie /play 1 après PLAY
rp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); rp.bind(("127.0.0.1", 0)); rp.settimeout(0.2)
fb = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); fb.bind(("127.0.0.1", 0))
FB_PORT = fb.getsockname()[1]; fb.close()           # port libre pour les retours (le pont s'y attache)
got = []

def reaper():
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while time.time() - T0 < 4:
        try:
            data, _ = rp.recvfrom(4096)
        except socket.timeout:
            continue
        a, args = P.osc_decode(data)
        got.append((a, [v for _t, v in args]))
        if a == "/play":
            tx.sendto(P.osc_encode("/play", [("f", 1.0)]), ("127.0.0.1", FB_PORT))
threading.Thread(target=reaper, daemon=True).start()

LEDS = {}
class Cap(X.DryOut):
    def short(self, h, st, d1, d2=0):
        if st == 0x90: LEDS[(h, d1)] = d2
    def long(self, h, data): pass
X.DryOut = Cap

def inject():
    def put(t, *ev):
        time.sleep(max(0, t - (time.time() - T0)))
        D.EVENTS.put(ev + (time.time(),))
    def tap(t, note):
        put(t, 1, 0x90, note, 127); put(t + 0.03, 1, 0x90, note, 0)
    tap(1.0, D.NOTE_PLAY)
    tap(1.2, D.NOTE_STOP)
    tap(1.3, D.NOTE_RECORD)
    tap(1.4, D.NOTE_CYCLE)
    tap(1.5, D.NOTE_CLICK)
    put(1.6, 1, 0x90, D.NOTE_REW, 127); put(1.8, 1, 0x90, D.NOTE_REW, 0)          # ◄◄ tenu
    tap(1.9, D.NOTE_MARKER)                                                       # MARKER seul = poser
    put(2.0, 1, 0x90, D.NOTE_MARKER, 127); tap(2.05, D.NOTE_RIGHT); put(2.15, 1, 0x90, D.NOTE_MARKER, 0)
    tap(2.2, D.NOTE_ZOOM); tap(2.3, D.NOTE_LEFT); tap(2.4, D.NOTE_UP); tap(2.5, D.NOTE_ZOOM)
    put(2.6, 1, 0xB0, D.CC_JOG, 0x02)                                             # jog +2 (sans --clic-lv1)
    put(2.7, 1, 0xB0, D.CC_JOG, 0x41)                                             # jog -1
threading.Thread(target=inject, daemon=True).start()

sys.argv = ["x", "--dry-run", "--no-journal", "--x32", "aucun", "--host", "127.0.0.1",
            "--port", str(srv.getsockname()[1]), "--reaper", "127.0.0.1:%d:%d" % (rp.getsockname()[1], FB_PORT),
            "--seconds", "3.2"]
with contextlib.redirect_stdout(io.StringIO()):
    D.main()
print("Reçu par Reaper :", got)
acts = [v[0] for a, v in got if a == "/action"]
ok = [a for a, _ in got[:5]] == ["/play", "/stop", "/record", "/repeat", "/click"]
ok = ok and ("/rewind", [1.0]) in got and ("/rewind", [0.0]) in got
ok = ok and acts[:4] == [R.ACT_ADD_MARKER, R.ACT_NEXT_MARKER, R.ACT_ZOOM_OUT_H, R.ACT_ZOOM_IN_V]
ok = ok and acts[4:] == [R.ACT_JOG_FWD, R.ACT_JOG_FWD, R.ACT_JOG_BACK]
ok = ok and acts.count(R.ACT_ADD_MARKER) == 1                     # MARKER + flèche : pas de marqueur posé
play = [v for (h, n), v in LEDS.items() if n == D.NOTE_PLAY]
ok = ok and play == [127]                                           # LED PLAY = retour /play 1 de Reaper
print("LED PLAY :", play)
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
