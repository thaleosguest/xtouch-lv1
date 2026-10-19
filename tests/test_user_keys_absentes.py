"""Test : la LV1 envoie canaux et couches mais PAS ses User Keys (journal 113310 du 19/10 : FLIP sans effet,
« aucune User Key Flip AB », alors que la User Key 16 = Flip A/B).
- 1re connexion : canaux + couches, pas de User Keys -> le pont se reconnecte (l'état n'est pas complet) ;
- 2e connexion : tout, dont la User Key 16 « Flip AB Input channel » -> FLIP de la X-Touch envoie /Set/UserKey 15 ;
- limite : une LV1 qui n'enverrait JAMAIS ses User Keys est acceptée après KEYS_TRIES reconnexions (pas de boucle).

    py tests/test_user_keys_absentes.py .
"""
import contextlib, io, socket, sys, threading, time
sys.path.insert(0, sys.argv[1])
import lv1_probe as P
import xtouch_probe as X
import xtouch_lv1_display as D

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

# ── limite de reconnexions (logique seule)
link = D.LV1Link(D.LV1State())
base = {"/Channels", "/Notify/Layers"}
check("sans User Keys : incomplet", not link.state_complete(base))
check("avec User Keys : complet", link.state_complete(base | {"/Notify/UserKeyInfo"}))
check("sans couches : incomplet", not link.state_complete({"/Channels", "/Notify/UserKeyInfo"}))
link.keys_missing = D.LV1Link.KEYS_TRIES
check("après KEYS_TRIES reconnexions : accepté sans User Keys", link.state_complete(base))

# ── scénario réel, par le réseau
D.LV1Link.STATE_ASK, D.LV1Link.STATE_GIVEUP = 0.4, 1.0
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0)); srv.listen(2)
RECU = []                                            # (n° de connexion, adresse, args) reçus par la fausse LV1


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
                a, args = P.osc_decode(p)
                if a.startswith(("/Get", "/Set")): RECU.append((n, a, [v for _, v in args]))
    threading.Thread(target=rx, daemon=True).start()
    send("/handshake", [("i", 1)])
    send("/Channels", [("i", 1)] + track("Kick", 0, 0))
    lay = [("i", 0), ("i", 0), ("i", 1), ("s", "Ch 1-16"), ("i", 16)]
    for k in range(16): lay += [("i", 0), ("i", k)]
    send("/Notify/Layers", lay); send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
    if n == 2:                                       # 2e connexion : les User Keys arrivent enfin
        for k in range(16):
            func = "Flip AB Input channel" if k == 15 else "None"
            send("/Notify/UserKeyInfo", [("i", k), ("s", "FlipAB" if k == 15 else "None"), ("s", func), ("i", int(k == 15))])
    for _ in range(60):
        try: send("/ping", [("h", 1), ("i", 1)])
        except OSError: return
        time.sleep(0.1)


def server():
    serve(1)
    serve(2)
threading.Thread(target=server, daemon=True).start()


def flip():                                          # FLIP de la X-Touch, une fois la 2e connexion faite
    t_end = time.time() + 8
    while time.time() < t_end and not any(n == 2 for n, _, _ in RECU):
        time.sleep(0.05)
    time.sleep(0.5)                                  # le temps que les User Keys soient lues
    D.EVENTS.put((1, 0x90, D.NOTE_FLIP, 127, time.time()))
    D.EVENTS.put((1, 0x90, D.NOTE_FLIP, 0, time.time()))
threading.Thread(target=flip, daemon=True).start()


class Muet(X.DryOut):
    def short(self, h, st, d1, d2=0): pass
    def long(self, h, data): pass
X.DryOut = Muet

sys.argv = ["x", "--dry-run", "--no-journal", "--x32", "aucun", "--host", "127.0.0.1",
            "--port", str(srv.getsockname()[1]), "--seconds", "7"]
out = io.StringIO()
with contextlib.redirect_stdout(out):
    D.main()
texte = out.getvalue()
user_keys = [(n, a, v) for n, a, v in RECU if a == "/Set/UserKey"]
print("Connexions :", texte.count("LV1 connectée"), "| /Set/UserKey envoyés :", user_keys)
check("reconnexion faute de User Keys", texte.count("LV1 connectée") == 2 and "n'envoie pas son état" in texte)
check("FLIP -> User Key 16 (index 15) sur la 2e connexion",
      user_keys[:2] == [(2, "/Set/UserKey", [15, True]), (2, "/Set/UserKey", [15, False])])
print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
