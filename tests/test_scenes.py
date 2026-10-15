"""Test : scènes LV1 <-> marqueurs Reaper (côté pont). Fausse LV1 : liste de scènes, scène courante à la connexion
(ne doit PAS être transmise), état complet renvoyé (même scène : pas transmise), rappel d'une autre scène (transmis
avec son nom), même scène rappelée à nouveau hors état complet (transmise). Puis Reaper signale un marqueur franchi
(fichier reaper_to_lv1.txt) -> /Set/CurSceneIndex avec l'index de la scène de ce nom."""
import contextlib, io, os, socket, sys, tempfile, threading, time
sys.path.insert(0, sys.argv[1])
import lv1_probe as P
import xtouch_probe as X
import xtouch_lv1_display as D
import reaper_scenes as RS

TMP = tempfile.mkdtemp()
RS.FOLDER = TMP
seen = []                                         # lignes successives de lv1_to_reaper.txt
got = []
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0)); srv.listen(1)
T0 = time.time()

def track(name, g, c):
    return [("s", name), ("i", g), ("i", c), ("d", 0.0), ("d", 0.0)] + [("i", 0)] * 12 + [("h", 0), ("d", 0.0)]

def at(t):
    time.sleep(max(0, t - (time.time() - T0)))

def lv1():
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
                if a.startswith("/Set"): got.append((a, [v for _t, v in args]))
    threading.Thread(target=rx, daemon=True).start()
    send("/handshake", [("i", 1)])
    send("/Channels", [("i", 1)] + track("Ch1", 0, 0))
    send("/Notify/Scene/Name", [("s", "Intro")])
    send("/Notify/SceneList", [("i", 3), ("i", 0), ("s", "Intro"), ("i", 1), ("s", "Chanson 1"), ("i", 2), ("s", "Rappel")])
    send("/Notify/CurSceneIndex", [("i", 0)])                         # connexion : pas transmis
    at(1.0); send("/Channels", [("i", 1)] + track("Ch1", 0, 0))      # état complet (Flip A/B)
    send("/Notify/CurSceneIndex", [("i", 0)])                         # même scène dans l'état : pas transmis
    at(3.2); send("/Notify/CurSceneIndex", [("i", 1)])                # rappel « Chanson 1 » : transmis
    send("/Notify/Scene/Name", [("s", "Chanson 1")])
    at(3.8); send("/Notify/CurSceneIndex", [("i", 1)])                # même scène rappelée à nouveau : transmis
    at(6)
threading.Thread(target=lv1, daemon=True).start()

def watch():
    path, last = os.path.join(TMP, RS.TO_REAPER), None
    while time.time() - T0 < 5.5:
        try:
            line = open(path, encoding="utf-8").read()
        except OSError:
            line = None
        if line and line != last:
            seen.append(line.rstrip("\n").split("\t")); last = line
        time.sleep(0.02)
threading.Thread(target=watch, daemon=True).start()

def reaper():
    at(4.5)
    with open(os.path.join(TMP, RS.TO_LV1), "w", encoding="utf-8") as f:
        f.write("123\t-1\tRappel\n")                                   # lecture : marqueur « Rappel » franchi
threading.Thread(target=reaper, daemon=True).start()

class Cap(X.DryOut):
    def short(self, *a): pass
    def long(self, *a): pass
X.DryOut = Cap
sys.argv = ["x", "--dry-run", "--no-journal", "--x32", "aucun", "--host", "127.0.0.1",
            "--port", str(srv.getsockname()[1]), "--reaper", "127.0.0.1:9:0", "--seconds", "5.5"]
with contextlib.redirect_stdout(io.StringIO()):
    D.main()
print("Vers Reaper :", seen)
print("/Set vers la LV1 :", got)
ok = [(s[1], s[2]) for s in seen] == [("1", "Chanson 1"), ("1", "Chanson 1")] and len({s[0] for s in seen}) == 2
ok = ok and ("/Set/CurSceneIndex", [2]) in got
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
