"""Test étape 3 : ◄ BANK ► de la X-Touch -> couche affichée (locale), contre une fausse LV1.

    py tests/test_banque.py .

Vérifie : couche suivante / précédente, saut des couches vides, arrêt au bout, retour à la couche
de la LV1 quand elle envoie /Notify/CurrentLayer, banque ignorée pendant qu'un fader est tenu, et
que Mute agit sur la piste de la couche affichée.
"""
import io, socket, sys, threading, time, contextlib
sys.path.insert(0, sys.argv[1])
import lv1_probe as P
import xtouch_probe as X
import xtouch_lv1_display as D

srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0)); srv.listen(1)
PORT = srv.getsockname()[1]
got = []
T0 = time.time()


def track(name, g, c):
    return [("s", name), ("i", g), ("i", c), ("d", 0.0), ("d", 0.0)] + [("i", 0)] * 12 + [("h", 0), ("d", 0.0)]


def layer(name, first):
    out = [("s", name), ("i", 16)]
    for k in range(16):
        out += [("i", -1), ("i", -1)] if first is None else [("i", 0), ("i", first + k)]
    return out


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
                    got.append((round(time.time() - T0, 2), a, P.short_args(args)))
    threading.Thread(target=rx, daemon=True).start()
    time.sleep(0.1)
    send("/handshake", [("i", 1)])
    chans = [("i", 64)]
    for k in range(64):
        chans += track("In %d" % (k + 1), 0, k)
    send("/Channels", chans)
    lay = [("i", 0), ("i", 0), ("i", 8)]
    for name, first in (("Ch 1-16", 0), ("Ch 17-32", 16), ("Ch 33-48", 32), (" ", None),
                        ("Ch 49-64", 48), (" ", None), (" ", None), (" ", None)):
        lay += layer(name, first)
    send("/Notify/Layers", lay); send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
    time.sleep(2.0 - (time.time() - T0))
    send("/Notify/Layers", lay); send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])   # clic « Ch 1-16 » sur la LV1
    time.sleep(3.5)
    c.close()
threading.Thread(target=server, daemon=True).start()


class Cap(X.DryOut):
    def short(self, h, st, d1, d2=0): pass
    def long(self, h, data): pass
X.DryOut = Cap

BANK_R, BANK_L = 0x2F, 0x2E
def inject():
    def put(t, *ev):
        time.sleep(max(0, t - (time.time() - T0)))
        D.EVENTS.put(ev + (time.time(),))
    def press(t, note):
        put(t, 0, 0x90, note, 127); put(t + 0.03, 0, 0x90, note, 0)
    press(0.5, BANK_R)      # -> Ch 17-32
    press(0.7, BANK_R)      # -> Ch 33-48
    press(0.9, BANK_R)      # -> Ch 49-64 (couche vide sautée)
    press(1.1, BANK_R)      # bout : inchangé
    press(1.3, BANK_L)      # -> Ch 33-48
    press(1.5, 0x10)        # Mute tranche 1 -> In 33
    press(2.3, 0x10)        # après le clic LV1 (Ch 1-16) : Mute tranche 1 -> In 1
    put(2.5, 0, 0x90, 0x68, 127)   # fader 1 touché
    press(2.6, BANK_R)      # ignoré (fader tenu)
    put(2.8, 0, 0x90, 0x68, 0)
    press(3.4, 0x11)        # Mute tranche 2 -> In 2 (toujours Ch 1-16)
threading.Thread(target=inject, daemon=True).start()

sys.argv = ["x", "--dry-run", "--no-journal", "--host", "127.0.0.1", "--port", str(PORT), "--seconds", "3.8"]
out = io.StringIO()
with contextlib.redirect_stdout(out):
    D.main()
shown = [l.split(":", 1)[1].strip() for l in out.getvalue().splitlines() if "Couche affichée" in l]
print("Couches affichées :", shown)
print("/Set envoyés :", [(g[1], g[2]) for g in got])

want_layers = ["Ch 1-16", "Ch 17-32 (banque X-Touch)", "Ch 33-48 (banque X-Touch)",
               "Ch 49-64 (banque X-Touch)", "Ch 33-48 (banque X-Touch)", "Ch 1-16"]
want_sets = [("/Set/Track/Out/Mute", "i:0 i:32 T:True"), ("/Set/Track/Out/Mute", "i:0 i:0 T:True"),
             ("/Set/Track/Out/Mute", "i:0 i:1 T:True")]
ok = shown == want_layers and [(g[1], g[2]) for g in got] == want_sets
print("OK" if ok else "ÉCHEC (attendu %r / %r)" % (want_layers, want_sets))
sys.exit(0 if ok else 1)
