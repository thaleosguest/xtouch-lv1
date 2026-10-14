"""Test : la sélection faite sur l'écran de la LV1 (lecture simulée) devient la sélection du pont.

    py tests/test_selection_lv1.py .
"""
import sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

st = D.LV1State()
st.last_set[0] = [("Ch %d-%d" % (16 * k + 1, 16 * k + 16), [(0, 16 * k + i) for i in range(16)]) for k in range(5)]
st.current[0] = 1
READ = {"col": None}
w = D.LV1SelectionWatcher(st, 0, read=lambda: READ["col"])
res = []
for col, xt_sel in ((None, None), (4, None), (4, (0, 40)), (6, None), (None, None), (6, None)):
    if xt_sel:
        st.selected = xt_sel           # sélection faite sur la X-Touch entre deux lectures
    READ["col"] = col
    w.step()
    res.append(st.selected)
print(res)
want = [None, (0, 20), (0, 40), (0, 22), (0, 22), (0, 22)]
ok = res == want
print("OK" if ok else "ÉCHEC (attendu %r)" % want)
sys.exit(0 if ok else 1)
