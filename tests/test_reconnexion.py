"""Test : la LV1 accepte la connexion mais n'envoie pas son état (vu le 15/10 après un redémarrage de la LV1).
Le pont doit redemander, puis se reconnecter, et récupérer couches et couleurs à la 2e connexion.

    py tests/test_reconnexion.py .
"""
import contextlib, io, socket, sys, threading, time
sys.path.insert(0, sys.argv[1])
import lv1_probe as P
import xtouch_probe as X
import xtouch_lv1_display as D

D.LV1Link.STATE_ASK, D.LV1Link.STATE_GIVEUP = 0.5, 1.2
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0)); srv.listen(2)
GETS = []


def track(name, g, c):
    return [("s", name), ("i", g), ("i", c), ("d", 0.0), ("d", 0.0)] + [("i", 0)] * 12 + [("h", 0), ("d", 0.0)]


def serve(n):
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
                a, _ = P.osc_decode(p)
                if a.startswith("/Get"): GETS.append((n, a))
    threading.Thread(target=rx, daemon=True).start()
    send("/handshake", [("i", 1)])
    if n == 1:                       # LV1 qui charge encore : rien que des ping
        for _ in range(40):
            try: send("/ping", [("h", 1), ("i", 1)])
            except OSError: return
            time.sleep(0.1)
        return
    send("/Channels", [("i", 1)] + track("Kick", 0, 0))
    send("/Notify/TrackColor", [("i", 0), ("i", 0), ("i", 13), ("f", 0.0588), ("f", 0.6353), ("f", 0.6706)])
    lay = [("i", 0), ("i", 0), ("i", 1), ("s", "Ch 1-16"), ("i", 16)]
    for k in range(16): lay += [("i", 0), ("i", k)]
    send("/Notify/Layers", lay); send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
    time.sleep(5)


def server():
    serve(1)
    serve(2)
threading.Thread(target=server, daemon=True).start()


class Cap(X.DryOut):
    def short(self, h, st, d1, d2=0): pass
    def long(self, h, data): pass
X.DryOut = Cap

sys.argv = ["x", "--dry-run", "--no-journal", "--x32", "aucun", "--host", "127.0.0.1",
            "--port", str(srv.getsockname()[1]), "--seconds", "6.5"]
out = io.StringIO()
with contextlib.redirect_stdout(out):
    D.main()
text = out.getvalue()
print("\n".join(l for l in text.splitlines() if "LV1" in l or "Couche" in l))
print("Demandes /Get :", GETS)
ok = text.count("LV1 connectée") == 2 and "n'envoie pas son état" in text and "Couche affichée : Ch 1-16" in text
ok = ok and GETS.count((1, "/Get/Layers")) == 2          # demande initiale + nouvelle demande
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
