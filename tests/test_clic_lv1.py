"""Test : --clic-lv1, la LV1 suit BANK et la sélection (clics simulés remplacés par des faux).

    py tests/test_clic_lv1.py .

La fausse LV1 « reçoit » un clic de couche en mettant à jour sa couche courante (comme /Notify/CurrentLayer)
après 0,1 s. On vérifie l'ordre et le contenu des clics : couche puis tranche, tranche seulement si la LV1
affiche la bonne couche, refus (pas administrateur) qui n'arrête rien.
"""
import sys, threading, time
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

st = D.LV1State()
layers = [("Ch %d-%d" % (16 * k + 1, 16 * k + 16), [(0, 16 * k + i) for i in range(16)]) for k in range(5)]
st.last_set[0] = layers
st.current[0] = 0
CLICKS = []
REFUSE = {"on": False}


def fake_layer(k, mixer):
    if REFUSE["on"]:
        return False, "pas administrateur"
    CLICKS.append(("couche", k))
    def lv1():
        time.sleep(0.1)
        with st.lock:
            st.current[0] = k
            st.local.pop(0, None)
    threading.Thread(target=lv1, daemon=True).start()
    return True, None


def fake_strip(i, mixer):
    with st.lock:
        cur = st.current[0]
    CLICKS.append(("tranche", i, cur))
    return True, None


b = D.ButtonControl(st, link=None, write=False, page=0)
b.lv1 = D.LV1Clicker(st, 0, fake_layer, fake_strip)
b.lv1.start()


def entries():
    with st.lock:
        return list(st.layer_entries(0)[1]) + [None]


def press(note, unit=0):
    b.on_midi(unit, 0x90, note, 127, time.time(), entries(), None)
    time.sleep(0.3)


press(0x18 + 4)          # Select tranche 5 -> clic tranche 5 (couche 0)
press(0x2F)              # BANK ► -> clic couche 1
press(0x30)              # CHANNEL ◄ : sélection In 5 pas affichée -> 1re de Ch 17-32 (In 17) -> clic tranche 1
for _ in range(16):      # CHANNEL ► x16 : In 18..32 puis Ch 33-48 / In 33 -> clic couche 2 puis tranche 1
    b.on_midi(0, 0x90, 0x31, 127, time.time(), entries(), None)
time.sleep(1.5)
REFUSE["on"] = True
press(0x2E)              # BANK ◄ refusé : pas de clic, le pont continue
time.sleep(0.3)

print("Clics :", CLICKS)
ok = (CLICKS[:4] == [("tranche", 4, 0), ("couche", 1), ("tranche", 0, 1), ("tranche", 1, 1)] or
      CLICKS[:3] == [("tranche", 4, 0), ("couche", 1), ("tranche", 0, 1)])
# la rafale de CHANNEL ► est regroupée : au moins le clic de couche 2 puis la tranche 1 sur la couche 2
ok = ok and ("couche", 2) in CLICKS and CLICKS[-1] == ("tranche", 0, 2)
ok = ok and CLICKS.index(("couche", 2)) < len(CLICKS) - 1
ok = ok and not any(c == ("couche", 1) for c in CLICKS[CLICKS.index(("couche", 2)):])
with st.lock:
    ok = ok and st.selected == (0, 32) and st.local.get(0) == 1   # BANK ◄ local malgré le refus
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
