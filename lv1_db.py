#!/usr/bin/env python3
"""Lecture de la base de travail de la LV1 (CurrentLV1.dat) pour ce que le réseau ne donne pas à la connexion.

La LV1 écrit ses réglages en continu dans C:\\Users\\Public\\Waves Audio\\eMotion\\Sessions\\CurrentLV1.dat
(SQLite, mode WAL), cf. x32-gain-recall. On ne l'ouvre JAMAIS directement (SQLite y créerait -shm/-wal et des
verrous) : copie du fichier + -wal dans un dossier temporaire, lecture de la copie.

Pan (vérifié le 14/10/2026, LV1 V17) : snapshot_chainer_params, snapshot -1, param 436 PARAM_OUTPUT_BALANCE,
-45 (gauche) .. +45 (droite) ; absent = centre. Réseau (/Notify/Track/Pan, /Set/Track/Pan) : -45 .. +45 aussi.
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


# Entrée A/B sélectionnée (établi par x32-gain-recall) : param 0 du canal, snapshot -1 ; 1.0 = B, absent = A.
PARAM_INPUT_SELECT = 0


def input_ab(path=DB_PATH):
    """{(0, canal 0-based): True si l'entrée B est sélectionnée} pour toutes les entrées."""
    dst = copy_db(path)
    try:
        db = sqlite3.connect(dst)
        try:
            objs = db.execute("select id, obj_index from object where obj_type = 0").fetchall()
            vals = dict(db.execute("select chainer_id, param_value from snapshot_chainer_params "
                                   "where snapshot_id = -1 and param_id = ?", (PARAM_INPUT_SELECT,)).fetchall())
        finally:
            db.close()
    finally:
        shutil.rmtree(os.path.dirname(dst), ignore_errors=True)
    return {(0, idx): float(vals.get(oid, 0.0)) >= 0.5 for oid, idx in objs}


# Mode de couche (boutons Input / Mix / Factory / Custom / Spill de la colonne de droite, voyants des touches View de
# la X-Touch, demande de Joseph du 16/10/2026) : surface_property_int, surface 2 = Mixer 1 / 3 = Mixer 2, propriété 12
# (eProp_LayersMode) = ovv_track_mapping_type (écrit aussitôt par la LV1, cf. x32-gain-recall lv1/layers.py) ;
# config_info track_type 0 = nombre de canaux d'entrée configuré (16 / 32 / 64 / 80).
MODE_FACTORY, MODE_CUSTOM, MODE_SPILL, MODE_INPUTS, MODE_BUSSES = 0, 1, 3, 4, 5
PROP_LAYERS_MODE = 12


def layer_mode(mixer=1, path=DB_PATH):
    """(mode de couche, nombre de canaux d'entrée) du Mixer 1 ou 2 ; None pour ce qui manque."""
    dst = copy_db(path)
    try:
        db = sqlite3.connect(dst)
        try:
            row = db.execute("select value from surface_property_int where surface = ? and property = ?",
                             (1 + mixer, PROP_LAYERS_MODE)).fetchone()
            n = db.execute("select num_tracks from config_info where track_type = 0").fetchone()
        finally:
            db.close()
    finally:
        shutil.rmtree(os.path.dirname(dst), ignore_errors=True)
    return (row[0] if row else None), (n[0] if n else None)


def db_stamp(path=DB_PATH):
    """Repère de changement de la base (dates et tailles du fichier et du -wal) : relire seulement s'il change."""
    out = []
    for p in (path, path + "-wal"):
        try:
            st = os.stat(p)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


# Routage (relevé le 15/10/2026 sur la session de Joseph) : table `routes`, une ligne par liaison du patch.
#   source  (src_cluster_type, src_cluster_type_index, src_channel_index)
#   dest.   (dst_cluster_type, dst_cluster_type_index, dst_section_index, dst_channel_index)
# Clusters : 0 = canal d'entrée (index = canal 0-based ; section 0 = entrée A, 1 = entrée B ; channel = L/R),
# 10 = Inputs = entrées d'un appareil, 11 = Outputs = sorties d'un appareil (index = « assign », la place de
# l'appareil dans l'inventaire : table device ; channel = n° de canal de l'appareil, 0-based).
# Pilote SoundGrid de CE PC : device_daw.is_local = 1 -> device.id -> device.assign (ex. LV1-PORT, assign 1).
# Ex. Joseph : Inputs[0] 0-1 (X32) -> canal 0 A ; Inputs[1] 0-1 (LV1-PORT) -> canal 0 B ; Inputs[0] 0-1 -> Outputs[1] 0-1.
CL_CHANNEL, CL_INPUTS, CL_OUTPUTS = 0, 10, 11


def devices(path=DB_PATH):
    """Appareils de l'inventaire : [(nom, genre « DAW » / « IOBox » / …, assign, local)]."""
    dst = copy_db(path)
    try:
        db = sqlite3.connect(dst)
        try:
            rows = db.execute("select d.assign, d.mac, d.device_gender, g.name, "
                              "(select is_local from device_daw w where w.id = d.id) from device d "
                              "left join device_gender g on g.id = d.device_gender").fetchall()
            names = {(m, gd): n for m, gd, n in db.execute("select mac, gender, name from device_name")}
        finally:
            db.close()
    finally:
        shutil.rmtree(os.path.dirname(dst), ignore_errors=True)
    return [(names.get((mac, gender)) or "?", gname, assign, bool(loc)) for assign, mac, gender, gname, loc in rows]


def driver_size(path=DB_PATH, driver=None):
    """Nombre de canaux de lecture (vers la LV1) du pilote : device.in_channel_count (LV1-PORT : 128 le 16/10)."""
    for name, _g, assign, local in devices(path):
        if (driver and name.lower() == driver.lower()) or (not driver and local):
            dst = copy_db(path)
            try:
                db = sqlite3.connect(dst)
                try:
                    row = db.execute("select in_channel_count from device where assign = ? and device_gender = 1",
                                     (assign,)).fetchone()
                finally:
                    db.close()
            finally:
                shutil.rmtree(os.path.dirname(dst), ignore_errors=True)
            return row[0] if row and row[0] and row[0] > 0 else None
    return None


def routing(path=DB_PATH, driver=None):
    """Pour le pilote SoundGrid de ce PC : {canal 0-based: {"rec": [n° de canal du pilote, 0-based, L puis R],
    "play": [...]}}. rec = canaux du pilote qui reçoivent la source de l'entrée A du canal (à ENREGISTRER) ;
    play = canaux de lecture du pilote branchés sur l'entrée B (virtual soundcheck). Rend aussi le nom du pilote.
    driver : nom du pilote SoundGrid à utiliser (ex. « TracksLive-FL » : Reaper sur un AUTRE PC, remarque de Joseph
    du 15/10) ; par défaut, celui du PC où tourne la LV1 (device_daw.is_local)."""
    dst = copy_db(path)
    try:
        db = sqlite3.connect(dst)
        try:
            if driver:
                local = db.execute("select d.assign, d.mac from device d join device_name n on n.mac = d.mac "
                                   "and n.gender = d.device_gender where lower(n.name) = lower(?)", (driver,)).fetchone()
            else:
                local = db.execute("select d.assign, d.mac from device d join device_daw w on w.id = d.id "
                                   "where w.is_local = 1").fetchone()
            if not local:
                return None, {}
            assign, mac = local
            name = db.execute("select name from device_name where mac = ? and gender = 1", (mac,)).fetchone()
            rows = db.execute("select src_cluster_type, src_cluster_type_index, src_channel_index, dst_cluster_type, "
                              "dst_cluster_type_index, dst_section_index, dst_channel_index from routes").fetchall()
        finally:
            db.close()
    finally:
        shutil.rmtree(os.path.dirname(dst), ignore_errors=True)
    to_driver = {}                   # source (cluster, index, canal) -> canaux du pilote qui la reçoivent
    for sc, si, sch, dc, di, _ds, dch in rows:
        if dc == CL_OUTPUTS and di == assign:
            to_driver.setdefault((sc, si, sch), []).append(dch)
    out = {}
    for sc, si, sch, dc, di, ds, dch in sorted(rows, key=lambda r: (r[4], r[5], r[6])):
        if dc != CL_CHANNEL:
            continue
        e = out.setdefault(di, {"rec": [], "play": []})
        if ds == 0:                  # entrée A : sa source part-elle vers le pilote ?
            e["rec"] += sorted(to_driver.get((sc, si, sch), []))[:1]
        elif ds == 1 and sc == CL_INPUTS and si == assign:
            e["play"].append(sch)    # entrée B = lecture du pilote
    for (sc, si, sch), chans in to_driver.items():       # sortie directe d'un canal vers le pilote
        if sc == CL_CHANNEL:
            out.setdefault(si, {"rec": [], "play": []})["rec"] += sorted(chans)[:1]
    return (name[0] if name else None), {k: v for k, v in out.items() if v["rec"] or v["play"]}


def main():
    pans = input_pans(sys.argv[1] if len(sys.argv) > 1 else DB_PATH)
    for (g, ch), p in sorted(pans.items())[:16]:
        print("  In %2d : pan %+.2f" % (ch + 1, p))
    print("(%d entrées)" % len(pans))
    return 0


if __name__ == "__main__":
    sys.exit(main())
