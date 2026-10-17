"""Test : X-Touch débranchée pendant que le pont tourne (plantage de la 0.2 chez Joseph le 18/10 : « envoi court :
There is no driver installed on your system », exception non rattrapée).
- SafeMidi : la 1re erreur d'envoi est notée (lost), les suivantes sont ignorées, rien ne remonte ;
- boucle principale (--dry-run, fausse LV1 absente) : sortie qui tombe en panne au 3e SysEx -> le pont rouvre les ports,
  annonce « X-Touch reconnectée » et va au bout sans exception."""
import contextlib, io, sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D
import xtouch_probe as X

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

class Broken:
    def short(self, h, *a): raise OSError("envoi court : There is no driver installed on your system.")
    def long(self, h, d): raise OSError("envoi SysEx : There is no driver installed on your system.")
m = D.SafeMidi(Broken())
m.short(1, 0x90, 1, 127); m.long(1, b"x")
check("erreur notée sans exception", m.lost and "no driver" in m.lost)

class Flaky(X.DryOut):
    n = 0
    def long(self, h, data):
        Flaky.n += 1
        if Flaky.n == 3:
            raise OSError("envoi SysEx : There is no driver installed on your system.")
X.DryOut = Flaky
sys.argv = ["x", "--dry-run", "--no-journal", "--host", "127.0.0.1", "--port", "9", "--x32", "aucun", "--seconds", "3"]
out = io.StringIO()
with contextlib.redirect_stdout(out):
    code = D.main()
txt = out.getvalue()
check("perte vue", "X-Touch perdue" in txt)
check("reconnectée", "X-Touch reconnectée" in txt)
check("fin normale", code == 0 and "Arrêté" in txt)
print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
