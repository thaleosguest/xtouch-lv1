"""Test : état complet de la LV1 (connexion, rappel de scène, Flip A/B) — bug du 15/10 (journal 155042).
La LV1 envoie les jeux d'usine suivis de /Notify/CurrentLayer, puis les pages Custom SANS CurrentLayer : la couche
suivie doit rester celle d'usine. Un vrai passage en Custom (Layers Custom + CurrentLayer) doit, lui, être suivi."""
import sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D


def layers(view, flag, sets):
    args = [("i", view), ("i", flag), ("i", len(sets))]
    for name, entries in sets:
        args += [("s", name), ("i", len(entries))]
        for g, c in entries:
            args += [("i", g), ("i", c)]
    return args


usine = [("Ch 1-16", [(0, k) for k in range(16)]), ("Ch 17-32", [(0, 16 + k) for k in range(16)])]
custom = [("Page-1", [(-1, -1)] * 6 + [(0, 2)] + [(-1, -1)] * 9), ("Page-2", [(-1, -1)] * 16)]
st = D.LV1State()
for v in (0, 1):                                            # état complet, comme le journal 155042 à 8240 s
    D.handle(st, "/Notify/Layers", layers(v, 0, usine))
    D.handle(st, "/Notify/CurrentLayer", [("i", v), ("i", 0)])
for v in (0, 1):
    D.handle(st, "/Notify/Layers", layers(v, 1, custom))
after_dump = st.layer_entries(0)[0]
D.handle(st, "/Notify/Layers", layers(0, 1, custom))         # vrai clic sur Custom dans la LV1
D.handle(st, "/Notify/CurrentLayer", [("i", 0), ("i", 0)])
after_click = st.layer_entries(0)[0]
print("après l'état complet :", after_dump, "| après un clic Custom :", after_click)
ok = after_dump == "Ch 1-16" and after_click == "Page-1"
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
