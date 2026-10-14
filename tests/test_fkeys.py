"""Test : F1..F8 -> User Keys 1..8 de la LV1 ; une User Key « Flip Sends » met aussi la X-Touch en sends on fader.

    py tests/test_fkeys.py .
"""
import contextlib, io, json, socket, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, sys.argv[1])
import lv1_probe as P
import xtouch_probe as X
import xtouch_lv1_display as D

T0 = time.time()
# ── faux x32-gain-recall : In 1 = préampli 32 (EXP 17), In 2 stéréo = 33 + 34, In 3 sans X32
# Règle de Joseph : jamais G et D en même temps (gain comme 48 V) : appui encodeur = L <-> R.
XGR = {"gains": [0.0] * 128, "phantom": [0] * 128}
XGR["gains"][32], XGR["gains"][33], XGR["gains"][34] = 10.0, 20.0, 20.0
POSTS = []
SETS = []
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        self._send({"connected": True, "gains": XGR["gains"], "phantom": XGR["phantom"],
                    "exp_map": {"32": 17, "33": 18, "34": 19}, "lv1_sources": {"1": [17], "2": [18, 19]}})
    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        POSTS.append((round(time.time() - T0, 2), self.path, d))
        if self.path == "/api/gain":
            XGR["gains"][d["idx"]] = d["db"]; self._send({"ok": True, "db": d["db"]})
        else:
            XGR["phantom"][d["idx"]] = 1 if d["on"] else 0; self._send({"ok": True})
http = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=http.serve_forever, daemon=True).start()

# ── fausse LV1
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0)); srv.listen(1)
def track(name, g, c):
    return [("s", name), ("i", g), ("i", c), ("d", 0.0), ("d", 0.0)] + [("i", 0)] * 12 + [("h", 0), ("d", 0.0)]
def server():
    c, _ = srv.accept(); c.settimeout(0.1)
    send = lambda a, args=(): c.sendall(P.frame(a, args))
    def drain():
        buf = b""
        while True:
            try:
                d = c.recv(65536)
            except socket.timeout: continue
            except OSError: return
            if not d: return
            buf += d
            pk, buf = P.split_frames(buf)
            for p in pk:
                a, args = P.osc_decode(p)
                if a.startswith("/Set"): SETS.append((a, [v for _, v in args]))
    threading.Thread(target=drain, daemon=True).start()
    send("/handshake", [("i", 1)])
    send("/Channels", [("i", 3)] + track("Kick", 0, 0) + track("Gtr", 0, 1) + track("Vx", 0, 2))
    lay = [("i", 0), ("i", 0), ("i", 1), ("s", "Ch 1-16"), ("i", 16)]
    for k in range(16): lay += [("i", 0), ("i", k)]
    send("/Notify/Layers", lay); send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
    aux = [("i", 24)]
    for k in range(8): aux += [("i", k), ("i", 2), ("s", "Fx %d" % (k + 1))]
    for k in range(16): aux += [("i", k), ("i", 25), ("s", "Mon %d" % (k + 1))]
    send("/Aux/Tracks", aux)
    send("/Notify/Aux/Send/Gain", [("i", 0), ("i", 0), ("i", 2), ("d", -10.0), ("T", True)])
    send("/Notify/Aux/Send/On", [("i", 0), ("i", 0), ("i", 2), ("T", True), ("T", True)])
    send("/Notify/UserKeyInfo", [("i", 0), ("s", "Fx 2"), ("s", "Flip Sends: MX1: Fx 2"), ("i", 1)])
    send("/Notify/UserKeyInfo", [("i", 1), ("s", "TB"), ("s", "Talkback"), ("i", 1)])
    send("/Notify/UserKeyInfo", [("i", 2), ("s", "User 3"), ("s", "User 3"), ("i", 0)])
    time.sleep(6)
threading.Thread(target=server, daemon=True).start()

LEDS = []
class Cap(X.DryOut):
    def short(self, h, st, d1, d2=0):
        if st == 0x90 and 0x36 <= d1 <= 0x3D and h == 0: LEDS.append((round(time.time() - T0, 1), d1, d2))
    def long(self, h, data): pass
X.DryOut = Cap

def inject():
    def put(t, *ev):
        time.sleep(max(0, t - (time.time() - T0)))
        D.EVENTS.put(ev + (time.time(),))
    def fader(t, v):
        put(t, 0, 0x90, 0x68, 127); put(t + 0.05, 0, 0xE0, v & 0x7F, v >> 7); put(t + 0.3, 0, 0x90, 0x68, 0)
    put(1.0, 1, 0x90, 0x36, 127); put(1.05, 1, 0x90, 0x36, 0)    # F1 -> User Key 1 = Flip Sends Fx 2
    fader(1.3, 7000)                                             # -> envoi In 1 -> Fx 2 (aux 1)
    put(1.9, 1, 0x90, 0x37, 127); put(1.95, 1, 0x90, 0x37, 0)    # F2 -> User Key 2 (Talkback) : mode inchangé
    fader(2.2, 8000)                                             # -> toujours un envoi vers Fx 2
    put(2.8, 1, 0x90, 0x36, 127); put(2.85, 1, 0x90, 0x36, 0)    # F1 -> fin du Flip Sends (User Key 1 à nouveau)
    fader(3.1, 9000)                                             # -> fader de piste
    put(3.7, 1, 0x90, 0x38, 127); put(3.75, 1, 0x90, 0x38, 0)    # F3 -> User Key 3 non assignée : envoyée quand même
threading.Thread(target=inject, daemon=True).start()

sys.argv = ["x", "--dry-run", "--no-journal", "--host", "127.0.0.1", "--port", str(srv.getsockname()[1]),
            "--x32", "aucun", "--seconds", "4.3"]
with contextlib.redirect_stdout(io.StringIO()):
    D.main()
seq = [(a.split("/Set/")[1], v[:3]) for a, v in SETS]
print("/Set envoyés :", seq)
keys = [v for a, v in SETS if a == "/Set/UserKey"]
print("LED F1 :", [(t, v) for t, d, v in LEDS if d == 0x36])
gains = [(a, v[:3]) for a, v in SETS if "Gain" in a]
ok = [k[:2] for k in keys] == [[0, True], [0, False], [1, True], [1, False], [0, True], [0, False], [2, True], [2, False]]
ok = ok and gains[0] == ("/Set/Aux/Send/Gain", [0, 0, 1]) and gains[-1][0] == "/Set/Track/Out/Gain"
ok = ok and any(a == "/Set/Aux/Send/Gain" for a, v in gains[1:-1]) and not any(a == "/Set/Track/Out/Gain" for a, v in gains[:-1])
on = [v for t, d, v in LEDS if d == 0x36]
ok = ok and 127 in on and on[-1] == 0
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
