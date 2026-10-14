#!/usr/bin/env python3
"""Lecture de la base de travail de la LV1 (CurrentLV1.dat) pour ce que le réseau ne donne pas à la connexion.

La LV1 écrit ses réglages en continu dans C:\\Users\\Public\\Waves Audio\\eMotion\\Sessions\\CurrentLV1.dat
(SQLite, mode WAL), cf. x32-gain-recall. On ne l'ouvre JAMAIS directement (SQLite y créerait -shm/-wal et des
verrous) : copie du fichier + -wal dans un dossier temporaire, lecture de la copie.

Pan (vérifié le 14/10/2026, LV1 V17) : snapshot_chainer_params, snapshot -1, param 436 PARAM_OUTPUT_BALANCE,
-45 (gauche) .. +45 (droite) ; absent = centre. Réseau (/Notify/Track/Pan, /Set/Track/Pan) : -1 .. +1.
chainer_id = object.id ; object.obj_type 0 = entrées, obj_index = canal 0-based.

    py lv1_db.py          # affiche les pans des entrées
"""
import os
import shutil
import sqlite3
import sys
import tempfile

DB_PATH = r"C:\Users\Public\Waves Audio\eMotion\Sessions\CurrentLV1.dat"
PARAM_BALANCE = 436
BALANCE_SCALE = 45.0


def copy_db(path=DB_PATH):
    """Copie (fichier + -wal) dans un dossier temporaire ; renvoie le chemin de la copie (à effacer)."""
    d = tempfile.mkdtemp(prefix="lv1db_")
    dst = os.path.join(d, "c.dat")
    shutil.copyfile(path, dst)
    if os.path.exists(path + "-wal"):
        shutil.copyfile(path + "-wal", dst + "-wal")
    return dst


def input_pans(path=DB_PATH):
    """{(0, canal 0-based): pan -1..+1} pour toutes les entrées connues de la base."""
    dst = copy_db(path)
    try:
        db = sqlite3.connect(dst)
        try:
            objs = db.execute("select id, obj_index from object where obj_type = 0").fetchall()
            vals = dict(db.execute("select chainer_id, param_value from snapshot_chainer_params "
                                   "where snapshot_id = -1 and param_id = ?", (PARAM_BALANCE,)).fetchall())
        finally:
            db.close()
    finally:
        shutil.rmtree(os.path.dirname(dst), ignore_errors=True)
    return {(0, idx): max(-1.0, min(1.0, float(vals.get(oid, 0.0)) / BALANCE_SCALE)) for oid, idx in objs}


# Envois aux (vérifié le 15/10/2026 : In 1 -> Fx 1 -10,8 = GAIN_0, -> Mon 1 -21,0 = GAIN_8, In 2 -> Fx 8 = GAIN_7).
# aux = index de /Aux/Tracks (Fx 1-8 = 0..7, Mon 1-16 = 8..23). aux 0..15 : GAIN_n (232+n), ONOFF_n (248+n) ;
# aux 16..23 : GAIN_2_k (595+k), ONOFF_2_k (603+k) — non vérifié (Mon 9-16 jamais réglés pendant l'essai).
# Absent : gain -144, off (chainer_params_default_values, obj_type 0).
def send_params(aux):
    if aux < 16:
        return 232 + aux, 248 + aux
    return 595 + (aux - 16), 603 + (aux - 16)


def input_sends(path=DB_PATH, n_aux=24):
    """{(0, canal 0-based, aux): (gain dB, on)} pour toutes les entrées et les n_aux premiers aux."""
    dst = copy_db(path)
    try:
        db = sqlite3.connect(dst)
        try:
            objs = db.execute("select id, obj_index from object where obj_type = 0").fetchall()
            ids = sorted({p for a in range(n_aux) for p in send_params(a)})
            rows = db.execute("select chainer_id, param_id, param_value from snapshot_chainer_params "
                              "where snapshot_id = -1 and param_id in (%s)" % ",".join(map(str, ids))).fetchall()
        finally:
            db.close()
    finally:
        shutil.rmtree(os.path.dirname(dst), ignore_errors=True)
    vals = {(c, p): v for c, p, v in rows}
    out = {}
    for oid, idx in objs:
        for a in range(n_aux):
            pg, po = send_params(a)
            out[(0, idx, a)] = (float(vals.get((oid, pg), -144.0)), bool(vals.get((oid, po), 0.0)))
    return out


def main():
    pans = input_pans(sys.argv[1] if len(sys.argv) > 1 else DB_PATH)
    for (g, ch), p in sorted(pans.items())[:16]:
        print("  In %2d : pan %+.2f" % (ch + 1, p))
    print("(%d entrées)" % len(pans))
    return 0


if __name__ == "__main__":
    sys.exit(main())
