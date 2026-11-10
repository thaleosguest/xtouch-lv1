"""Faux appareil RTP-MIDI (X-Touch / Extender par Ethernet) pour les tests : esclave AppleMIDI, comme ceux de Joseph."""
import select
import socket
import struct
import threading


class FakeDevice(threading.Thread):
    """Appareil RTP-MIDI esclave : contrôle sur ``port``, données sur ``port + 1``."""

    def __init__(self, port, name=b"X-Touch"):
        super().__init__(daemon=True)
        self.port, self.dev_name = port, name
        self.c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.d = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.c.bind(("127.0.0.1", port))
        self.d.bind(("127.0.0.1", port + 1))
        self.ssrc = 0x58540000 + port
        self.powered = True          # False : ne répond plus à rien (éteint)
        self.ctrl_addr = self.data_addr = None
        self.midi = []               # sections MIDI reçues (octets bruts, sans l'en-tête de longueur)
        self.raw = []                # paquets RTP reçus
        self.by = 0
        self.bad_data_port = 0
        self.ck2 = 0
        self.seq = 100
        self.stop = False

    def run(self):
        socks = {self.c: False, self.d: True}
        while not self.stop:
            for sock in select.select(list(socks), [], [], 0.05)[0]:   # sans attente : le pont envoie par rafales
                try:
                    pk, addr = sock.recvfrom(4096)
                except OSError:
                    continue
                if self.powered:
                    self.handle(sock, socks[sock], pk, addr)

    def handle(self, sock, is_data, pk, addr):
        if pk[:2] != b"\xff\xff":
            self.raw.append(pk)
            n = pk[12] & 0x0F
            body = pk[13:]
            if pk[12] & 0x80:
                n, body = (n << 8) | pk[13], pk[14:]
            self.midi.append(body[:n])
            return
        cmd = pk[2:4]
        if cmd == b"IN":
            token = pk[8:12]
            if is_data:
                if self.ctrl_addr is None or addr[1] != self.ctrl_addr[1] + 1:
                    self.bad_data_port += 1          # le piège : pas de réponse
                    return
                self.data_addr = addr
            else:
                self.ctrl_addr = addr
            sock.sendto(b"\xff\xffOK" + struct.pack(">I", 2) + token + struct.pack(">I", self.ssrc)
                        + self.dev_name + b"\0", addr)
        elif cmd == b"CK":
            count = pk[8]
            t = struct.unpack(">QQQ", pk[12:36])
            if count == 0:
                sock.sendto(b"\xff\xffCK" + struct.pack(">IB3xQQQ", self.ssrc, 1, t[0], 5555, 0), addr)
            elif count == 2:
                self.ck2 += 1
        elif cmd == b"BY":
            self.by += 1
            self.ctrl_addr = self.data_addr = None

    def send_midi(self, section, seq=None):
        """Envoie une section de commandes MIDI toute faite (en-tête de longueur compris)."""
        self.seq = seq = (self.seq + 1) & 0xFFFF if seq is None else seq
        self.d.sendto(struct.pack(">BBHII", 0x80, 0x80 | 97, seq, 0, self.ssrc) + section, self.data_addr)

    def bye(self):
        self.c.sendto(b"\xff\xffBY" + struct.pack(">III", 2, 0, self.ssrc), self.ctrl_addr)
