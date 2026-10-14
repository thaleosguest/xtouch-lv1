"""Test étape 4 : TRACK + encodeurs -> gain X32, Rec tenu 1 s -> 48 V, via un FAUX x32-gain-recall (HTTP local).

    py tests/test_gain.py .
"""
import contextlib, io, json, socket, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, sys.argv[1])
import lv1_probe as P
import xtouch_probe as X
import xtouch_lv1_display as D

T0 = time.time()
# ── faux x32-gain-recall : In 1 = préampli 32 (EXP 17), In 2 stéréo = 33 + 34, In 3 sans X32
XGR = {"gains": [0.0] * 128, "phantom": [0] * 128}
XGR["gains"][32], XGR["gains"][33], XGR["gains"][34] = 10.0, 20.0, 20.0
POSTS = []
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
        while True:
            try:
                if not c.recv(65536): return
            except socket.timeout: continue
            except OSError: return
    threading.Thread(target=drain, daemon=True).start()
    send("/handshake", [("i", 1)])
    send("/Channels", [("i", 3)] + track("Kick", 0, 0) + track("Gtr", 0, 1) + track("Vx", 0, 2))
    lay = [("i", 0), ("i", 0), ("i", 1), ("s", "Ch 1-16"), ("i", 16)]
    for k in range(16): lay += [("i", 0), ("i", k)]
    send("/Notify/Layers", lay); send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
    time.sleep(6)
threading.Thread(target=server, daemon=True).start()

LCD, RINGS, LEDS = {}, {}, {}
class Cap(X.DryOut):
    def short(self, h, st, d1, d2=0):
        if time.time() - T0 > 4.6: return              # ignorer la remise à zéro finale
        if st == 0xB0 and 0x30 <= d1 <= 0x37: RINGS[(h, d1 - 0x30)] = d2
        if st == 0x90: LEDS[(h, d1)] = d2
    def long(self, h, data):
        if time.time() - T0 < 4.6: LCD[h] = bytes(data)
X.DryOut = Cap

def inject():
    def put(t, *ev):
        time.sleep(max(0, t - (time.time() - T0)))
        D.EVENTS.put(ev + (time.time(),))
    put(1.0, 0, 0xB0, 0x10, 0x01)                       # encodeur 1 hors mode gain : rien
    put(1.2, 1, 0x90, 0x28, 127); put(1.25, 1, 0x90, 0x28, 0)   # TRACK -> mode gain
    for k in range(4): put(1.5 + 0.01 * k, 0, 0xB0, 0x10, 0x01)  # +4 crans In 1 -> 12.0
    put(1.8, 0, 0xB0, 0x11, 0x43)                       # -3 crans In 2 (stéréo) -> 18.5 sur 33 ET 34
    put(1.9, 0, 0xB0, 0x12, 0x01)                       # In 3 : pas de préampli X32
    put(2.2, 0, 0x90, 0x00, 127); put(2.5, 0, 0x90, 0x00, 0)    # Rec bref : 48 V inchangé
    put(2.7, 0, 0x90, 0x01, 127); put(3.9, 0, 0x90, 0x01, 0)    # Rec tenu 1,2 s sur In 2 : 48 V ON (33, 34)
threading.Thread(target=inject, daemon=True).start()

sys.argv = ["x", "--dry-run", "--no-journal", "--host", "127.0.0.1", "--port", str(srv.getsockname()[1]),
            "--x32", "http://127.0.0.1:%d" % http.server_port, "--seconds", "4.8"]
with contextlib.redirect_stdout(io.StringIO()):
    D.main()

posts = [(p, d) for _, p, d in POSTS]
print("Envois à x32-gain-recall :", posts)
print("Couronnes :", {k: hex(v) for k, v in sorted(RINGS.items()) if v})
print("LED Rec :", {k: v for k, v in LEDS.items() if k[1] < 8 and v}, " LED TRACK :", LEDS.get((0, 0x28)))
want_g = {32: 12.0, 33: 18.5, 34: 18.5}
ok = all(XGR["gains"][i] == v for i, v in want_g.items())
ok = ok and XGR["phantom"][33] == 1 and XGR["phantom"][34] == 1 and XGR["phantom"][32] == 0
ok = ok and not any(d.get("idx") == 32 and p == "/api/phantom" for p, d in posts)
ok = ok and len([1 for p, d in posts if p == "/api/gain" and d["idx"] == 32]) <= 3     # crans regroupés
# en simulation, les tranches 1-8 (Extender à gauche) sont sur le port 1, la X-Touch (TRACK) sur le port 0
ok = ok and LEDS.get((0, 0x28)) == 127 and LEDS.get((1, 0x01)) == 127 and not LEDS.get((1, 0x00))
ok = ok and RINGS.get((1, 0)) == 0x24 and RINGS.get((1, 1)) == 0x25 and not RINGS.get((1, 2))
print("Gains finaux :", {i: XGR["gains"][i] for i in want_g})
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
