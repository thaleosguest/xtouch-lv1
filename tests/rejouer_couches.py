"""Rejoue les messages LV1 d'un journal réel et affiche la couche suivie (vue Mixer 1) à chaque changement,
à côté de ce que le pont avait affiché à l'époque (« affiché : … »). Usage : py tests/rejouer_couches.py . journal.txt"""
import ast, re, sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

TOK = re.compile(r"([a-zA-Z]):('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\S+)")


def parse_args(rest):
    out = []
    for t, v in TOK.findall(rest):
        if t == "s":
            v = ast.literal_eval(v)
        elif t in "ih":
            v = int(v)
        elif t in "fd":
            v = float(v)
        elif t in "TF":
            v = t == "T"
        out.append((t, v))
    return out


state = D.LV1State()
last = None
for line in open(sys.argv[2], encoding="utf-8"):
    parts = line.rstrip("\n").split(" ", 2)
    if len(parts) < 2:
        continue
    t, addr = parts[0], parts[1]
    if addr == "=====":
        if len(parts) > 2 and parts[2].startswith("affiché :"):
            print("%10s   (époque) %s" % (t, parts[2]))
        continue
    if not addr.startswith("/") or addr not in ("/Notify/Layers", "/Notify/CurrentLayer", "/Notify/CurSceneIndex"):
        continue
    D.handle(state, addr, parse_args(parts[2] if len(parts) > 2 else ""))
    if addr == "/Notify/CurSceneIndex":
        print("%10s   scène %s" % (t, parse_args(parts[2])[0][1]))
    name, _ = state.layer_entries(0)
    if name != last:
        print("%10s   MAINTENANT : %s" % (t, name))
        last = name
