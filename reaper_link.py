#!/usr/bin/env python3
"""Lien OSC avec REAPER (transport + navigation de la X-Touch, demande de Joseph du 15/10/2026).

Reaper : Préférences > Control/OSC/web > Add > OSC (Open Sound Control)
    Mode : Configure device IP+local port
    Device IP : 127.0.0.1   Device port : 9000      (Reaper ENVOIE l'état ici : LED play / rec / repeat / click)
    Local listen port : 8000                         (Reaper REÇOIT les commandes ici)
    Pattern config : Default
Bibliothèque standard seulement (OSC de lv1_probe), UDP.

Messages (fichier Default.ReaperOSC, non vérifiés sur la machine de Joseph) :
    /play /stop /record /repeat /click   (t = déclencheur : valeur 1)
    /rewind /forward                     (b = tenu : 1 à l'appui, 0 au relâchement)
    /action i:n                          (action Reaper par son numéro)
Retours : /play /stop /record /repeat /click f:0|1.
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lv1_probe as P

# Actions Reaper (liste des actions, section Main)
ACT_PREV_MARKER = 40172        # Markers: Go to previous marker/project start
ACT_NEXT_MARKER = 40173        # Markers: Go to next marker/project end
ACT_ADD_MARKER = 40157         # Markers: Insert marker at current position
ACT_JOG_BACK = 40084           # Transport: Rewind a little bit
ACT_JOG_FWD = 40085            # Transport: Fast forward a little bit
ACT_ZOOM_OUT_H = 1011          # View: Zoom out horizontal
ACT_ZOOM_IN_H = 1012           # View: Zoom in horizontal
ACT_ZOOM_IN_V = 40111          # View: Zoom in vertical
ACT_ZOOM_OUT_V = 40112         # View: Zoom out vertical
ACT_PREV_TRACK = 40286         # Track: Go to previous track
ACT_NEXT_TRACK = 40285         # Track: Go to next track
ACT_SCRUB_BACK = 40104         # View: Move cursor left one pixel  (SCRUB : pas fin)
ACT_SCRUB_FWD = 40105          # View: Move cursor right one pixel
ACT_REFRESH = 41743            # Control surface: Refresh all surfaces (Reaper renvoie tout son état)


def parse_target(text):
    """« 127.0.0.1:8000:9000 » -> (hôte, port d'envoi vers Reaper, port d'écoute des retours) ; « aucun » -> None."""
    if not text or text.lower() in ("aucun", "none", "off"):
        return None
    parts = text.split(":")
    host = parts[0] or "127.0.0.1"
    send = int(parts[1]) if len(parts) > 1 and parts[1] else 8000
    recv = int(parts[2]) if len(parts) > 2 and parts[2] else 9000
    return host, send, recv


class ReaperLink:
    def __init__(self, host="127.0.0.1", send_port=8000, recv_port=9000, journal=None):
        self.addr = (host, send_port)
        self.mark = journal or (lambda _s: None)
        self.state = {}                   # "play" / "record" / "repeat" / "click" / "stop" -> bool
        self.seen = 0.0                   # instant du dernier message reçu de Reaper
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx = None
        if recv_port:
            try:
                self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.rx.bind(("0.0.0.0", recv_port))
                self.rx.settimeout(0.5)
                threading.Thread(target=self._listen, daemon=True).start()
            except OSError as e:
                print("  Reaper : port d'écoute %d indisponible (%s) : pas de LED de transport." % (recv_port, e))
                self.rx = None
        # Reaper n'envoie son état QU'AUX CHANGEMENTS (essai de Joseph du 15/10 : « ecoute » ne reçoit rien) :
        # on lui demande de tout renvoyer au démarrage, puis toutes les 5 s tant qu'il ne répond pas.
        threading.Thread(target=self._refresh, daemon=True).start()

    def send(self, address, args=()):
        try:
            self.tx.sendto(P.osc_encode(address, list(args)), self.addr)
            self.mark("-> Reaper %s %s" % (address, " ".join(str(a[1]) for a in args)))
        except OSError as e:
            self.mark("-> Reaper %s : erreur %s" % (address, e))

    def trigger(self, name):
        self.send("/" + name, [("f", 1.0)])

    def hold(self, name, down):
        self.send("/" + name, [("f", 1.0 if down else 0.0)])

    def action(self, n):
        self.send("/action", [("i", int(n))])

    def _refresh(self):
        while True:
            if not self.connected():
                self.action(ACT_REFRESH)
            time.sleep(5.0)

    def connected(self):
        return time.time() - self.seen < 5.0

    def _listen(self):
        while True:
            try:
                data, _ = self.rx.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            for addr, args in self._messages(data):
                self.seen = time.time()
                key = addr.strip("/")
                if key in ("play", "stop", "record", "repeat", "click", "pause") and args:
                    try:
                        self.state[key] = float(args[0][1]) > 0.5
                    except (TypeError, ValueError):
                        pass

    def _messages(self, data):
        """Paquet OSC ou bundle (#bundle) -> [(adresse, args)]."""
        out = []
        if data.startswith(b"#bundle\0"):
            off = 16
            while off + 4 <= len(data):
                n = int.from_bytes(data[off:off + 4], "big")
                out += self._messages(data[off + 4:off + 4 + n])
                off += 4 + n
            return out
        try:
            out.append(P.osc_decode(data))
        except Exception:
            pass
        return out


if __name__ == "__main__":
    # Essai sans X-Touch : py reaper_link.py play | stop | record | repeat | click | marker | next | prev | ecoute
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ecoute"
    r = ReaperLink(journal=print)
    acts = {"marker": ACT_ADD_MARKER, "next": ACT_NEXT_MARKER, "prev": ACT_PREV_MARKER}
    if cmd in acts:
        r.action(acts[cmd])
    elif cmd != "ecoute":
        r.trigger(cmd)
    t_end = time.time() + 3
    while time.time() < t_end:
        time.sleep(0.2)
    print("Retours de Reaper :", r.state or "aucun (vérifie Device port 9000 dans Reaper)")
