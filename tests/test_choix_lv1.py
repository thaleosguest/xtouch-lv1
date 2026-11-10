"""Test : choix de la LV1 sur le réseau (0.8.1, deux LV1 vues chez Joseph le 02/11 : pc-portable-js et emo-lv1).

LV1 choisie si elle est là, sinon celle de ce PC, sinon une autre ; menu de l'icône. Sans réseau.
Usage : py tests/test_choix_lv1.py <dossier du dépôt>
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, sys.argv[1])
import lv1_finder as F                     # noqa: E402
import xtouch_lv1_display as D             # noqa: E402

ok = True


def check(what, cond):
    global ok
    print("%-45s %s" % (what, "ok" if cond else "ÉCHEC"))
    ok = ok and cond


ici = {"host": "pc-portable-js", "ipv4": ["192.168.1.16"], "source": "192.168.1.16", "local": True}
autre = {"host": "emo-lv1", "ipv4": ["192.168.1.19"], "source": "192.168.1.19", "local": False}
check("auto : ce PC, même entendu en 2e", F.pick([autre, ici])["host"] == "pc-portable-js")
check("choix d'un autre PC", F.pick([ici, autre], "EMO-LV1")["host"] == "emo-lv1")
check("choix absent : ce PC", F.pick([ici, autre], "pc-absent")["host"] == "pc-portable-js")
check("pas de LV1 ici : l'autre", F.pick([autre])["host"] == "emo-lv1")
check("aucune annonce", F.pick([]) is None)

path = os.path.join(tempfile.mkdtemp(), "xtouch_lv1_choix.json")
f = F.LV1Finder(path)
check("pas de choix au départ", f.choice is None)
f.set_choice("emo-lv1")
check("choix relu", F.LV1Finder(path).choice == "emo-lv1")
for e in (ici, autre):
    f.add({k: v for k, v in e.items() if k not in ("source", "local")}, e["source"])
f.seen["pc-portable-js"]["local"] = True                     # (l'adresse de test n'est pas forcément celle de ce PC)


class Link:
    current = autre


rows = D.lv1_menu(f, Link())
print(rows)
check("menu : automatique d'abord", rows[0][0] is None)
check("menu : ce PC avant l'autre", [r[0] for r in rows[1:]] == ["pc-portable-js", "emo-lv1"])
check("menu : LV1 connectée marquée", rows[2][1].endswith("connectée"))
f.set_choice("pc-absent")
check("menu : choix absent listé", D.lv1_menu(f, Link())[-1] == ("pc-absent", "LV1 de pc-absent (absente)"))
f.seen["emo-lv1"]["t"] = time.time() - F.SEEN_S - 1
check("annonce trop ancienne oubliée", [e["host"] for e in f.entries()] == ["pc-portable-js"])

print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
