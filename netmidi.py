# -*- coding: utf-8 -*-
"""X-Touch par le réseau (0.8.1, demande de Joseph du 02/11 : LV1 dans une VM Unraid sans écran, pilotée en RDP).

Les clics sur la LV1, l'overlay, la lecture de l'écran et de la base se font sur le PC où tourne XTouch-LV1 : il doit
donc tourner sur le PC de la LV1. La X-Touch, elle, est branchée en USB sur un autre PC (le portable de Joseph) :

- PC de la LV1 (« hôte ») : ``RelayHub`` écoute TCP ``PORT`` ; les ports MIDI du relais apparaissent à côté des ports
  USB (``CombinedOut`` / ``CombinedIn``, mêmes noms « X-TOUCH… ») : le pont les ouvre comme une X-Touch branchée.
- PC de la X-Touch (« relais ») : ``Relay`` ouvre la X-Touch / l'Extender en USB et fait suivre le MIDI dans les deux
  sens (boutons et faders vers l'hôte ; écrans, LED, moteurs vers la X-Touch). Pas de RTP MIDI ni de port virtuel.

Trames : [taille 4 octets BE][type 1 octet][données]. Relais -> hôte : b"H" JSON {"name", "version", "outs", "ins"}
(ports X-Touch du relais, renvoyé à chaque changement), b"I" [n° d'entrée, status, d1, d2]. Hôte -> relais : b"S"
[n° de sortie, status, d1, d2], b"L" [n° de sortie] + SysEx. Une seule X-Touch par hôte : un 2e relais remplace le 1er.
"""
import json
import socket
import struct
import sys
import threading
import time

PORT = 9310
NET_BASE = 1000          # numéros des ports réseau dans les listes de CombinedOut / CombinedIn


def frame(kind, payload=b""):
    return struct.pack(">I", 1 + len(payload)) + kind + payload


def split(buf):
    """Trames complètes de ``buf`` -> ([(type, données)], reste)."""
    out = []
    while len(buf) >= 4:
        n = struct.unpack(">I", buf[:4])[0]
        if n < 1 or n > 1 << 20:
            raise OSError("trame réseau invalide")
        if len(buf) < 4 + n:
            break
        out.append((buf[4:5], buf[5:4 + n]))
        buf = buf[4 + n:]
    return out, buf


def is_private(ip):
    """Adresse d'un réseau local (ou Tailscale 100.64/10) : seules acceptées par l'hôte."""
    p = [int(x) for x in ip.split(".")] if ip.count(".") == 3 else []
    return bool(p) and (p[0] in (10, 127) or (p[0] == 192 and p[1] == 168) or (p[0] == 172 and 16 <= p[1] <= 31)
                        or (p[0] == 169 and p[1] == 254) or (p[0] == 100 and 64 <= p[1] <= 127))


# ─── Hôte (PC de la LV1) ──────────────────────────────────────────────────────────────────────────────────────────

class NetHandle:
    def __init__(self, port, gen):
        self.port, self.gen = port, gen


