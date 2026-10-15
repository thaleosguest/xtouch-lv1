"""Test : point / contour de toucher à l'écran = doigt posé SEULEMENT (disparaît dès le relâchement, demande de Joseph du
15/10), ou fader bougé sans toucher détecté (ongle) pendant qu'il bouge ; pas la temporisation des garde-fous."""
import sys
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

f = D.FaderControl(D.LV1State(), None)
f.touched[2] = True
f.hold_until[2] = 10.3
a = f.touch_display(10.0)                     # doigt posé
f.touched[2] = False                          # relâché à 10.0 : garde-fous encore actifs jusqu'à 10.3
b = f.touch_display(10.01)
f.untouched_move[5] = 20.0                    # ongle sur le fader 6
c, d = f.touch_display(20.05), f.touch_display(20.3)
print("posé :", a, "| relâché :", b, "(garde-fou :", sorted(f.held(10.01)), ") | ongle :", c, "puis", d)
ok = a == [2] and b == [] and f.held(10.01) == {2} and c == [5] and d == []
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
