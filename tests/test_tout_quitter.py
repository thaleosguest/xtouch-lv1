"""Test : « Tout quitter » dans le menu de l'icône (demande de Joseph, 19/10) = X/M32 Gain Recall puis XTouch-LV1.
- faux Gain Recall local : reçoit POST /api/quit (Host 127.0.0.1:port, comme ses ALLOWED_HOSTS), le pont s'arrête ;
- Gain Recall absent : le pont s'arrête quand même, sans attendre plus de 2 s ;
- menu : entrée visible avec Gain Recall, masquée avec --x32 aucun (gr_url None).

    py tests/test_tout_quitter.py .
"""
import sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, sys.argv[1])
import xtouch_lv1_display as D

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond

recu = []


class FauxGR(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        recu.append((self.path, self.headers.get("Host")))
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = HTTPServer(("127.0.0.1", 0), FauxGR)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# 1) Gain Recall présent
D.STOP.clear()
D.quit_all("http://127.0.0.1:%d" % port)
check("Gain Recall reçoit /api/quit", recu == [("/api/quit", "127.0.0.1:%d" % port)])
check("le pont s'arrête", D.STOP.is_set())
srv.shutdown()

# 2) Gain Recall absent (port fermé)
D.STOP.clear()
t0 = time.time()
D.quit_all("http://127.0.0.1:%d" % port)
check("absent : le pont s'arrête quand même, vite", D.STOP.is_set() and time.time() - t0 < 2.5)
D.STOP.clear()

# 3) entrée du menu
import tray
menus = []


class FauxTray:
    def __init__(self, tip, items, icon_path=None):
        menus.append(items)

    def start(self):
        return self


sauve = tray.TrayIcon
tray.TrayIcon = FauxTray
D.start_tray("http://127.0.0.1:8032")
D.start_tray(None)
tray.TrayIcon = sauve
lib = lambda items: [(it[0]() if callable(it[0]) else it[0]) for it in items if it]
print("menu avec Gain Recall :", lib(menus[0]))
check("entrée visible", any(l and l.startswith("Tout quitter") for l in lib(menus[0])))
check("entrée masquée sans Gain Recall", not any(l and l.startswith("Tout quitter") for l in lib(menus[1])))

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
