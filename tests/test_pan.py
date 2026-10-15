"""Test : PAN = encodeurs sur le pan LV1 (/Set/Track/Pan), pan inconnu = encodeur sans effet, appui = centre.

    py tests/test_pan.py .
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
    send("/Notify/Track/Pan", [("i", 0), ("i", 0), ("d", -22.5), ("i", 1)])  # In 1 connu (L22.5 : échelle LV1 -45..+45) ; In 2 inconnu
    time.sleep(1.6 - (time.time() - T0))
    send("/Notify/Track/Pan", [("i", 0), ("i", 0), ("d", -22.5), ("i", 1)])  # retour tardif : ignoré
    time.sleep(6)
threading.Thread(target=server, daemon=True).start()

RINGS, LCD = {}, {}
class Cap(X.DryOut):
    def short(self, h, st, d1, d2=0):
        if time.time() - T0 < 2.9 and st == 0xB0 and 0x30 <= d1 <= 0x37: RINGS[(h, d1 - 0x30)] = d2
    def long(self, h, data):
        if time.time() - T0 < 2.9: LCD[h] = bytes(data)
X.DryOut = Cap

def inject():
    def put(t, *ev):
        time.sleep(max(0, t - (time.time() - T0)))
        D.EVENTS.put(ev + (time.time(),))
    put(1.2, 1, 0x90, 0x2A, 127); put(1.25, 1, 0x90, 0x2A, 0)    # PAN -> mode pan
    put(1.4, 0, 0xB0, 0x10, 0x03)                                # In 1 : -0.5 (L22,5) + 3 crans x 3 -> L14
    put(1.45, 0, 0xB0, 0x11, 0x01)                               # In 2 : pan inconnu -> rien
    put(2.0, 0, 0xB0, 0x10, 0x01)                                # +1 cran x 3 -> L11
    put(2.3, 0, 0x90, 0x20, 127); put(2.35, 0, 0x90, 0x20, 0)    # appui encodeur 1 -> centre
    put(2.6, 0, 0xB0, 0x10, 0x42)                                # -2 crans x 3 -> L6
threading.Thread(target=inject, daemon=True).start()

sys.argv = ["x", "--dry-run", "--no-journal", "--host", "127.0.0.1", "--port", str(srv.getsockname()[1]),
            "--x32", "aucun", "--seconds", "3.2"]
with contextlib.redirect_stdout(io.StringIO()):
    D.main()
pans = [round(v[2]) for a, v in SETS if a == "/Set/Track/Pan" and v[1] == 0]
print("/Set/Track/Pan In 1 (-45..+45) :", pans, " autres :", [v for a, v in SETS if a == "/Set/Track/Pan" and v[1] != 0])
print("Ligne du bas :", LCD.get(1, b"")[-60:], " couronne 1 :", hex(RINGS.get((1, 0), 0)))
ok = pans == [-14, -11, 0, -6] and not [v for a, v in SETS if a == "/Set/Track/Pan" and v[1] != 0]
ok = ok and b"L6 " in LCD.get(1, b"") and b"  ?" in LCD.get(1, b"") and RINGS.get((1, 0)) == 5
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
