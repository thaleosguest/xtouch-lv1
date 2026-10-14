"""Test de lv1_capture.py sur une fausse capture pcapng (Ethernet / IPv4 / TCP).

    py tests/test_capture.py .

Cas couverts : trame coupée en deux segments, segment en double (pktmon le voit parfois deux fois),
retransmission partielle, les deux sens, messages bavards masqués.
"""
import contextlib, io, os, struct, sys, tempfile
sys.path.insert(0, sys.argv[1])
import lv1_probe as P
import lv1_capture as C

LV1, TAB, PORT = (192, 168, 1, 8), (192, 168, 1, 50), 56397


def eth_ip_tcp(src, dst, sport, dport, seq, payload):
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, 0x18, 65535, 0, 0) + payload
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0, bytes(src), bytes(dst)) + tcp
    return b"\x00" * 12 + b"\x08\x00" + ip


def block(btype, body):
    body += b"\x00" * ((4 - len(body) % 4) % 4)
    n = 12 + len(body)
    return struct.pack("<II", btype, n) + body + struct.pack("<I", n)


def epb(t_us, pkt):
    return block(6, struct.pack("<IIIII", 0, t_us >> 32, t_us & 0xFFFFFFFF, len(pkt), len(pkt)) + pkt)


cmd = P.frame("/Set/CurrentLayer", [("i", 0), ("i", 2)])
sel = P.frame("/Set/Select", [("i", 0), ("i", 4)])
note = P.frame("/Notify/CurrentLayer", [("i", 0), ("i", 2)])
ping = P.frame("/ping", [("h", 5), ("i", 1)])

pk = []
t = 1_000_000
s_tab, s_lv1 = 1000, 5000
pk.append(epb(t, eth_ip_tcp(LV1, TAB, PORT, 50123, s_lv1, ping))); s_lv1 += len(ping)
half = len(cmd) // 2
pk.append(epb(t + 1000, eth_ip_tcp(TAB, LV1, 50123, PORT, s_tab, cmd[:half])))
pk.append(epb(t + 1000, eth_ip_tcp(TAB, LV1, 50123, PORT, s_tab, cmd[:half])))          # doublon
pk.append(epb(t + 2000, eth_ip_tcp(TAB, LV1, 50123, PORT, s_tab + half, cmd[half:]))); s_tab += len(cmd)
pk.append(epb(t + 3000, eth_ip_tcp(LV1, TAB, PORT, 50123, s_lv1, note))); s_lv1 += len(note)
pk.append(epb(t + 4000, eth_ip_tcp(TAB, LV1, 50123, PORT, s_tab - 4, cmd[-4:] + sel)))   # retransmission partielle
shb = block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
idb = block(1, struct.pack("<HHI", 1, 0, 65535))
f = tempfile.NamedTemporaryFile(suffix=".pcapng", delete=False)
f.write(shb + idb + b"".join(pk)); f.close()

out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = C.main([f.name])
os.unlink(f.name)
text = out.getvalue()
print(text)
lines = [l for l in text.splitlines() if "->LV1" in l or "LV1->" in l]
want = [("->LV1", "/Set/CurrentLayer i:0 i:2"), ("LV1->", "/Notify/CurrentLayer i:0 i:2"),
        ("->LV1", "/Set/Select i:0 i:4")]
ok = rc == 0 and len(lines) == 3 and all(d in l and m in l for l, (d, m) in zip(lines, want)) \
    and "/ping ×1" in text and "192.168.1.50:50123" in lines[0]
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
