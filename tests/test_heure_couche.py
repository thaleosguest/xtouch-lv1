"""Test : afficheur 7 segments (position REAPER, sinon heure du PC), notification de couche, /time de REAPER.
- time_display : 1 h 02 min 03,456 s -> « 1.02.03.456 » ; 17:05:09 -> « 17.05.09 » + 3 blancs ; 10 codes, points
  fusionnés dans le chiffre précédent (+0x40) ;
- layer_toast : couche par défaut ignorée ; banque X-Touch, couche vide et Mixer 2 en sous-titre ;
- ReaperLink : /time f reçu sur le port d'écoute -> .time, alive()."""
import os, socket, sys, time
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D
import reaper_link as R
import lv1_probe as P

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

def txt(codes):
    """Codes 7 segments -> texte lisible (point après un chiffre = +0x40)."""
    out = ""
    for c in codes:
        dot = c >= 0x40 and (c - 0x40) >= 0x20
        b = c - 0x40 if dot else c
        out += (chr(b) if b >= 0x20 else chr(b + 0x40)) + ("." if dot else "")
    return out

a, t = D.time_display(3723.456, None)
check("reaper", txt(t) == "  1.02.03.456" and len(t) == 10 and txt(a) == "  ")
a, t = D.time_display(None, time.struct_time((2026, 10, 16, 17, 5, 9, 4, 289, 1)))
check("heure", txt(t) == " 17.05.09   " and len(t) == 10)
a, t = D.time_display(-0.2, None)
check("négatif", txt(t) == "  0.00.00.000")
check("défaut ignoré", D.layer_toast("Ch 1-16 (par défaut)") is None and D.layer_toast(None) is None)
check("simple", D.layer_toast("Grp/Fx") == ("Grp/Fx", None))
check("banque", D.layer_toast("Ch 17-32 (banque X-Touch)") == ("Ch 17-32", "X-Touch bank"))
check("vide + banque + M2", D.layer_toast("Page-3 (vide) (banque X-Touch)", 2) == ("Page-3", "Mixer 2  ·  empty  ·  X-Touch bank"))

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
r = R.ReaperLink("127.0.0.1", 9, port)
check("pas encore", r.time is None and not r.alive())
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
tx.sendto(P.osc_encode("/time", [("f", 12.5)]), ("127.0.0.1", port))
tx.sendto(P.osc_encode("/time/str", [("s", "0:12.500")]), ("127.0.0.1", port))
for _ in range(50):
    if r.time is not None:
        break
    time.sleep(0.02)
check("/time reçu", r.time == 12.5 and r.alive())

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