class RelayHub(threading.Thread):
    """Serveur TCP du PC de la LV1 : un relais à la fois ; ses ports MIDI dans ``outs`` / ``ins``."""

    def __init__(self, port=PORT, log=print):
        super().__init__(daemon=True, name="relay-hub")
        self.port, self.log = port, log
        self.lock = threading.Lock()
        self.sock = None
        self.gen = 0                 # change à chaque relais : les poignées d'avant deviennent invalides
        self.peer = None             # (adresse, nom du PC) du relais connecté
        self.outs, self.ins = [], []
        self.in_units = {}           # n° d'entrée du relais -> unité du pont
        self.events = None           # file des messages reçus (celle de WinMidiIn)
        self.stop_flag = False
        self.error = None

    # -- côté pont -------------------------------------------------------------------------------------------------
    def send(self, h, payload_kind, payload):
        with self.lock:
            if h.gen != self.gen or self.sock is None:
                raise OSError("X-Touch réseau déconnectée")
            sock = self.sock
        try:
            sock.sendall(frame(payload_kind, payload))
        except OSError as e:
            self._drop(sock, "envoi impossible : %s" % e)
            raise OSError("X-Touch réseau : %s" % e)

    def short(self, h, status, d1, d2=0):
        self.send(h, b"S", bytes((h.port & 0xFF, status & 0xFF, d1 & 0x7F, d2 & 0x7F)))

    def long(self, h, data):
        self.send(h, b"L", bytes((h.port & 0xFF,)) + bytes(data))

    def open_out(self, port):
        with self.lock:
            if self.sock is None or port >= len(self.outs):
                raise OSError("port réseau %d absent" % port)
            return NetHandle(port, self.gen)

    def open_in(self, port, unit):
        with self.lock:
            if self.sock is None or port >= len(self.ins):
                raise OSError("entrée réseau %d absente" % port)
            self.in_units[port] = unit

    def close_ins(self):
        with self.lock:
            self.in_units = {}

    # -- réseau ----------------------------------------------------------------------------------------------------
    def run(self):
        while not self.stop_flag:
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE if sys.platform == "win32"
                               else socket.SO_REUSEADDR, 1)
                srv.bind(("", self.port))
                srv.listen(2)
                srv.settimeout(1.0)
            except OSError as e:
                self.error = str(e)
                self.log("  X-Touch réseau : écoute TCP %d impossible (%s), nouvel essai dans 10 s" % (self.port, e))
                time.sleep(10)
                continue
            self.error = None
            try:
                while not self.stop_flag:
                    try:
                        conn, addr = srv.accept()
                    except socket.timeout:
                        continue
                    if not is_private(addr[0]):
                        self.log("  X-Touch réseau : %s refusé (pas un réseau local)" % addr[0])
                        conn.close()
                        continue
                    threading.Thread(target=self._serve, args=(conn, addr), daemon=True).start()
            finally:
                srv.close()

    def _drop(self, sock, why):
        with self.lock:
            if self.sock is not sock:
                return
            self.sock, self.outs, self.ins, self.in_units = None, [], [], {}
            self.gen += 1
            peer, self.peer = self.peer, None
        try:
            sock.close()
        except OSError:
            pass
        self.log("  X-Touch réseau : relais %s parti (%s)" % (peer and peer[1], why))

    def _serve(self, conn, addr):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(1.0)
        with self.lock:
            old = self.sock
        if old is not None:
            self._drop(old, "remplacé par %s" % addr[0])
        with self.lock:
            self.sock, self.gen, self.peer = conn, self.gen + 1, (addr[0], "?")
        buf = b""
        try:
            while not self.stop_flag:
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    with self.lock:
                        if self.sock is not conn:
                            return
                    continue
                if not chunk:
                    raise OSError("connexion fermée")
                frames, buf = split(buf + chunk)
                for kind, data in frames:
                    if kind == b"H":
                        hello = json.loads(data.decode("utf-8"))
                        with self.lock:
                            if self.sock is not conn:
                                return
                            changed = (hello.get("outs"), hello.get("ins")) != (self.outs, self.ins)
                            self.outs, self.ins = list(hello.get("outs") or []), list(hello.get("ins") or [])
                            self.peer = (addr[0], hello.get("name") or addr[0])
                            if changed:              # ports changés (USB rebranché) : poignées d'avant invalides
                                self.gen += 1
                                self.in_units = {}
                        self.log("  X-Touch réseau : relais %s (%s), ports %s" % (self.peer[1], addr[0], self.outs))
                    elif kind == b"I" and len(data) == 4:
                        with self.lock:
                            unit = self.in_units.get(data[0]) if self.sock is conn else None
                            q = self.events
                        if unit is not None and q is not None:
                            q.put((unit, data[1], data[2], data[3], time.time()))
        except (OSError, ValueError) as e:
            self._drop(conn, str(e))
        else:
            self._drop(conn, "arrêt")


class CombinedOut:
    """Sorties MIDI du pont : ports USB (``local``) puis ports du relais (numéros >= NET_BASE)."""

    def __init__(self, local, hub):
        self.local, self.hub = local, hub

    def list(self):
        out = list(self.local.list()) if self.local else []
        with self.hub.lock:
            net = list(self.hub.outs) if self.hub.sock is not None else []
        return out + [(NET_BASE + i, name) for i, name in enumerate(net)]

    def open(self, index):
        if index >= NET_BASE:
            return self.hub.open_out(index - NET_BASE)
        return self.local.open(index)

    def short(self, h, status, d1, d2=0):
        if isinstance(h, NetHandle):
            return self.hub.short(h, status, d1, d2)
        return self.local.short(h, status, d1, d2)

    def long(self, h, data):
        if isinstance(h, NetHandle):
            return self.hub.long(h, data)
        return self.local.long(h, data)

    def close(self, h):
        if not isinstance(h, NetHandle):
            self.local.close(h)


class CombinedIn:
    """Entrées MIDI du pont : USB (``local``, WinMidiIn) puis relais ; même file de messages."""

    def __init__(self, local, hub, events):
        self.local, self.hub = local, hub
        hub.events = events

    def list(self):
        out = list(self.local.list()) if self.local else []
        with self.hub.lock:
            net = list(self.hub.ins) if self.hub.sock is not None else []
        return out + [(NET_BASE + i, name) for i, name in enumerate(net)]

    def open(self, index, unit):
        if index >= NET_BASE:
            return self.hub.open_in(index - NET_BASE, unit)
        return self.local.open(index, unit)

    def close_all(self):
        if self.local:
            self.local.close_all()
        self.hub.close_ins()


# ─── Relais (PC de la X-Touch) ────────────────────────────────────────────────────────────────────────────────────

def relay_reachable(ips, port=PORT, timeout=0.6):
    """Première adresse de ``ips`` où un hôte XTouch-LV1 écoute, sinon None."""
    for ip in ips:
        try:
            socket.create_connection((ip, port), timeout=timeout).close()
            return ip
        except OSError:
            continue
    return None


