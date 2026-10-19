#!/usr/bin/env python3
"""Décode une capture réseau (pcapng ou pcap) du trafic LV1 <-> client (MyFOH, MyMon…) en messages OSC.

But : trouver les commandes que MyFOH envoie à la LV1 (changement de couche, sélection de canal…).

    py lv1_capture.py capture.pcapng [--port 56397] [--tout]

Sortie : un message par ligne, horodaté, avec le sens (client -> LV1 ou LV1 -> client). Par défaut,
les messages bavards (/Notify/Meters, /ping, /pong…) sont masqués ; --tout les montre.
Les messages envoyés PAR le client (les /Set…) sont résumés à la fin.

Capture avec l'outil intégré à Windows (PowerShell en administrateur), voir LISEZMOI.md :
    pktmon filter remove ; pktmon filter add -p <port LV1>
    pktmon start --capture --comp nics --pkt-size 0 -f myfoh.etl
    ... gestes dans MyFOH ...
    pktmon stop ; pktmon etl2pcap myfoh.etl -o myfoh.pcapng

Bibliothèque standard uniquement.
"""
import argparse
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lv1_probe as L
import osc

NOISY = {"/Notify/Meters", "/ping", "/pong", "/Notify/NetworkCongestion", "/Notify/TempoBlink"}


# ─── Lecture pcap / pcapng ────────────────────────────────────────────────────

def read_packets(path):
    """Renvoie [(instant en s, type de lien, octets)] pour pcap classique ou pcapng."""
    data = open(path, "rb").read()
    if data[:4] in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
        return _read_pcap(data)
    if data[:4] == b"\x0a\x0d\x0d\x0a":
        return _read_pcapng(data)
    raise ValueError("format inconnu (ni pcap ni pcapng)")


def _read_pcap(data):
    magic = data[:4]
    e = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    nano = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
    link = struct.unpack(e + "I", data[20:24])[0]
    out, i = [], 24
    while i + 16 <= len(data):
        sec, frac, incl, _ = struct.unpack(e + "IIII", data[i:i + 16])
        i += 16
        out.append((sec + frac / (1e9 if nano else 1e6), link, data[i:i + incl]))
        i += incl
    return out


def _read_pcapng(data):
    out, links, i, e = [], [], 0, "<"
    while i + 12 <= len(data):
        btype = struct.unpack(e + "I", data[i:i + 4])[0]
        if btype == 0x0A0D0D0A:   # Section Header : l'ordre des octets est donné par le magic
            e = "<" if data[i + 8:i + 12] == b"\x4d\x3c\x2b\x1a" else ">"
            links = []
        blen = struct.unpack(e + "I", data[i + 4:i + 8])[0]
        if blen < 12 or i + blen > len(data):
            break
        body = data[i + 8:i + blen - 4]
        if btype == 1:            # Interface Description
            links.append((struct.unpack(e + "H", body[:2])[0], 1e-6))
            res = _if_tsresol(body[8:], e)
            if res:
                links[-1] = (links[-1][0], res)
        elif btype == 6:          # Enhanced Packet
            ifid, hi, lo, cap = struct.unpack(e + "IIII", body[:16])
            link, res = links[ifid] if ifid < len(links) else (1, 1e-6)
            out.append((((hi << 32) | lo) * res, link, body[20:20 + cap]))
        elif btype == 3:          # Simple Packet
            link, _ = links[0] if links else (1, 1e-6)
            out.append((0.0, link, body[4:]))
        i += blen
    return out


def _if_tsresol(opts, e):
    i = 0
    while i + 4 <= len(opts):
        code, ln = struct.unpack(e + "HH", opts[i:i + 4])
        if code == 0:
            break
        if code == 9 and ln >= 1:
            v = opts[i + 4]
            return 2.0 ** -(v & 0x7F) if v & 0x80 else 10.0 ** -v
        i += 4 + ((ln + 3) & ~3)
    return None


# ─── Ethernet / IPv4 / IPv6 / TCP ─────────────────────────────────────────────

