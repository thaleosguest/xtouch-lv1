#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test LV1 : couleurs et vumètres par l'API réseau privée de la LV1 (celle des apps MyFOH / MyMon).

LECTURE SEULE : ce script n'envoie à la LV1 que la poignée de main, les /pong de maintien
et deux demandes d'état (/Get/Aux/Tracks, /Get/Layers). Il ne change aucun réglage.

Protocole repris du module Companion communautaire « companion-module-waves-lv1 »
(licence MIT, non affilié à Waves, rétro-ingénierie) :
  - découverte : paquets OSC « /zDNS » en multicast UDP 225.1.1.1:13337
  - transport  : TCP, chaque trame = [taille 4 octets BE][en-tête 8 octets 00 00 00 02 00 00 00 00][OSC]
  - maintien   : la LV1 envoie /ping ~1 fois/s, il faut répondre /pong avec les mêmes arguments
  - poignée de main « MyFOH » : /handshake i:1 i:-1 i:1 + /device_name s:nom s:uuid (un seul envoi TCP)

Python 3 standard uniquement (rien à installer).

Usage :
    py lv1_probe.py                      # découverte automatique, 60 s
    py lv1_probe.py --duration 120       # plus long
    py lv1_probe.py --host 192.168.1.50 --port 51234
    py lv1_probe.py --style mymon        # autre poignée de main, pour comparer la cadence des vumètres
