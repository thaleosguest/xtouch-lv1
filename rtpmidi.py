# -*- coding: utf-8 -*-
"""X-Touch / Extender par leur prise Ethernet, en RTP-MIDI direct (sans pilote ni PC relais).

Vérifié sur le matériel de Joseph le 10/11/2026 : X-Touch 192.168.1.38 (contrôle UDP 5008), Extender 192.168.1.39
(contrôle 5006), réglage de l'appareil = MC, esclave : c'est le PC qui invite.

- Session AppleMIDI : ``IN`` sur le port de contrôle puis sur le port de données (contrôle + 1), synchro d'horloge
  ``CK`` (0 / 1 / 2), paquets RTP (type 97), accusés ``RS``, ``BY`` pour finir.
- **Piège** : le port de données du PC doit être le port de contrôle du PC + 1, sinon l'invitation sur le port de
  données reste sans réponse.
- ``RtpHub`` tient une session par appareil de ``xtouch_rtpmidi.json`` et la refait toute seule (appareil éteint,
  câble). ``RtpOut`` / ``RtpIn`` s'empilent sur les ports existants (USB winmm, relais ``netmidi``) : le pont ne voit
  que des ports « X-TOUCH… » de plus (numéros >= RTP_BASE) et les ouvre comme une X-Touch branchée.
- Pas de journal de retransmission : un paquet perdu est compté (``lost_in``) et noté, pas rattrapé ; un paquet
  arrivé en retard est jeté (une vieille position de fader ne doit pas repasser devant la nouvelle).

Réglages : {"devices": [{"name": "X-TOUCH", "ip": "192.168.1.38", "port": 5008},
                        {"name": "X-TOUCH-EXT", "ip": "192.168.1.39", "port": 5006}]}
Essai sur le matériel : py rtpmidi.py [--text] [--seconds 10] [ip:port[:nom] ...]
"""
import json
import os
import random
import select
import socket
import struct
import threading
import time

RTP_BASE = 2000          # numéros des ports RTP-MIDI dans les listes de RtpOut / RtpIn (netmidi : 1000)
CONFIG = "xtouch_rtpmidi.json"
OUR_NAME = b"XTouch-LV1"
SIG = b"\xff\xff"        # début des paquets de session AppleMIDI
PAYLOAD_TYPE = 97
MAX_MIDI = 1400          # un message par paquet UDP, sans découpage (écran Mackie complet = 120 octets)


# ─── Paquets (fonctions pures) ────────────────────────────────────────────────────────────────────────────────────

def session_packet(cmd, token, ssrc, name=None):
    """``IN`` / ``OK`` / ``NO`` / ``BY`` : version 2, jeton, émetteur, nom (sauf ``BY``)."""
    return SIG + cmd + struct.pack(">III", 2, token, ssrc) + (name + b"\0" if name is not None else b"")


def ck_packet(ssrc, count, stamps):
    t = list(stamps) + [0] * (3 - len(stamps))
    return SIG + b"CK" + struct.pack(">IB3xQQQ", ssrc, count, *t)


def rs_packet(ssrc, seq):
    return SIG + b"RS" + struct.pack(">IHH", ssrc, seq & 0xFFFF, 0)


def parse_session(pk):
    """Paquet de session -> (commande, champs) ou None. ``CK`` : (émetteur, n°, [t1, t2, t3]) ; ``RS`` : (émetteur,
    séquence) ; les autres : (jeton, émetteur, nom)."""
    if len(pk) < 4 or pk[:2] != SIG:
        return None
    cmd = pk[2:4]
    if cmd == b"CK":
        if len(pk) < 36:
            return None
        ssrc, count = struct.unpack(">IB", pk[4:9])
        return cmd, (ssrc, count, list(struct.unpack(">QQQ", pk[12:36])))
    if cmd == b"RS":
        if len(pk) < 10:
            return None
        return cmd, struct.unpack(">IH", pk[4:10])
    if len(pk) < 16:
        return None
    _version, token, ssrc = struct.unpack(">III", pk[4:16])
    return cmd, (token, ssrc, pk[16:].split(b"\0")[0])


