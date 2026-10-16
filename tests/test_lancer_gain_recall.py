"""Test : XTouch-LV1 trouve X/M32 Gain Recall pour le lancer (demande de Joseph du 16/10 : « sur toutes les options »).
Ordre : suite.json de l'installeur, dossier voisin du pont (pack), %LOCALAPPDATA%\Programs, à côté du pont (zip),
clé « Lancer avec Windows » ; rien de trouvé -> None."""
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond
def touch(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close()
    return p

root = tempfile.mkdtemp(prefix="grfind_")
here = os.path.join(root, "progs", "XTouch-LV1"); os.makedirs(here)
suite = os.path.join(here, "suite.json")
env = {"LOCALAPPDATA": os.path.join(root, "lad")}
find = lambda run=None: D.find_gain_recall(here, suite, env, run or "")
check("rien", find() is None)
run_exe = touch(os.path.join(root, "ailleurs", D.GR_EXE))
check("clé Lancer avec Windows", find('"%s" --at-login' % run_exe) == run_exe)
zip_exe = touch(os.path.join(here, D.GR_EXE))
check("à côté (zip)", find() == zip_exe)
lad_exe = touch(os.path.join(env["LOCALAPPDATA"], "Programs", "X32 Gain Recall", D.GR_EXE))
check("Programs", find() == lad_exe)
sib_exe = touch(os.path.join(root, "progs", "X32 Gain Recall", D.GR_EXE))
check("dossier voisin (pack)", find() == sib_exe)
inst_exe = touch(os.path.join(root, "autre dossier", "X32 Gain Recall", D.GR_EXE))
json.dump({"gainrecall": inst_exe}, open(suite, "w"))
check("suite.json", find() == inst_exe)
json.dump({"gainrecall": os.path.join(root, "disparu.exe")}, open(suite, "w"))
check("suite.json périmé -> suivant", find() == sib_exe)
print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
