#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSC minimal (Python standard) et trames TCP de l'API réseau de la LV1.

Trame TCP de la LV1 = [taille 4 octets BE][en-tête 8 octets 00 00 00 02 00 00 00 00][paquet OSC]
(protocole repris du module Companion « companion-module-waves-lv1 », MIT, non affilié à Waves).
osc_encode / osc_decode servent aussi tels quels en UDP (REAPER).

Sorti de lv1_probe.py (étape 5 du refactor) ; lv1_probe les réexporte.
"""
import struct

TX_HEADER = bytes([0, 0, 0, 2, 0, 0, 0, 0])
HEADER_LEN = 8


def _pad4(n):
    return (4 - n % 4) % 4


def _osc_str(s):
    b = s.encode("utf-8") + b"\0"
    return b + b"\0" * _pad4(len(b))


def osc_encode(address, args=()):
    """args = liste de (type, valeur), types i f h d s b T F N I."""
    tags = ","
    data = b""
    for t, v in args:
        tags += t
        if t == "i":
            data += struct.pack(">i", int(v))
        elif t == "f":
            data += struct.pack(">f", float(v))
        elif t == "h":
            data += struct.pack(">q", int(v))
        elif t == "d":
            data += struct.pack(">d", float(v))
        elif t == "s":
            data += _osc_str(str(v))
        elif t == "b":
            data += struct.pack(">i", len(v)) + v + b"\0" * _pad4(len(v))
        elif t in "TFNI":
            pass
        else:
            raise ValueError("type OSC inconnu : " + t)
    return _osc_str(address) + _osc_str(tags) + data


def _read_str(buf, off):
    end = buf.index(b"\0", off)
    s = buf[off:end].decode("utf-8", "replace")
    n = end - off + 1
    return s, off + n + _pad4(n)


def osc_decode(buf):
    """Retourne (adresse, [(type, valeur), ...]). S'arrête sur un type inconnu."""
    address, off = _read_str(buf, 0)
    if off >= len(buf):
        return address, []
    tag, off = _read_str(buf, off)
    if not tag.startswith(","):
        return address, []
    args = []
    for t in tag[1:]:
        if t == "i":
            args.append(("i", struct.unpack_from(">i", buf, off)[0])); off += 4
        elif t == "f":
            args.append(("f", struct.unpack_from(">f", buf, off)[0])); off += 4
        elif t == "h":
            args.append(("h", struct.unpack_from(">q", buf, off)[0])); off += 8
        elif t == "d":
            args.append(("d", struct.unpack_from(">d", buf, off)[0])); off += 8
        elif t == "s":
            s, off = _read_str(buf, off); args.append(("s", s))
        elif t == "b":
            n = struct.unpack_from(">i", buf, off)[0]; off += 4
            args.append(("b", bytes(buf[off:off + n]))); off += n + _pad4(n)
        elif t == "T":
            args.append(("T", True))
        elif t == "F":
            args.append(("F", False))
        elif t == "N":
            args.append(("N", None))
        elif t == "I":
            args.append(("I", float("inf")))
        else:
            args.append(("?", t))  # taille inconnue : on ne peut pas continuer
            break
    return address, args


def frame(address, args=()):
    p = osc_encode(address, args)
    return struct.pack(">I", len(p)) + TX_HEADER + p


def split_frames(buf):
    """Découpe un tampon reçu en paquets OSC. Retourne (paquets, reste)."""
    packets = []
    while len(buf) >= 4 + HEADER_LEN:
        size = struct.unpack_from(">I", buf, 0)[0]
        if size == 0 or size > 16 * 1024 * 1024:
            buf = buf[1:]  # resynchronisation
            continue
        total = 4 + HEADER_LEN + size
        if len(buf) < total:
            break
        packets.append(bytes(buf[4 + HEADER_LEN:total]))
        buf = buf[total:]
    return packets, buf
