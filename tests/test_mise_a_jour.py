"""Test : avis de mise à jour de XTouch-LV1 (demande de Joseph du 18/10).
- version_tuple : « v0.2.10 » > « 0.2.9 », texte quelconque -> () ;
- release plus récente -> UPDATE rempli + UNE bulle (pas une 2e fois pour la même version) ;
- même version, brouillon, pré-version, réseau en panne -> rien."""
import sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

class Tray:
    def __init__(self): self.notes = []
    def notify(self, title, text): self.notes.append(title)
check("versions", D.version_tuple("v0.2.10") > D.version_tuple("0.2.9") and D.version_tuple("latest") == ())
t = Tray()
D.VERSION = "0.2.2"
D.check_update(t, fetch=lambda: {"tag_name": "v0.2.2", "html_url": "u"})
check("même version", D.UPDATE["version"] is None and not t.notes)
D.check_update(t, fetch=lambda: {"tag_name": "v0.3", "draft": True})
D.check_update(t, fetch=lambda: {"tag_name": "v0.3", "prerelease": True})
check("brouillon / pré-version ignorés", D.UPDATE["version"] is None)
def down(): raise OSError("pas de réseau")
D.check_update(t, fetch=down)
check("réseau en panne", D.UPDATE["version"] is None)
D.check_update(t, fetch=lambda: {"tag_name": "v0.3.0", "html_url": "https://github.com/x/releases/tag/v0.3.0"})
D.check_update(t, fetch=lambda: {"tag_name": "v0.3.0", "html_url": "https://github.com/x/releases/tag/v0.3.0"})
check("mise à jour signalée une fois", D.UPDATE["version"] == "0.3.0" and len(t.notes) == 1 and "0.3.0" in t.notes[0]
      and D.UPDATE["url"].endswith("v0.3.0"))
print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