def encode_commands(messages):
    """Section de commandes MIDI d'un paquet RTP : messages complets (status compris), temps delta 0 entre eux."""
    body = b""
    for i, m in enumerate(messages):
        body += (b"\0" if i else b"") + bytes(m)
    if len(body) > 0x0FFF:
        raise OSError("message MIDI trop long pour un paquet RTP (%d octets)" % len(body))
    if len(body) > 15:
        return bytes((0x80 | (len(body) >> 8), len(body) & 0xFF)) + body
    return bytes((len(body),)) + body


def rtp_packet(seq, stamp, ssrc, messages):
    return struct.pack(">BBHII", 0x80, 0x80 | PAYLOAD_TYPE, seq & 0xFFFF, stamp & 0xFFFFFFFF, ssrc) \
        + encode_commands(messages)


def parse_rtp(pk):
    """Paquet RTP-MIDI -> (séquence, émetteur, section MIDI) ou None."""
    if len(pk) < 13 or pk[0] & 0xC0 != 0x80 or pk[1] & 0x7F != PAYLOAD_TYPE:
        return None
    seq, _stamp, ssrc = struct.unpack(">HII", pk[2:12])
    return seq, ssrc, pk[12 + 4 * (pk[0] & 0x0F):]


_DATA_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}
_SYS_LEN = {0xF1: 1, 0xF2: 2, 0xF3: 1}


def decode_commands(payload):
    """Section de commandes MIDI -> [(status, d1, d2)] des messages de canal (notes, CC, pitch bend…).

    Gère la longueur sur 12 bits, les temps delta, le status courant (running status), les SysEx (entiers ou en
    morceaux : sautés, le pont n'en lit pas) et le journal de retransmission (ignoré). Un paquet abîmé rend ce qui
    a pu être lu."""
    out = []
    if not payload:
        return out
    flags = payload[0]
    n, pos = flags & 0x0F, 1
    if flags & 0x80:
        if len(payload) < 2:
            return out
        n, pos = (n << 8) | payload[1], 2
    end = min(len(payload), pos + n)
    first, running = True, None
    while pos < end:
        if not first or flags & 0x20:                    # temps delta (1 à 4 octets), absent du 1er sauf drapeau Z
            for _ in range(4):
                if pos >= end:
                    return out
                more = payload[pos] & 0x80
                pos += 1
                if not more:
                    break
            if pos >= end:
                return out
        first = False
        b = payload[pos]
        if b >= 0xF8:                                    # temps réel : un octet, ne touche pas au status courant
            pos += 1
            continue
        if b in (0xF0, 0xF7):                            # SysEx ou suite de SysEx : jusqu'à F7 / F0 / F4
            pos += 1
            while pos < end and payload[pos] < 0x80:
                pos += 1
            pos += 1
            running = None
            continue
        if b >= 0xF0:                                    # messages système communs
            pos += 1 + _SYS_LEN.get(b, 0)
            running = None
            continue
        if b >= 0x80:
            running = b
            pos += 1
        if running is None:
            return out
        need = _DATA_LEN[running & 0xF0]
        if pos + need > end:
            return out
        data = payload[pos:pos + need]
        if any(x & 0x80 for x in data):
            return out
        pos += need
        out.append((running, data[0], data[1] if need == 2 else 0))
    return out


def is_private(ip):
    """Adresse d'un réseau local : les seules où l'on envoie des invitations."""
    try:
        p = [int(x) for x in ip.split(".")]
    except (ValueError, AttributeError):
        return False
    return len(p) == 4 and all(0 <= x <= 255 for x in p) and (
        p[0] in (10, 127) or (p[0] == 192 and p[1] == 168) or (p[0] == 172 and 16 <= p[1] <= 31)
        or (p[0] == 169 and p[1] == 254))


