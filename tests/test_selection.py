"""Test : sélection locale (Select, ◄ CHANNEL ►), LED Select, banque qui suit au bout de couche.

    py tests/test_selection.py .
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


LEDS = {}
class Cap(X.DryOut):
    def short(self, h, st, d1, d2=0):
        if st == 0x90 and 0x18 <= d1 <= 0x1F and time.time() - T0 < 2.45:   # avant la remise à zéro finale
            LEDS[(h, d1)] = d2
    def long(self, h, data): pass
X.DryOut = Cap

MARKS = []
class J:
    def write(self, *a): pass
    def mark(self, text): MARKS.append(text)
D.JOURNAL = J()

CH_R, CH_L, SEL = 0x31, 0x30, 0x18
def inject():
    def put(t, *ev):
        time.sleep(max(0, t - (time.time() - T0)))
        D.EVENTS.put(ev + (time.time(),))
    def press(t, unit, note):
        put(t, unit, 0x90, note, 127); put(t + 0.03, unit, 0x90, note, 0)
    press(0.30, 0, CH_R)         # rien de sélectionné -> 1er canal affiché (In 1)
    press(0.45, 1, SEL + 7)      # Select tranche 16 -> In 16
    press(0.60, 0, CH_R)         # bout de couche -> banque Ch 17-32, In 17
    press(0.75, 0, CH_L)         # retour Ch 1-16, In 16
    press(0.90, 0, 0x2F)         # BANK ► : la sélection reste In 16 (non affichée)
    press(1.05, 0, CH_R)         # non affichée -> 1er canal affiché (In 17)
    press(1.20, 0, 0x2F); press(1.30, 0, 0x2F)   # Ch 33-48 puis Ch 49-64 (couche vide sautée)
    press(1.45, 0, CH_L)         # non affichée -> In 49
    press(1.60, 0, CH_L)         # bout gauche -> banque Ch 33-48 (vide sautée), dernier canal In 48
    # à 2,0 s la fausse LV1 « clique » Ch 1-16 : la sélection In 48 n'est plus affichée
    press(2.20, 0, CH_R)         # -> In 1
threading.Thread(target=inject, daemon=True).start()

sys.argv = ["x", "--dry-run", "--no-journal", "--host", "127.0.0.1", "--port", str(PORT), "--seconds", "2.6"]
with contextlib.redirect_stdout(io.StringIO()):
    D.main()
sel = [m.split("->")[-1].strip() if "Channel" in m else m for m in MARKS if "sélection" in m]
print("Sélections :", sel)
want = ["sélection (0, 0)", "sélection (0, 15)", "sélection (0, 16)", "sélection (0, 15)",
        "sélection (0, 16)", "sélection (0, 48)", "sélection (0, 47)", "sélection (0, 0)"]
leds_on = sorted(k for k, v in LEDS.items() if v)
print("LED Select allumées à la fin :", leds_on)
ok_led = len(leds_on) == 1   # une seule LED Select : In 1, tranche 1
ok = sel == want and ok_led
print("OK" if ok else "ÉCHEC (attendu %r)" % want)
sys.exit(0 if ok else 1)
