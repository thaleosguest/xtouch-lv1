"""Test : état mute/solo initial lu dans /Channels (1er entier = solo, 2e = mute).

    py tests/test_etat_initial.py . [journal_reel.txt]

Sans journal : /Channels synthétique. Avec un journal réel : affiche les entrées mutées / en solo
d'après le premier /Channels du journal (à comparer avec l'écran de la LV1).
"""
import os, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xtouch_lv1_display as D
import analyser_channels as A


def track(name, g, c, solo=0, mute=0):
    return ([("s", name), ("i", g), ("i", c), ("d", 0.0), ("d", 0.0), ("i", solo), ("i", mute)]
            + [("i", 0)] * 10 + [("h", 0), ("d", 0.0)])


st = D.LV1State()
D.handle(st, "/Channels", [("i", 3)] + track("A", 0, 0) + track("B", 0, 5, mute=1) + track("C", 0, 6, solo=1))
got = {k: (t["mute"], t["solo"]) for k, t in st.tracks.items()}
want = {(0, 0): (False, False), (0, 5): (True, False), (0, 6): (False, True)}
print("synthétique :", "OK" if got == want else "ÉCHEC %r" % got)
ok = got == want

# Une notification ultérieure doit toujours l'emporter.
D.handle(st, "/Notify/Track/Out/Mute", [("i", 0), ("i", 5), ("i", 0), ("T", True)])
ok &= st.tracks[(0, 5)]["mute"] is False
print("notification après /Channels :", "OK" if st.tracks[(0, 5)]["mute"] is False else "ÉCHEC")

if len(sys.argv) > 2:
    st = D.LV1State()
    for addr, args in A.read_journal(sys.argv[2]):
        if addr == "/Channels":
            D.handle(st, addr, args)
            break
    for field in ("mute", "solo"):
        names = ["%s %d (%s)" % ("In" if g == 0 else "g%d" % g, c + 1, t["name"])
                 for (g, c), t in sorted(st.tracks.items()) if t[field]]
        print("%s : %s" % (field, ", ".join(names) or "aucun"))
sys.exit(0 if ok else 1)
