"""Génère le logo de XTouch-LV1 (demande de Joseph du 16/10/2026 : le MÊME logo que X/M32 Gain Recall, autre couleur)
à partir d'UNE définition géométrique, sans aucune dépendance (rastérisation et PNG/ICO écrits à la main). Repris de
x32-gain-recall-workspace/tools/make_icon.py ; seule la couleur du bloc de droite change (ACCENT) :

  assets/logo.svg   logo vectoriel (README, réutilisation)
  assets/icon.ico   icône de l'exe (PyInstaller --icon), 16 à 256 px
  (les deux servent aussi à l'installeur LV1 Suite, build.py)

Relancer après toute retouche du logo :  py tools/make_icon.py
Repère : carré de 120 x 120. En dessous de SMALL px, version simplifiée (deux blocs + lien), les
détails (potard, vumètre) n'étant plus lisibles.
"""
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BG = "#2B2E33"      # anthracite (fond du float)
X32 = "#454A52"     # bloc X/M32
LV1 = "#38C9FF"     # bloc de droite : bleu LV1 (Gain Recall : ambre #F2B63B)
LITE = "#E9EDF0"    # lien + potard
SMALL = 24          # en dessous : version simplifiée

# (type, couleur, paramètres) dans l'ordre de peinture.
FULL = [
    ("rrect", BG, (0, 0, 120, 120, 26)),
    ("rrect", X32, (14, 40, 50, 80, 8)),
    ("rrect", LV1, (70, 40, 106, 80, 8)),
    ("rect", LITE, (50, 57, 70, 63)),
    ("ring", LITE, (32, 60, 4.5, 4.5)),       # potard : disque plein de rayon 9
    ("seg", X32, (32, 60, 35.5, 53.9, 1.6)),  # index incliné (pas vertical : sinon symbole marche/arrêt)
    ("rrect", BG, (80, 50, 85, 70, 2)),       # vumètre
    ("rrect", BG, (88, 56, 93, 70, 2)),
    ("rrect", BG, (96, 46, 101, 70, 2)),
]
SIMPLE = [
    ("rrect", BG, (0, 0, 120, 120, 26)),
    ("rrect", X32, (8, 34, 50, 86, 10)),
    ("rrect", LV1, (70, 34, 112, 86, 10)),
    ("rect", LITE, (50, 53, 70, 67)),
]


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _inside(kind, p, x, y):
    if kind == "rect":
        x0, y0, x1, y1 = p
        return x0 <= x <= x1 and y0 <= y <= y1
    if kind == "rrect":
        x0, y0, x1, y1, r = p
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        cx = min(max(x, x0 + r), x1 - r)
        cy = min(max(y, y0 + r), y1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    if kind == "ring":
        cx, cy, r, w = p
        d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        return r - w <= d <= r + w
    if kind == "seg":
        x0, y0, x1, y1, w = p
        dx, dy = x1 - x0, y1 - y0
        t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)))
        return (x - x0 - t * dx) ** 2 + (y - y0 - t * dy) ** 2 <= w * w
    raise ValueError(kind)


def render(size, ss=4):
    """Pixels RGBA (bytes, ligne par ligne) du logo à `size` px, suréchantillonné ss x ss."""
    shapes = [(k, _rgb(c), p) for k, c, p in (FULL if size >= SMALL else SIMPLE)]
    scale = 120.0 / size
    out = bytearray()
    for py_ in range(size):
        for px in range(size):
            r = g = b = a = 0
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) * scale
                    y = (py_ + (sy + 0.5) / ss) * scale
                    col = None
                    for kind, c, p in shapes:
                        if _inside(kind, p, x, y):
                            col = c
                    if col:
                        r += col[0]; g += col[1]; b += col[2]; a += 255
            n = ss * ss
            cov = a // n
            if cov:
                k = a // 255   # sous-échantillons couverts
                out += bytes((r // k, g // k, b // k, cov))
            else:
                out += b"\0\0\0\0"
    return bytes(out)


def png(size):
    raw = render(size)
    rows = b"".join(b"\0" + raw[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def ico(sizes):
    """ICO à entrées PNG (lu par Windows depuis Vista, et par PyInstaller)."""
    imgs = [png(s) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(imgs))
    off = 6 + 16 * len(imgs)
    dirs = b""
    for s, data in zip(sizes, imgs):
        dirs += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), off)
        off += len(data)
    return head + dirs + b"".join(imgs)


def svg(shapes=FULL):
    parts = []
    for kind, c, p in shapes:
        if kind == "rect":
            x0, y0, x1, y1 = p
            parts.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="{c}"/>')
        elif kind == "rrect":
            x0, y0, x1, y1, r = p
            parts.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="{r}" fill="{c}"/>')
        elif kind == "ring":
            cx, cy, r, w = p
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{c}" stroke-width="{2 * w}"/>')
        elif kind == "seg":
            x0, y0, x1, y1, w = p
            parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="{c}" '
                         f'stroke-width="{2 * w}" stroke-linecap="round"/>')
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">' + "".join(parts) + "</svg>"


def main():
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    with open(os.path.join(ROOT, "assets", "logo.svg"), "w", encoding="utf-8", newline="\n") as f:
        f.write(svg() + "\n")
    with open(os.path.join(ROOT, "assets", "icon.ico"), "wb") as f:
        f.write(ico([16, 20, 24, 32, 48, 64, 128, 256]))
    print("assets/logo.svg, assets/icon.ico écrits")


if __name__ == "__main__":
    main()
