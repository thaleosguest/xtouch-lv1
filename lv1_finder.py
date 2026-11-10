# -*- coding: utf-8 -*-
"""Choix de la LV1 sur le réseau (0.8.1, demande de Joseph du 02/11 : « comme MyFOH, on peut choisir à qui se connecter,
mais prioriser la connexion sur le PC local »).

Chaque LV1 annonce `/zDNS` en multicast (225.1.1.1:13337) à TOUS les PC du réseau. Jusqu'en 0.8, XTouch-LV1 prenait la
1re annonce entendue : avec deux LV1 sur le réseau (vu le 02/11 : pc-portable-js et emo-lv1), la X-Touch suivait au
hasard la LV1 d'un autre PC (couches et couleurs qui ne correspondaient pas à l'écran).

``LV1Finder`` écoute les annonces en continu (liste à jour pour le menu de l'icône). ``pick`` : LV1 choisie si elle est
là, sinon celle de CE PC, sinon une autre (la 1re par nom). Le choix est retenu dans ``xtouch_lv1_choix.json`` par nom
de PC (le port change à chaque lancement de la LV1) ; None = automatique (ce PC d'abord).
"""
import json
import os
import socket
import threading
import time

import lv1_probe as L

SEEN_S = 6.0          # une LV1 dont l'annonce date de plus de SEEN_S s n'est plus listée (elle en envoie ~1 par seconde)


def is_local(e):
    """Annonce d'une LV1 qui tourne sur ce PC : même nom de PC, une de nos adresses, ou envoyée par nous."""
    local = set(L.local_ipv4s())
    return ((e.get("host") or "").lower() == socket.gethostname().lower()
            or bool(local & set(e.get("ipv4") or [])) or e.get("source") in local or
            (e.get("source") or "").startswith("127."))


def lv1_key(e):
    return (e.get("host") or e.get("source") or "?").lower()


def pick(entries, choice=None):
    """LV1 à joindre parmi ``entries`` (annonces récentes) : la choisie, sinon celle de ce PC, sinon la 1re autre."""
    if not entries:
        return None
    if choice:
        for e in entries:
            if lv1_key(e) == choice.lower():
                return e
    for e in entries:
        if e.get("local"):
            return e
    return sorted(entries, key=lv1_key)[0]


class LV1Finder(threading.Thread):
    def __init__(self, choice_path=None):
        super().__init__(daemon=True, name="lv1-finder")
        self.lock = threading.Lock()
        self.seen = {}                       # nom -> annonce (+ "t", "local", "source")
        self.choice_path = choice_path
        self.choice = self._load_choice()
        self.stop_flag = False

    # -- choix retenu -------------------------------------------------------------------------------------------
    def _load_choice(self):
        try:
            with open(self.choice_path, encoding="utf-8-sig") as f:
                c = json.load(f).get("lv1")
            return c if isinstance(c, str) and c else None
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def set_choice(self, name):
        self.choice = name or None
        if self.choice_path:
            try:
                with open(self.choice_path, "w", encoding="utf-8") as f:
                    json.dump({"lv1": self.choice}, f)
            except OSError:
                pass

    # -- annonces -----------------------------------------------------------------------------------------------
    def entries(self):
        """Annonces récentes : celle de ce PC d'abord, puis les autres par nom."""
        now = time.time()
        with self.lock:
            out = [e for e in self.seen.values() if now - e["t"] < SEEN_S]
        return sorted(out, key=lambda e: (not e["local"], lv1_key(e)))

    def wait_entries(self, timeout):
        """Annonces récentes ; attend jusqu'à ``timeout`` s qu'il y en ait (et un peu plus pour entendre celle de ce PC)."""
        end = time.time() + timeout
        first = None
        while time.time() < end and not self.stop_flag:
            got = self.entries()
            if any(e["local"] for e in got):
                return got
            if got and first is None:
                first = time.time()
            if first is not None and time.time() - first > 2.5:     # plusieurs annonces par seconde : 2,5 s suffit
                return got
            time.sleep(0.2)
        return self.entries()

    def add(self, e, source):
        e = dict(e, source=source, t=time.time())
        e["local"] = is_local(e)
        with self.lock:
            self.seen[lv1_key(e)] = e

    def run(self):
        while not self.stop_flag:
            try:
                self._listen()
            except OSError as ex:
                print("  Recherche des LV1 : %s (nouvel essai dans 5 s)" % ex)
            time.sleep(5)

    def _listen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", L.MCAST_PORT))
            joined = False
            for ip in L.local_ipv4s():
                try:
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                 socket.inet_aton(L.MCAST_ADDR) + socket.inet_aton(ip))
                    joined = True
                except OSError:
                    pass
            if not joined:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                             socket.inet_aton(L.MCAST_ADDR) + socket.inet_aton("0.0.0.0"))
            s.settimeout(0.5)
            while not self.stop_flag:
                try:
                    data, src = s.recvfrom(65535)
                except socket.timeout:
                    continue
                e = L.parse_zdns(data)
                if e and e["service"] == L.SERVICE and e["port"]:
                    self.add(e, src[0])
        finally:
            s.close()
