"""Test : sends on fader. SEND -> choix de l'aux (faders bloqués), Select -> faders = envois (/Set/Aux/Send/Gain),
Mute = envoi on/off, SEND -> retour aux faders des canaux.

    py tests/test_sends.py .
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
    time.sleep(6)
threading.Thread(target=server, daemon=True).start()

LCD, MOTOR = {}, {}
class Cap(X.DryOut):
    def short(self, h, st, d1, d2=0):
        if st & 0xF0 == 0xE0: MOTOR[(h, st & 0x0F, round(time.time() - T0, 1))] = d1 | (d2 << 7)
    def long(self, h, data):
        if time.time() - T0 < 4.6: LCD.setdefault(round(time.time() - T0, 1), []).append(bytes(data))
X.DryOut = Cap

def inject():
    def put(t, *ev):
        time.sleep(max(0, t - (time.time() - T0)))
        D.EVENTS.put(ev + (time.time(),))
    put(1.0, 0, 0x90, 0x68, 127)                                  # toucher fader 1 (le toucher est connu)
    put(1.05, 0, 0xE0, 0x00, 0x30); put(1.1, 0, 0x90, 0x68, 0)    # fader 1 normal -> /Set/Track/Out/Gain
    put(1.5, 1, 0x90, 0x29, 127); put(1.55, 1, 0x90, 0x29, 0)    # SEND -> choix
    put(1.7, 0, 0x90, 0x68, 127); put(1.75, 0, 0xE0, 0x10, 0x30); put(1.8, 0, 0x90, 0x68, 0)  # fader bloqué
    put(1.9, 0, 0x90, 0x10, 127); put(1.95, 0, 0x90, 0x10, 0)    # Mute bloqué pendant le choix
    put(2.1, 0, 0x90, 0x1A, 127); put(2.15, 0, 0x90, 0x1A, 0)    # Select tranche 3 -> aux 2 (Fx 3)
    put(2.6, 0, 0x90, 0x68, 127); put(2.65, 0, 0xE0, 0x00, 0x40); put(3.0, 0, 0x90, 0x68, 0)  # envoi In1 -> Fx3
    put(3.3, 0, 0x90, 0x10, 127); put(3.35, 0, 0x90, 0x10, 0)    # Mute tranche 1 -> envoi OFF
    put(3.6, 1, 0x90, 0x29, 127); put(3.65, 1, 0x90, 0x29, 0)    # SEND -> retour
    put(3.9, 0, 0x90, 0x69, 127); put(3.95, 0, 0xE1, 0x00, 0x50); put(4.3, 0, 0x90, 0x69, 0)  # fader 2 normal
threading.Thread(target=inject, daemon=True).start()

sys.argv = ["x", "--dry-run", "--no-journal", "--host", "127.0.0.1", "--port", str(srv.getsockname()[1]),
            "--x32", "aucun", "--seconds", "4.8"]
with contextlib.redirect_stdout(io.StringIO()):
    D.main()
kinds = [(a, v[:3]) for a, v in SETS]
print("/Set envoyés :", [(a.split("/Set/")[1], v) for a, v in kinds])
picks = [v for t, d in sorted(LCD.items()) if 1.4 < t < 2.2 for v in d if b"Fx 1" in v]
print("Écran pendant le choix :", picks[0][5:60] if picks else None)
ok = kinds[0][0] == "/Set/Track/Out/Gain" and kinds[0][1][:2] == [0, 0]
ok = ok and all(a != "/Set/Track/Out/Gain" or v[:2] != [0, 0] for a, v in kinds[1:])   # rien pendant le choix
ok = ok and any(a == "/Set/Aux/Send/Gain" and v == [0, 0, 2] for a, v in kinds)
ok = ok and ("/Set/Aux/Send/On", [0, 0, 2]) in kinds and [v for a, v in SETS if a == "/Set/Aux/Send/On"][0][3] is False
ok = ok and kinds[-1][0] == "/Set/Track/Out/Gain" and kinds[-1][1][:2] == [0, 1]
ok = ok and not any(a == "/Set/Track/Out/Mute" for a, v in kinds)
ok = ok and bool(picks)
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