def tcp_segments(packets):
    """[(instant, ip src, port src, ip dst, port dst, seq, données)] des segments TCP non vides."""
    out = []
    for t, link, p in packets:
        if link == 1:             # Ethernet
            off, etype = 14, struct.unpack(">H", p[12:14])[0] if len(p) >= 14 else 0
            while etype in (0x8100, 0x88A8) and len(p) >= off + 4:   # VLAN
                etype = struct.unpack(">H", p[off + 2:off + 4])[0]
                off += 4
            if etype not in (0x0800, 0x86DD):
                # Carte Wi-Fi : pktmon écrit des trames 802.11 (en-tête 24-34 o + LLC/SNAP) tout en
                # annonçant de l'Ethernet (vu le 14/10/2026). On cherche l'en-tête SNAP.
                k = p.find(b"\xaa\xaa\x03\x00\x00\x00", 24, 48)
                if k < 0:
                    continue
                off, etype = k + 8, struct.unpack(">H", p[k + 6:k + 8])[0]
        elif link in (101, 228, 229):   # IP brut
            off, etype = 0, 0x0800 if p[:1] and p[0] >> 4 == 4 else 0x86DD
        elif link == 0:           # loopback BSD
            off, etype = 4, 0x0800 if len(p) > 4 and p[4] >> 4 == 4 else 0x86DD
        else:
            continue
        if etype == 0x0800 and len(p) >= off + 20:
            ihl = (p[off] & 0x0F) * 4
            if p[off + 9] != 6:
                continue
            total = struct.unpack(">H", p[off + 2:off + 4])[0]
            src, dst = ".".join(map(str, p[off + 12:off + 16])), ".".join(map(str, p[off + 16:off + 20]))
            seg = p[off + ihl:off + max(total, ihl)] if total else p[off + ihl:]
        elif etype == 0x86DD and len(p) >= off + 40:
            if p[off + 6] != 6:
                continue
            plen = struct.unpack(">H", p[off + 4:off + 6])[0]
            src, dst = p[off + 8:off + 24].hex(), p[off + 24:off + 40].hex()
            seg = p[off + 40:off + 40 + plen]
        else:
            continue
        if len(seg) < 20:
            continue
        sport, dport, seq = struct.unpack(">HHI", seg[:8])
        doff = (seg[12] >> 4) * 4
        payload = seg[doff:]
        if payload:
            out.append((t, src, sport, dst, dport, seq, payload))
    return out


def streams(segments):
    """Réassemble chaque sens de chaque connexion (doublons et retransmissions ignorés)."""
    flows = {}
    for t, src, sp, dst, dp, seq, data in segments:
        flows.setdefault((src, sp, dst, dp), []).append((t, seq, data))
    out = {}
    for key, segs in flows.items():
        segs.sort(key=lambda x: x[0])
        nxt, chunks = None, []
        for t, seq, data in segs:
            if nxt is None:
                nxt = seq
            d = (seq - nxt) & 0xFFFFFFFF
            if d >= 0x80000000:                 # recouvrement / retransmission
                skip = (nxt - seq) & 0xFFFFFFFF
                if skip >= len(data):
                    continue
                data, seq = data[skip:], nxt
            elif d > 0:                         # trou (paquet perdu par la capture) : on recolle
                chunks.append((t, None))
            chunks.append((t, data))
            nxt = (seq + len(data)) & 0xFFFFFFFF
        out[key] = chunks
    return out


def decode_stream(chunks):
    """[(instant, adresse OSC, args)] d'un sens réassemblé (trame LV1 : taille + en-tête 8 o + OSC)."""
    out, buf, t_buf = [], b"", 0.0
    for t, data in chunks:
        if data is None:
            buf = b""                            # trou : on abandonne la trame en cours
            continue
        if not buf:
            t_buf = t
        buf += data
        pk, buf = osc.split_frames(buf)
        for p in pk:
            try:
                addr, args = osc.osc_decode(p)
            except Exception:                    # trame illisible : on la signale sans s'arrêter
                addr, args = "<illisible %d octets>" % len(p), []
            out.append((t_buf if buf else t, addr, args))
        if not buf:
            t_buf = t
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Décode une capture du trafic LV1 (MyFOH…) en messages OSC.")
    ap.add_argument("capture", help="fichier .pcapng ou .pcap")
    ap.add_argument("--port", type=int, help="port TCP de la LV1 (sinon : deviné, le plus fréquent)")
    ap.add_argument("--tout", action="store_true", help="montrer aussi /Notify/Meters, /ping, /pong…")
    a = ap.parse_args(argv)

    segs = tcp_segments(read_packets(a.capture))
    if not segs:
        print("Aucun segment TCP avec données dans la capture.")
        return 1
    port = a.port
    if port is None:
        c = Counter()
        for s in segs:
            c[s[2]] += 1
            c[s[4]] += 1
        port = c.most_common(1)[0][0]
        print("Port LV1 deviné : %d (sinon --port)" % port)
    flows = streams([s for s in segs if port in (s[2], s[4])])
    msgs = []
    for (src, sp, dst, dp), chunks in flows.items():
        to_lv1 = dp == port
        peer = "%s:%d" % ((src, sp) if to_lv1 else (dst, dp))
        for t, addr, args in decode_stream(chunks):
            msgs.append((t, to_lv1, peer, addr, args))
    msgs.sort(key=lambda m: m[0])
    if not msgs:
        print("Aucun message OSC décodé sur le port %d." % port)
        return 1
    t0 = msgs[0][0]
    hidden = Counter()
    for t, to_lv1, peer, addr, args in msgs:
        if addr in NOISY and not a.tout:
            hidden[addr] += 1
            continue
        print("%8.3f %s %-21s %s %s" % (t - t0, "->LV1" if to_lv1 else "LV1->", peer, addr,
                                        L.short_args(args, 40)))
    if hidden:
        print("\n(masqués : %s ; --tout pour les voir)" % ", ".join("%s ×%d" % kv for kv in hidden.items()))
    sent = Counter(m[3] for m in msgs if m[1])
    print("\nMessages envoyés par le(s) client(s) à la LV1 :")
    for addr, n in sent.most_common():
        print("  %5d  %s" % (n, addr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