"""
import argparse
import collections
import datetime
import json
import os
import socket
import statistics
import struct
import sys
import threading
import time
import uuid

MCAST_ADDR = "225.1.1.1"
MCAST_PORT = 13337
SERVICE = "_waveslv113._tcp"

# Adresses très bavardes : comptées, mais pas affichées une par une.
NOISY = {"/ping", "/Notify/Meters", "/Notify/NetworkCongestion", "/Notify/TempoBlink"}


# OSC et trames TCP : dans osc.py (étape 5 du refactor), réexportés ici pour les anciens appels.
from osc import (TX_HEADER, HEADER_LEN, _pad4, _osc_str, osc_encode, _read_str, osc_decode,  # noqa: F401
                 frame, split_frames)


def say(text):
    """Affiche une ligne d'événement sans se mélanger à la ligne d'état réécrite en place."""
    sys.stdout.write("\r" + " " * 150 + "\r" + text + "\n")
    sys.stdout.flush()


def short_args(args, limit=12):
    out = []
    for t, v in args[:limit]:
        if t == "f":
            out.append("%s:%.3f" % (t, v))
        elif t == "b":
            out.append("b:<%d octets>" % len(v))
        else:
            out.append("%s:%r" % (t, v))
    if len(args) > limit:
        out.append("… (+%d)" % (len(args) - limit))
    return " ".join(out)


# ─── Découverte /zDNS ─────────────────────────────────────────────────────────

def local_ipv4s():
    ips = set()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except OSError:
        pass
    try:  # adresse de la route par défaut
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.")]


def rank_ip(ip):
    if ip.startswith("127."):
        return -100
    if ip.startswith("169.254."):
        return -50
    parts = ip.split(".")
    if parts[0] == "172" and len(parts) > 1 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
        return 30
    if ip.startswith("192.168.56."):
        return 20
    if ip.startswith("192.168."):
        return 100
    if ip.startswith("10."):
        return 90
    return 40


def parse_zdns(data):
    try:
        address, args = osc_decode(data)
    except Exception:
        return None
    if address != "/zDNS" or len(args) < 2 or args[0][0] != "s":
        return None
    entry = {"service": args[0][1], "uuid": args[1][1] if args[1][0] == "s" else None,
             "host": None, "port": None, "ipv4": [], "ipv6": []}
    for t, v in args[2:]:
        if t == "s":
            if v.count(".") == 3 and all(p.isdigit() for p in v.split(".")):
                entry["ipv4"].append(v)
            elif ":" in v:
                entry["ipv6"].append(v)
            elif entry["host"] is None and v:
                entry["host"] = v
        elif t == "i" and entry["port"] is None and 1024 < v < 65536:
            entry["port"] = v
    entry["ipv4"].sort(key=rank_ip, reverse=True)
    return entry


def discover(timeout=8.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", MCAST_PORT))
    joined = False
    for ip in local_ipv4s():
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         socket.inet_aton(MCAST_ADDR) + socket.inet_aton(ip))
            joined = True
        except OSError:
            pass
    if not joined:
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         socket.inet_aton(MCAST_ADDR) + socket.inet_aton("0.0.0.0"))
        except OSError:
            pass
    s.settimeout(0.5)
    found = {}
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, src = s.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        e = parse_zdns(data)
        if not e or e["service"] != SERVICE or not e["port"]:
            continue
        e["source"] = src[0]
        key = (e["host"], e["port"])
        if key not in found:
            found[key] = e
            print("  LV1 trouvée : %s port %s, adresses %s (annonce reçue de %s)"
                  % (e["host"], e["port"], ", ".join(e["ipv4"]), src[0]))
            break  # une suffit pour le test
    s.close()
    return list(found.values())


# ─── Client ───────────────────────────────────────────────────────────────────

class Probe:
    def __init__(self, sock, style, device_name, verbose):
        self.sock = sock
        self.style = style
        self.device_name = device_name
        self.uuid = str(uuid.uuid4()).upper()
        self.verbose = verbose
        self.lock = threading.Lock()
        self.alive = True
        self.t0 = time.time()
        self.counts = collections.Counter()
        self.first_seen = {}
        self.examples = {}
        self.meter_times = []
        self.meter_frame_sizes = []
        self.meters_last = {}
        self.meters_min = {}
        self.meters_max = {}
        self.colors = {}
        self.color_events = []
        self.names = {}
        self.handshake_ack = threading.Event()
        self.session_id = threading.Event()
        self.log = []

    # envoi
    def send(self, address, args=()):
        self.sock.sendall(frame(address, args))

    def send_batch(self, msgs):
        self.sock.sendall(b"".join(frame(a, g) for a, g in msgs))

    def handshake(self):
        if self.style == "myfoh":
            self.send_batch([
                ("/handshake", [("i", 1), ("i", -1), ("i", 1)]),
                ("/device_name", [("s", self.device_name), ("s", self.uuid)]),
            ])
            return self.handshake_ack.wait(3.0)
        # style MyMon
        ip = self.sock.getsockname()[0]
        self.send_batch([("/Get/Aux/Tracks", []), ("/YourHostIP", [("s", ip)])])
        self.session_id.wait(3.0)
        self.send("/handshake", [("i", 1), ("i", -1), ("i", 0)])
        ok = self.handshake_ack.wait(3.0)
        if ok:
            self.send("/device_name", [("s", self.device_name), ("s", self.uuid)])
        return ok

    # réception
    def reader(self):
        buf = b""
        while self.alive:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            except OSError as e:
                if self.alive:
                    print("\n  Connexion perdue : %s" % e)
                self.alive = False
                break
            if not chunk:
                print("\n  La LV1 a fermé la connexion.")
                self.alive = False
                break
            buf += chunk
            packets, buf = split_frames(buf)
            for p in packets:
                try:
                    address, args = osc_decode(p)
                except Exception as e:
                    self.counts["<décodage impossible>"] += 1
                    continue
                self.on_message(address, args, len(p))

    def on_message(self, address, args, size):
        now = time.time() - self.t0
        with self.lock:
            self.counts[address] += 1
            if address not in self.first_seen:
                self.first_seen[address] = now
                self.examples[address] = short_args(args, 16)
        if address == "/ping":
            try:
                self.send("/pong", args)
            except OSError:
                pass
            return
        if address == "/handshake" and args and args[0] == ("i", 1):
            self.handshake_ack.set()
        elif address == "/Notify/CurrentSessionID":
            self.session_id.set()
        elif address == "/Notify/Meters":
            self.on_meters(args, now, size)
            return
        elif address == "/Notify/TrackColor":
            self.on_color(args, now)
        elif address in ("/Notify/Track/Name", "/Notify/TrackName"):
            if len(args) >= 3 and args[0][0] == "i" and args[1][0] == "i" and args[2][0] == "s":
                self.names[(args[0][1], args[1][1])] = args[2][1]
                say("  [%6.2f s] Nom      groupe %d canal %d -> %r" % (now, args[0][1], args[1][1], args[2][1]))
        elif address == "/Channels":
            self.on_channels(args)
        if self.verbose and address not in NOISY:
            say("  [%6.2f s] %s %s" % (now, address, short_args(args)))
        if address not in NOISY:
            self.log.append("%.3f %s %s" % (now, address, short_args(args, 40)))

    def on_meters(self, args, now, size):
        with self.lock:
            self.meter_times.append(now)
            n = 0
            for i in range(1, len(args) - 3, 4):
                g, ch, sub, db = args[i], args[i + 1], args[i + 2], args[i + 3]
                if g[0] != "i" or ch[0] != "i" or sub[0] != "i" or db[0] != "f":
                    continue
                key = (g[1], ch[1], sub[1])
                v = db[1]
                self.meters_last[key] = v
                self.meters_min[key] = min(v, self.meters_min.get(key, v))
                self.meters_max[key] = max(v, self.meters_max.get(key, v))
                n += 1
            self.meter_frame_sizes.append((n, size))

    def on_color(self, args, now):
        if len(args) < 6 or args[0][0] != "i" or args[1][0] != "i":
            say("  [%6.2f s] Couleur  format inattendu : %s" % (now, short_args(args)))
            return
        g, ch = args[0][1], args[1][1]
        rgb = [a[1] for a in args[3:6] if a[0] == "f"]
        if len(rgb) != 3:
            say("  [%6.2f s] Couleur  format inattendu : %s" % (now, short_args(args)))
            return
        scale = 255.0 if max(rgb) <= 1.0001 else 1.0
        hx = "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c * scale)))) for c in rgb)
        prev = self.colors.get((g, ch))
        self.colors[(g, ch)] = {"rgb_brut": rgb, "hex": hx, "arg2": args[2][1] if len(args) > 2 else None}
        self.color_events.append((now, g, ch, hx))
        if prev is None or prev["hex"] != hx:
            say("  [%6.2f s] Couleur  groupe %d canal %d -> %s  (brut %s)"
                  % (now, g, ch, hx, ", ".join("%.3f" % c for c in rgb)))

    def on_channels(self, args):
        if not args or args[0][0] != "i":
            return
        count = args[0][1]
        if count <= 0 or count > 256:
            return
        for i in range(count):
            base = 1 + i * 19
            if base + 2 >= len(args):
                break
            n, g, c = args[base], args[base + 1], args[base + 2]
            if n[0] == "s" and g[0] == "i" and c[0] == "i":
                self.names[(g[1], c[1])] = n[1]

    # affichage périodique
    def status_line(self):
        with self.lock:
            mt = list(self.meter_times)
            live = sorted(((k, v) for k, v in self.meters_last.items() if k[0] == 0 and k[2] == 0),
                          key=lambda kv: kv[0][1])
        rate = ""
        if len(mt) >= 2:
            recent = [b - a for a, b in zip(mt[-6:], mt[-5:])]
            if recent:
                rate = "dernier écart %.0f ms" % (1000 * recent[-1])
        loud = [(k, v) for k, v in live if v > -60][:6]
        txt = "  ".join("In%d %.1f" % (k[1] + 1, v) for k, v in loud) or "aucune entrée au-dessus de -60 dB"
        return "  vumètres : %d trames, %s | %s" % (len(mt), rate, txt)

    def report(self, host, port):
        mt = self.meter_times
        gaps = [b - a for a, b in zip(mt, mt[1:])]
        meter = {
            "trames": len(mt),
            "duree_observee_s": round(mt[-1] - mt[0], 2) if len(mt) > 1 else 0,
        }
        if gaps:
            meter.update({
                "ecart_moyen_ms": round(1000 * statistics.mean(gaps), 1),
                "ecart_median_ms": round(1000 * statistics.median(gaps), 1),
                "ecart_min_ms": round(1000 * min(gaps), 1),
                "ecart_max_ms": round(1000 * max(gaps), 1),
                "frequence_hz": round(1 / statistics.mean(gaps), 2),
            })
        if self.meter_frame_sizes:
            meter["valeurs_par_trame"] = max(n for n, _ in self.meter_frame_sizes)
            meter["octets_par_trame"] = max(s for _, s in self.meter_frame_sizes)
        moving = sorted(k for k in self.meters_max
                        if self.meters_max[k] - self.meters_min[k] > 3.0)
        meter["canaux_qui_ont_bouge"] = [
            {"groupe": g, "canal": c + 1, "voie": s,
             "min_db": round(self.meters_min[(g, c, s)], 1), "max_db": round(self.meters_max[(g, c, s)], 1)}
            for g, c, s in moving[:40]]
        groups = sorted({k[0] for k in self.meters_last})
        meter["groupes_presents"] = groups
        return {
            "date": datetime.datetime.now().isoformat(timespec="seconds"),
            "lv1": {"host": host, "port": port, "poignee_de_main": self.style},
            "vumetres": meter,
            "couleurs": {
                "nombre_de_canaux": len(self.colors),
                "changements_en_direct": len(self.color_events),
                "exemples": [{"groupe": g, "canal": c + 1, "nom": self.names.get((g, c)),
                              "hex": v["hex"], "rgb_brut": [round(x, 4) for x in v["rgb_brut"]],
                              "arg2": v["arg2"]}
                             for (g, c), v in sorted(self.colors.items())[:80]],
            },
            "adresses_recues": {a: {"nombre": n, "premiere_s": round(self.first_seen[a], 2),
                                    "exemple": self.examples[a]}
                                for a, n in self.counts.most_common()},
        }


def connect_any(addresses, port, timeout=5.0):
    last = None
    for ip in addresses:
        try:
            s = socket.create_connection((ip, port), timeout=timeout)
            s.settimeout(1.0)
            return s, ip
        except OSError as e:
            print("  Échec de connexion à %s:%d (%s)" % (ip, port, e))
            last = e
    raise last or OSError("aucune adresse")


def main():
    ap = argparse.ArgumentParser(description="Test LV1 : couleurs et vumètres (lecture seule).")
    ap.add_argument("--host", help="adresse IP de la LV1 (sinon découverte automatique)")
    ap.add_argument("--port", type=int, help="port TCP de la LV1 (change avec la config du mixer)")
    ap.add_argument("--duration", type=float, default=60.0, help="durée de l'écoute en secondes (60)")
    ap.add_argument("--style", choices=["myfoh", "mymon"], default="myfoh", help="poignée de main (myfoh)")
    ap.add_argument("--name", default="XTouch-Probe", help="nom affiché dans MyRemote ControlPanel")
    ap.add_argument("--verbose", action="store_true", help="affiche chaque message (hors vumètres et ping)")
    a = ap.parse_args()

    print("Test LV1 : couleurs et vumètres (lecture seule)")
    host, port = a.host, a.port
    addresses = [host] if host else []
    if not (host and port):
        print("Recherche de la LV1 sur le réseau (annonce /zDNS, 8 s max)…")
        found = discover()
        if host:
            found = [e for e in found if host in e["ipv4"]] or found
        if not found:
            print("\nAucune LV1 trouvée. Vérifie que la LV1 tourne, puis relance, ou donne --host et --port.")
            print("Astuce : le pare-feu Windows peut bloquer le multicast UDP 13337 pour Python.")
            return 2
        e = found[0]
        port = port or e["port"]
        addresses = addresses or (e["ipv4"] + [e["source"]])
        if not host:
            # Sur le même PC que la LV1, l'adresse locale marche aussi.
            if any(ip in local_ipv4s() for ip in e["ipv4"]):
                addresses = ["127.0.0.1"] + addresses
    seen = set()
    addresses = [x for x in addresses if not (x in seen or seen.add(x))]

    print("Connexion TCP au port %d…" % port)
    sock, ip = connect_any(addresses, port)
    print("  Connecté à %s:%d" % (ip, port))
    probe = Probe(sock, a.style, a.name, a.verbose)
    th = threading.Thread(target=probe.reader, daemon=True)
    th.start()
    if not probe.handshake():
        print("  Pas de réponse à la poignée de main (%s) en 3 s." % a.style)
        if a.style == "myfoh":
            print("  Essaie : py lv1_probe.py --style mymon")
        probe.alive = False
        sock.close()
        return 3
    print("  Poignée de main acceptée (%s). Demande de l'état…" % a.style)
    probe.send("/Get/Aux/Tracks", [])
    probe.send("/Get/Layers", [("i", 0), ("i", 0)])

    print("\nÉcoute pendant %.0f s. Pendant ce temps :" % a.duration)
    print("  1. envoie du signal sur quelques entrées (les vumètres doivent bouger) ;")
    print("  2. change la couleur d'un ou deux canaux dans la LV1 ;")
    print("  3. renomme un canal.\n")
    end = time.time() + a.duration
    try:
        while time.time() < end and probe.alive:
            time.sleep(1.0)
            sys.stdout.write("\r" + probe.status_line()[:150].ljust(150))
            sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n  Arrêt demandé.")
    probe.alive = False
    try:
        sock.close()
    except OSError:
        pass
    print("\n")

    rep = probe.report(ip, port)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    here = os.path.dirname(os.path.abspath(__file__))
    rpath = os.path.join(here, "lv1_probe_report_%s.json" % stamp)
    lpath = os.path.join(here, "lv1_probe_log_%s.txt" % stamp)
    with open(rpath, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    with open(lpath, "w", encoding="utf-8") as f:
        f.write("\n".join(probe.log))

    m = rep["vumetres"]
    print("=== Résultat ===")
    if m.get("trames", 0) >= 2:
        print("Vumètres : %d trames, une toutes les %.0f ms en moyenne (%.2f par seconde), "
              "écart min %.0f ms, max %.0f ms, %d valeurs par trame."
              % (m["trames"], m["ecart_moyen_ms"], m["frequence_hz"], m["ecart_min_ms"],
                 m["ecart_max_ms"], m.get("valeurs_par_trame", 0)))
        print("Canaux dont le niveau a varié de plus de 3 dB : %d" % len(m["canaux_qui_ont_bouge"]))
    else:
        print("Vumètres : pas assez de trames reçues (%d)." % m.get("trames", 0))
    c = rep["couleurs"]
    print("Couleurs : %d canaux reçus, %d changements vus en direct." % (c["nombre_de_canaux"], c["changements_en_direct"]))
    print("\nRapport : %s\nJournal : %s" % (rpath, lpath))
    print("Envoie-moi le fichier rapport (.json).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
