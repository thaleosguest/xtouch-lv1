"""Test : installeur sur des dossiers temporaires (faux programme, faux dossier REAPER) — scripts déclarés, anciennes
lignes lv1_* remplacées, __startup.lua (bloc marqué, contenu de l'utilisateur gardé), surface OSC ajoutée une fois,
réglages jamais écrasés, réinstallation idempotente, désinstallation (réglages gardés)."""
import os, sys, tempfile
sys.path.insert(0, sys.argv[1])
import installer as I

root = tempfile.mkdtemp(prefix="inst_")
src, tgt, rp = (os.path.join(root, d) for d in ("src", "Programs dir", "REAPER"))
os.makedirs(os.path.join(src, "reaper")); os.makedirs(os.path.join(src, "_internal")); os.makedirs(os.path.join(rp, "Scripts"))
def put(p, s):
    with open(p, "w", encoding="utf-8", newline="") as f: f.write(s)
def get(p):
    with open(p, encoding="utf-8", newline="") as f: return f.read()
put(os.path.join(src, "XTouch-LV1.exe"), "exe")
put(os.path.join(src, "_internal", "x.dll"), "dll")
for s in I.SCRIPTS + ["lv1_common.lua"]: put(os.path.join(src, "reaper", s), "-- " + s)
put(os.path.join(src, "xtouch_ecran.json"), "NEW")
os.makedirs(tgt); put(os.path.join(tgt, "xtouch_ecran.json"), "MINE")       # réglage déjà là
put(os.path.join(rp, "reaper-kb.ini"), 'SCR 4 0 RSaaa "Custom: lyrics.lua" Cockos/lyrics.lua\r\n'
    'SCR 4 0 RSbbb "Custom: lv1_scenes.lua" C:\\old\\reaper\\lv1_scenes.lua\r\n'
    'SCR 260 0 RSccc "Custom: lv1_meter_bridge.lua" C:\\old\\reaper\\lv1_meter_bridge.lua\r\n')
put(os.path.join(rp, "REAPER.ini"), "[reaper]\r\nfoo=1\r\n[verchk]\r\nx=2\r\n")
put(os.path.join(rp, "Scripts", "__startup.lua"), "-- user stuff\r\nprint(1)\r\n")

out = []
for _ in range(2):
    I.install(src, tgt, rp, out.append, do_shortcuts=False)
kb = get(os.path.join(rp, "reaper-kb.ini"))
ini = get(os.path.join(rp, "REAPER.ini"))
st = get(os.path.join(rp, "Scripts", "__startup.lua"))
print(kb); print(ini); print(st)
ok = "lyrics.lua" in kb and "C:\\old" not in kb and kb.count("lv1_") == 6 and kb.count('"' + tgt) == 3
ok = ok and ini.count("csurf_") == 2 and "csurf_cnt=1" in ini and 'csurf_0=OSC "XTouch-LV1" 3 8000' in ini
ok = ok and ini.index("csurf_cnt") < ini.index("[verchk]")
ok = ok and st.startswith("-- user stuff") and st.count(I.BEGIN) == 1 and st.count("NamedCommandLookup") == 2
ok = ok and get(os.path.join(tgt, "xtouch_ecran.json")) == "MINE" and os.path.exists(os.path.join(tgt, "reaper", "lv1_common.lua"))
ok = ok and "\n" not in kb.replace("\r\n", "")
I.uninstall(tgt, rp, out.append, keep_settings=True, do_shortcuts=False)
kb2, st2 = get(os.path.join(rp, "reaper-kb.ini")), get(os.path.join(rp, "Scripts", "__startup.lua"))
ok = ok and "lv1_" not in kb2 and "lyrics" in kb2 and I.BEGIN not in st2 and "print(1)" in st2
ok = ok and sorted(os.listdir(tgt)) == ["xtouch_ecran.json"]
print("\n".join(out))
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