def load_config(path):
    """Appareils de ``xtouch_rtpmidi.json`` : [{"name", "ip", "port"}] ; [] si absent ou illisible (-> USB seul)."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f).get("devices") or []
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for d in raw:
        try:
            name, ip, port = str(d["name"]), str(d["ip"]), int(d["port"])
        except (KeyError, TypeError, ValueError):
            continue
        if name and is_private(ip) and 0 < port < 65535:
            out.append({"name": name, "ip": ip, "port": port})
    return out


# ─── Sessions ─────────────────────────────────────────────────────────────────────────────────────────────────────

class RtpHandle:
    def __init__(self, index, gen):
        self.index, self.gen = index, gen


class _Session:
    def __init__(self, index, name, ip, port):
        self.index, self.name, self.ip, self.port = index, name, ip, port
        self.state = "idle"          # idle -> ctrl -> data -> sync -> up
        self.c = self.d = None       # sockets de contrôle et de données (ports locaux P et P + 1)
        self.gen = 0                 # change à chaque session : les poignées d'avant deviennent invalides
        self.token = 0
        self.next_try = 0.0
        self.t_state = self.t_sent = self.t_ck = self.t_rs = self.last_in = 0.0
        self.tries = 0
        self.seq_out = 0
        self.seq_in = None           # dernière séquence reçue de l'appareil
        self.rs_due = False
        self.unit = None             # unité du pont (entrée ouverte) ou None
        self.lost_in = self.late_in = 0
        self.latency_ms = None       # aller simple mesuré par la synchro d'horloge
        self.warned = False
        self.peer_name = ""
        self.peer_ssrc = None        # émetteur annoncé par l'appareil (un BY d'un autre émetteur est ignoré)


class RtpHub(threading.Thread):
    """Une session RTP-MIDI par appareil ; ports listés seulement quand la session est établie et synchronisée."""

    def __init__(self, devices, log=print, ck_period=3.0, timeout=9.0, retry=3.0, invite_wait=1.0):
        super().__init__(daemon=True, name="rtp-midi")
        self.log = log
        self.ck_period, self.timeout, self.retry, self.invite_wait = ck_period, timeout, retry, invite_wait
        self.lock = threading.Lock()
        self.sessions = [_Session(i, d["name"], d["ip"], int(d["port"])) for i, d in enumerate(devices)]
        self.events = None           # file des messages reçus (celle de WinMidiIn)
        self.ssrc = random.getrandbits(32) or 1
        self.t0 = time.monotonic()
        self.stop_flag = False

    def clock(self):
        return int((time.monotonic() - self.t0) * 10000)            # horloge 10 kHz, comme l'essai du 10/11

    # -- côté pont -------------------------------------------------------------------------------------------------
    def list(self):
        with self.lock:
            return [(RTP_BASE + s.index, s.name) for s in self.sessions if s.state == "up"]

    def open_out(self, index):
        with self.lock:
            s = self._get(index)
            return RtpHandle(index, s.gen)

    def open_in(self, index, unit):
        with self.lock:
            self._get(index).unit = unit

    def close_ins(self):
        with self.lock:
            for s in self.sessions:
                s.unit = None

    def _get(self, index):
        if not 0 <= index < len(self.sessions) or self.sessions[index].state != "up":
            raise OSError("port RTP-MIDI %d absent" % index)
        return self.sessions[index]

    def send(self, h, message):
        if len(message) > MAX_MIDI:
            raise OSError("message MIDI trop long (%d octets)" % len(message))
        with self.lock:
            s = self.sessions[h.index] if 0 <= h.index < len(self.sessions) else None
            if s is None or s.state != "up" or s.gen != h.gen:
                raise OSError("X-Touch RTP-MIDI déconnectée")
            s.seq_out = (s.seq_out + 1) & 0xFFFF
            try:
                s.d.sendto(rtp_packet(s.seq_out, self.clock(), self.ssrc, [message]), (s.ip, s.port + 1))
            except OSError as e:
                raise OSError("X-Touch RTP-MIDI : %s" % e)

    def short(self, h, status, d1, d2=0):
        st = status & 0xFF
        if st & 0xF0 in (0xC0, 0xD0):                    # programme, pression (vumètres Mackie) : un seul octet
            self.send(h, bytes((st, d1 & 0x7F)))
        else:
            self.send(h, bytes((st, d1 & 0x7F, d2 & 0x7F)))

    def long(self, h, data):
        self.send(h, bytes(data))

    def stale(self, h):
        """True si ``h`` est une poignée RTP-MIDI dont la session est tombée (même revenue depuis) : le pont doit tout
        rouvrir, sans attendre qu'un envoi échoue (sans vumètre ni geste, rien n'est envoyé pendant des minutes)."""
        if not isinstance(h, RtpHandle):
            return False
        with self.lock:
            s = self.sessions[h.index] if 0 <= h.index < len(self.sessions) else None
            return s is None or s.state != "up" or s.gen != h.gen

    def status(self):
        """État lisible de chaque appareil (menu de l'icône, journal, essais)."""
        with self.lock:
            return [{"name": s.name, "ip": s.ip, "port": s.port, "up": s.state == "up", "latency_ms": s.latency_ms,
                     "lost": s.lost_in, "late": s.late_in, "peer": s.peer_name} for s in self.sessions]

    def stop(self):
        """Fin propre : ``BY`` à chaque appareil (sinon il garde la session jusqu'à son propre délai)."""
        self.stop_flag = True
        if self.is_alive() and threading.current_thread() is not self:
            self.join(2.0)
        for s in self.sessions:
            self._down(s, None)

    # -- réseau ----------------------------------------------------------------------------------------------------
    def run(self):
        while not self.stop_flag:
            now = time.monotonic()
            socks = {}
            for s in self.sessions:
                try:
                    self._step(s, now)
                except OSError as e:
                    self._down(s, str(e))
                if s.c is not None:
                    socks[s.c], socks[s.d] = (s, False), (s, True)
            if not socks:
                time.sleep(0.05)
                continue
            try:
                ready = select.select(list(socks), [], [], 0.05)[0]
            except (OSError, ValueError):
                continue
            for sock in ready:
                s, is_data = socks[sock]
                for _ in range(64):                      # vider ce qui est arrivé, sans affamer l'autre appareil
                    if sock is not (s.d if is_data else s.c):
                        break                            # session fermée pendant le traitement
                    try:
                        pk, addr = sock.recvfrom(4096)
                    except (BlockingIOError, InterruptedError):
                        break
                    except OSError:
                        break                            # Windows : « connexion réinitialisée » après un ICMP
                    if addr[0] != s.ip:
                        continue
                    try:
                        self._packet(s, is_data, pk, time.monotonic())
                    except OSError as e:
                        self._down(s, str(e))

    def _open(self, s):
        for _ in range(50):
            base = random.randrange(40000, 60000, 2)
            c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            d = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                c.bind(("", base))
                d.bind(("", base + 1))                   # le piège : données = contrôle + 1
            except OSError:
                c.close()
                d.close()
                continue
            c.setblocking(False)
            d.setblocking(False)
            s.c, s.d = c, d
            return
        raise OSError("aucune paire de ports UDP libre")

    def _invite(self, s, data, now):
        sock, port = (s.d, s.port + 1) if data else (s.c, s.port)
        sock.sendto(session_packet(b"IN", s.token, self.ssrc, OUR_NAME), (s.ip, port))
        s.t_sent = now

    def _sync(self, s, now):
        s.d.sendto(ck_packet(self.ssrc, 0, [self.clock()]), (s.ip, s.port + 1))
        s.t_ck = now

    def _step(self, s, now):
        if s.state == "idle":
            if now < s.next_try:
                return
            self._open(s)
            s.token = random.getrandbits(32)
            s.state, s.tries, s.t_state = "ctrl", 1, now
            self._invite(s, False, now)
        elif s.state in ("ctrl", "data"):
            if now - s.t_sent >= self.invite_wait:
                s.tries += 1
                if s.tries > 3:
                    return self._down(s, "pas de réponse à l'invitation")
                self._invite(s, s.state == "data", now)
        elif s.state == "sync":
            if now - s.t_state > 5 * self.invite_wait:
                return self._down(s, "pas de synchro d'horloge")
            if now - s.t_ck >= 0.5 * self.invite_wait:
                self._sync(s, now)
        elif s.state == "up":
            if now - s.last_in > self.timeout:
                return self._down(s, "plus de réponse depuis %.0f s" % (now - s.last_in))
            if now - s.t_ck >= self.ck_period:
                self._sync(s, now)
            if s.rs_due and now - s.t_rs >= 1.0:
                s.c.sendto(rs_packet(self.ssrc, s.seq_in), (s.ip, s.port))
                s.rs_due, s.t_rs = False, now

    def _down(self, s, why):
        """Ferme la session (``BY`` si l'appareil nous connaît) ; nouvel essai après ``retry``."""
        with self.lock:
            was, c, d = s.state, s.c, s.d
            s.state, s.c, s.d, s.unit = "idle", None, None, None
            s.gen += 1
            s.seq_in, s.rs_due, s.latency_ms = None, False, None
            s.next_try = time.monotonic() + self.retry
        if c is None:
            return
        if was != "ctrl" and why != "BY":
            bye = session_packet(b"BY", s.token, self.ssrc)
            for sock, port in ((d, s.port + 1), (c, s.port)):
                try:
                    sock.sendto(bye, (s.ip, port))
                except OSError:
                    pass
        c.close()
        d.close()
        if why is None:
            return
        if was == "up":
            self.log("  X-Touch RTP-MIDI : %s (%s) partie (%s)" % (s.name, s.ip, why))
            s.warned = False
        elif not s.warned:
            s.warned = True
            self.log("  X-Touch RTP-MIDI : %s (%s:%d) injoignable (%s), nouvel essai toutes les %g s"
                     % (s.name, s.ip, s.port, why, self.retry))

    def _packet(self, s, is_data, pk, now):
        if pk[:2] != SIG:
            if is_data and s.state == "up":
                self._midi(s, pk, now)
            return
        parsed = parse_session(pk)
        if parsed is None:
            return
        cmd, f = parsed
        if cmd == b"OK":
            if f[0] != s.token:
                return
            if s.state == "ctrl" and not is_data:
                s.state, s.tries = "data", 1
                s.peer_name, s.peer_ssrc = f[2].decode("utf-8", "replace"), f[1]
                self._invite(s, True, now)
            elif s.state == "data" and is_data:
                s.state, s.t_state = "sync", now
                self._sync(s, now)
        elif cmd == b"NO":
            if f[0] == s.token and s.state in ("ctrl", "data"):
                self._down(s, "invitation refusée")
        elif cmd == b"BY":
            if s.state != "idle" and f[1] == s.peer_ssrc:
                self._down(s, "BY")
        elif cmd == b"IN":                               # l'appareil est esclave : ce n'est pas à lui d'inviter
            sock, port = (s.d, s.port + 1) if is_data else (s.c, s.port)
            sock.sendto(session_packet(b"NO", f[0], self.ssrc, OUR_NAME), (s.ip, port))
        elif cmd == b"CK":
            _ssrc, count, t = f
            s.last_in = now
            sock, port = (s.d, s.port + 1) if is_data else (s.c, s.port)
            if count == 0:
                sock.sendto(ck_packet(self.ssrc, 1, [t[0], self.clock()]), (s.ip, port))
            elif count == 1:
                clock = self.clock()
                sock.sendto(ck_packet(self.ssrc, 2, [t[0], t[1], clock]), (s.ip, port))
                rtt = clock - t[0]
                if s.state == "sync":
                    with self.lock:
                        s.state, s.seq_out, s.seq_in = "up", random.getrandbits(16), None
                        s.lost_in = s.late_in = 0
                    s.warned = False
                    self.log("  X-Touch RTP-MIDI : %s (%s:%d) connectée%s"
                             % (s.name, s.ip, s.port, " [%s]" % s.peer_name if s.peer_name else ""))
                if 0 <= rtt < 100000:
                    s.latency_ms = rtt / 20.0
        # RS (accusé de l'appareil) : rien à faire, on ne tient pas de journal

    def _midi(self, s, pk, now):
        parsed = parse_rtp(pk)
        if parsed is None:
            return
        seq, _ssrc, payload = parsed
        s.last_in = now
        if s.seq_in is not None:
            ahead = (seq - s.seq_in) & 0xFFFF
            if ahead == 0 or ahead >= 0x8000:            # doublon ou paquet en retard : jeté
                s.late_in += 1
                return
            if ahead > 1:
                s.lost_in += ahead - 1
                self.log("  X-Touch RTP-MIDI : %s : %d paquet(s) perdu(s)" % (s.name, ahead - 1))
        s.seq_in, s.rs_due = seq, True
        with self.lock:
            unit, q = s.unit, self.events
        if unit is None or q is None:
            return
        t = time.time()
        for st, d1, d2 in decode_commands(payload):
            q.put((unit, st, d1, d2, t))


# ─── Ports du pont ────────────────────────────────────────────────────────────────────────────────────────────────

class RtpOut:
    """Sorties MIDI du pont : celles de ``inner`` (USB, relais) puis les appareils RTP-MIDI (numéros >= RTP_BASE)."""

    def __init__(self, inner, hub):
        self.inner, self.hub = inner, hub

    def list(self):
        return (list(self.inner.list()) if self.inner else []) + self.hub.list()

    def open(self, index):
        if index >= RTP_BASE:
            return self.hub.open_out(index - RTP_BASE)
        return self.inner.open(index)

    def short(self, h, status, d1, d2=0):
        if isinstance(h, RtpHandle):
            return self.hub.short(h, status, d1, d2)
        return self.inner.short(h, status, d1, d2)

    def long(self, h, data):
        if isinstance(h, RtpHandle):
            return self.hub.long(h, data)
        return self.inner.long(h, data)

    def close(self, h):
        if not isinstance(h, RtpHandle):
            self.inner.close(h)


class RtpIn:
    """Entrées MIDI du pont : celles de ``inner`` puis les appareils RTP-MIDI ; même file de messages."""

    def __init__(self, inner, hub, events):
        self.inner, self.hub = inner, hub
        hub.events = events

    def list(self):
        return (list(self.inner.list()) if self.inner else []) + self.hub.list()

    def open(self, index, unit):
        if index >= RTP_BASE:
            return self.hub.open_in(index - RTP_BASE, unit)
        return self.inner.open(index, unit)

    def close_all(self):
        if self.inner:
            self.inner.close_all()
        self.hub.close_ins()


# ─── Essai sur le matériel ────────────────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    import queue
    ap = argparse.ArgumentParser(description="Essai RTP-MIDI des X-Touch : connexion, latence, messages reçus.")
    ap.add_argument("devices", nargs="*", help="ip:port[:nom] (sinon %s à côté du script)" % CONFIG)
    ap.add_argument("--seconds", type=float, default=10.0, help="durée de l'écoute")
    ap.add_argument("--text", action="store_true", help="écrit « RTP OK » sur les écrans, effacé à la fin")
    a = ap.parse_args()
    devices = []
    for i, spec in enumerate(a.devices):
        p = spec.split(":")
        devices.append({"ip": p[0], "port": int(p[1]), "name": p[2] if len(p) > 2 else "X-TOUCH %d" % (i + 1)})
    if not devices:
        devices = load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG))
    if not devices:
        print("Aucun appareil : donner ip:port ou créer %s" % CONFIG)
        return 2
    events = queue.Queue()
    hub = RtpHub(devices)
    out, cin = RtpOut(None, hub), RtpIn(None, hub, events)
    hub.start()
    end, handles = time.time() + a.seconds, {}
    try:
        while time.time() < end:
            for idx, name in out.list():
                if idx not in handles:
                    handles[idx] = out.open(idx)
                    cin.open(idx, idx - RTP_BASE)
                    if a.text:
                        dev = 0x15 if "EXT" in name.upper() else 0x14
                        out.long(handles[idx], bytes((0xF0, 0, 0, 0x66, dev, 0x12, 0)) + b"RTP OK " + b"\xF7")
            try:
                unit, st, d1, d2, _t = events.get(timeout=0.2)
                print("  %s : %02X %02X %02X" % (devices[unit]["name"], st, d1, d2), flush=True)
            except queue.Empty:
                pass
    except KeyboardInterrupt:
        pass
    for st in hub.status():
        print("%-16s %s:%d  %s  latence %s  perdus %d  en retard %d"
              % (st["name"], st["ip"], st["port"], "connectée" if st["up"] else "ABSENTE",
                 "%.1f ms" % st["latency_ms"] if st["latency_ms"] is not None else "?", st["lost"], st["late"]))
    if a.text:
        for idx, h in handles.items():
            dev = 0x15 if "EXT" in dict(out.list()).get(idx, "").upper() else 0x14
            try:
                out.long(h, bytes((0xF0, 0, 0, 0x66, dev, 0x12, 0)) + b"       " + b"\xF7")
            except OSError:
                pass
        time.sleep(0.1)
    ok = all(st["up"] for st in hub.status())
    hub.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
