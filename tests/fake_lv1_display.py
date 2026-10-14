import socket, sys, threading, time
sys.path.insert(0, sys.argv[1])
import lv1_probe as P

srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0)); srv.listen(1)
print("PORT", srv.getsockname()[1], flush=True)

def track(name, g, c, fader):
    return [("s", name), ("i", g), ("i", c), ("d", fader), ("d", 0.0)] + [("i", 0)] * 12 + [("h", 0), ("d", 0.0)]

def layers(page=0, custom=0, spec=(("Ch 1-16", 0, 0), ("Ch 17-32", 0, 16))):
    a = [("i", page), ("i", custom), ("i", len(spec))]
    for name, g, start in spec:
        a += [("s", name), ("i", 16)]
        for k in range(16):
            if g is None or k >= 14:
                a += [("i", -1), ("i", -1)]
            else:
                a += [("i", g), ("i", start + k)]
    return a

def run():
    c, _ = srv.accept()
    c.settimeout(0.2)
    got = []
    def rx():
        buf = b""
        while True:
            try:
                d = c.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not d: return
            buf += d
            pk, buf = P.split_frames(buf)
            got.extend(P.osc_decode(p)[0] for p in pk)
    threading.Thread(target=rx, daemon=True).start()
    time.sleep(0.2)
    send = lambda a, args=(): c.sendall(P.frame(a, args))
    send("/handshake", [("i", 1)])
    chans = [("i", 3)] + track("Channel 1", 0, 0, -144.0) + track("Kick Drûm", 0, 1, -5.0) + track("Voix", 0, 16, 0.0)
    send("/Channels", chans)
    send("/Notify/TrackColor", [("i", 0), ("i", 0), ("i", 13), ("f", 0.0588), ("f", 0.6353), ("f", 0.6706)])
    send("/Notify/TrackColor", [("i", 0), ("i", 1), ("i", 21), ("f", 0.6392), ("f", 0.0), ("f", 0.0)])
    send("/Notify/TrackColor", [("i", 0), ("i", 16), ("i", 24), ("f", 0.9804), ("f", 0.4824), ("f", 0.0784)])
    send("/Notify/Layers", layers())
    send("/Notify/Layers", layers(0, 1, (("Page-1", 0, 4), ("Page-2", None, 0))))
    send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
    send("/Notify/CustomButton", [("i", 0), ("i", 0), ("i", 1)])
    t0 = time.time(); k = 0
    while time.time() - t0 < 2.6:
        lvl = -40 + 35 * ((k % 10) / 10)
        send("/Notify/Meters", [("i", 3), ("i", 0), ("i", 0), ("i", 0), ("f", -100.0),
                                ("i", 0), ("i", 1), ("i", 0), ("f", lvl), ("i", 0), ("i", 16), ("i", 0), ("f", -6.0)])
        if k == 10:
            send("/Notify/Track/Out/Gain", [("i", 0), ("i", 1), ("d", -12.3), ("T", True)])
            send("/Notify/Track/Name", [("i", 0), ("i", 0), ("s", "Bass DI"), ("T", True)])
        if k == 15:
            send("/Notify/CurrentLayer", [("i", 0), ("i", 1)])
        if k == 25:
            send("/Notify/CustomButton", [("i", 0), ("i", 1), ("i", 1)])
            send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
        if k == 35:
            send("/Notify/CustomButton", [("i", 0), ("i", 0), ("i", 1)])
            send("/Notify/Layers", layers(0, 0, (("Groups", 1, 0), ("Masters", 3, 0))))
            send("/Notify/CurrentLayer", [("i", 0), ("i", 0)])
        if k == 45:
            send("/Notify/SpillButton", [("i", 0), ("i", 1), ("i", 1)])
        if k % 20 == 0:
            send("/ping", [("h", 1), ("i", k)])
        k += 1
        time.sleep(0.043)
    time.sleep(0.3)
    print("SERVER GOT", sorted(set(got)), got.count("/pong"), "pong", flush=True)
    c.close()
threading.Thread(target=run).start()
