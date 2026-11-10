"""Messages courts sur toute la largeur des écrans X-Touch + Extender (Joseph, 10/11/2026) : couche, mode des
encodeurs, sends on fader, mode USER, SHIFT tenu. Chaque écran de tranche a 7 caractères : le message est découpé en
cases de 7 (mots regroupés, mot trop long coupé), centré sur la surface ; le reste de la ligne est vidé pendant le
message. Textes en anglais (règle de Joseph pour tout ce qui s'affiche)."""
CELL = 7


def pack_words(text):
    """« SENDS TO Mon 16 » -> ["SENDS", "TO", "Mon 16"] : mots regroupés en cases de 7 caractères au plus."""
    cells, cur = [], ""
    for w in (text or "").split():
        while len(w) > CELL:                       # mot trop long : coupé
            if cur:
                cells.append(cur)
                cur = ""
            cells.append(w[:CELL])
            w = w[CELL:]
        if not w:
            continue
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= CELL:
            cur += " " + w
        else:
            cells.append(cur)
            cur = w
    if cur:
        cells.append(cur)
    return cells


def compact(text):
    """« Ch 65-80 » (8 car.) -> « Ch65-80 » s'il tient alors dans une case ; sinon inchangé (découpé par mots)."""
    t = (text or "").strip()
    return t.replace(" ", "") if len(t) > CELL and len(t.replace(" ", "")) <= CELL else t


def banner_cells(*parts):
    """Cases du message : chaque partie commence une nouvelle case, centrée dans ses 7 caractères."""
    out = []
    for p in parts:
        out += pack_words(p)
    return [c.center(CELL).rstrip() for c in out]


def apply_banner(row, cells):
    """Ligne d'écrans (une case par tranche) -> même ligne avec le message centré, le reste vidé."""
    n = len(row)
    cells = list(cells)[:n]
    start = (n - len(cells)) // 2
    out = [""] * n
    for i, c in enumerate(cells):
        out[start + i] = c
    return out


def mode_message(name):
    """Mode des encodeurs (GainControl.mode_name)."""
    return {"pan": banner_cells("ENCODER", "PAN"),
            "gain": banner_cells("ENCODER", "GAIN"),
            "trim": banner_cells("ENCODER", "TRIM", "PUSH =", "PHASE")}.get(name)


def shift_message(on_b):
    """SHIFT tenu : rappel de SHIFT + FLIP et état A/B des entrées (remplace la LED FLIP, pas comprise, 10/11)."""
    ab = "?" if on_b is None else ("B" if on_b else "A")
    return banner_cells("SHIFT +", "FLIP =", "FLIP A/B", "INPUTS", "ON " + ab)