class Relay:
    """Fait suivre la X-Touch / l'Extender branchées ici vers l'hôte ``host`` (PC de la LV1)."""

    def __init__(self, hosts, name, version, midi_out, midi_in_factory, pick_ports, stop, log=print, port=PORT):
        self.hosts, self.name, self.version, self.port = list(hosts), name, version, port
        self.midi_out, self.midi_in_factory, self.pick_ports = midi_out, midi_in_factory, pick_ports
        self.stop, self.log = stop, log
        self.outs, self.ins = [], []       # [(index winmm, nom, poignée)]
        self.midi_in = None
        self.sock = None
        self.lock = threading.Lock()
        self.connected_to = None

    def _xtouch(self, ports):
        main, ext = self.pick_ports(ports, None, None)
        names = dict(ports)
        return [(i, names[i]) for i in (main, ext) if i is not None]

    def open_ports(self):
        """Ouvre les ports X-Touch présents (sorties et entrées) ; True s'ils ont changé."""
        want_out = self._xtouch(self.midi_out.list())
        probe_in = self.midi_in_factory()
        want_in = self._xtouch(probe_in.list())
        if [p[:2] for p in self.outs] == want_out and [p[:2] for p in self.ins] == want_in:
            return False
        self.close_ports()
        for i, name in want_out:
            try:
                self.outs.append((i, name, self.midi_out.open(i)))
            except OSError as e:
                self.log("  Relais : sortie %s : %s" % (name, e))
        self.midi_in = probe_in
        for k, (i, name) in enumerate(want_in):
            try:
                self.midi_in.open(i, k)
                self.ins.append((i, name, None))
            except OSError as e:
                self.log("  Relais : entrée %s : %s" % (name, e))
        return True

    def close_ports(self):
        for _i, _n, h in self.outs:
            try:
                self.midi_out.close(h)
            except OSError:
                pass
        if self.midi_in:
            self.midi_in.close_all()
        self.outs, self.ins = [], []

    def hello(self):
        return frame(b"H", json.dumps({"name": self.name, "version": self.version,
                                        "outs": [n for _i, n, _h in self.outs],
                                        "ins": [n for _i, n, _h in self.ins]}).encode("utf-8"))

    def send_input(self, unit, status, d1, d2):
        with self.lock:
            if self.sock is not None:
                try:
                    self.sock.sendall(frame(b"I", bytes((unit & 0xFF, status & 0xFF, d1 & 0x7F, d2 & 0x7F))))
                except OSError:
                    pass

    def _forward(self, sock, events):
        """Fil : boutons / faders de la X-Touch -> hôte, dès leur arrivée (le fader suit le doigt sans attente)."""
        import queue
        while not self.stop.is_set() and self.sock is sock:
            try:
                unit, st, d1, d2, _t = events.get(timeout=0.2)
            except queue.Empty:
                continue
            self.send_input(unit, st, d1, d2)

    def play(self, kind, data):
        if not data or data[0] >= len(self.outs):
            return
        h = self.outs[data[0]][2]
        try:
            if kind == b"S" and len(data) == 4:
                self.midi_out.short(h, data[1], data[2], data[3])
            elif kind == b"L":
                self.midi_out.long(h, data[1:])
        except OSError as e:
            self.log("  Relais : X-Touch perdue (%s)" % e)
            self.outs = []                    # rouvert au prochain tour (open_ports)

    def run(self, events):
        """Boucle du relais jusqu'à ``stop`` : connexion à l'hôte, ports rouverts toutes les 2 s si besoin."""
        while not self.stop.is_set():
            ip = relay_reachable(self.hosts, self.port, timeout=2.0)
            if ip is None:
                self.log("  Relais : PC de la LV1 injoignable (%s:%d), nouvel essai dans 3 s"
                         % ("/".join(self.hosts), self.port))
                self.stop.wait(3)
                continue
            try:
                self._session(ip, events)
            except OSError as e:
                self.log("  Relais : %s" % e)
            with self.lock:
                self.sock = None
            self.connected_to = None
            self.stop.wait(2)
        self.close_ports()

    def _session(self, ip, events):
        sock = socket.create_connection((ip, self.port), timeout=3)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(0.5)
        self.open_ports()
        sock.sendall(self.hello())
        with self.lock:
            self.sock = sock
        threading.Thread(target=self._forward, args=(sock, events), daemon=True).start()
        self.connected_to = ip
        self.log("  Relais : X-Touch envoyée à %s (%s)" % (ip, ", ".join(n for _i, n, _h in self.outs) or "aucune"))
        buf, t_ports = b"", time.time()
        try:
            while not self.stop.is_set():
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    chunk = None
                if chunk == b"":
                    raise OSError("l'hôte a fermé la connexion")
                if chunk:
                    frames, buf = split(buf + chunk)
                    for kind, data in frames:
                        self.play(kind, data)
                if time.time() - t_ports > 2.0:          # X-Touch débranchée / rebranchée ici
                    t_ports = time.time()
                    if self.open_ports():
                        with self.lock:
                            sock.sendall(self.hello())
        finally:
            with self.lock:
                self.sock = None
            sock.close()
