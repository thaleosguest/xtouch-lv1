"""Test : routage vers le pilote SoundGrid de ce PC, lu dans une base LV1 fabriquée qui reprend le patch de Joseph
(15/10) : canal 0 stéréo A = X32 1-2 (Inputs[0] 0-1), B = LV1-PORT lecture 1-2 (Inputs[1] 0-1) ; X32 1-2 -> LV1-PORT
1-2 (Outputs[1]) ; canal 3 mono B = lecture 6 ; canal 7 A = X32 9, X32 9 envoyée vers un AUTRE pilote (Outputs[2])."""
import os, sqlite3, sys, tempfile
sys.path.insert(0, sys.argv[1])
import lv1_db

d = tempfile.mkdtemp()
path = os.path.join(d, "CurrentLV1.dat")
db = sqlite3.connect(path)
db.executescript("""
create table device (id, device_gender, mac, io_bank, assign);
create table device_daw (id, hostname, is_local);
create table device_name (mac, gender, key, name);
create table routes (id, src_cluster_type, src_cluster_type_index, src_section_type, src_section_index,
  src_channel_index, src_control_id, src_asgn_type, dst_cluster_type, dst_cluster_type_index, dst_section_type,
  dst_section_index, dst_channel_index, dst_control_id, dst_asgn_type, status);
insert into device values (1, 0, 111, 0, 0), (3, 1, 333, 0, 1), (4, 1, 444, 0, 2);
insert into device_daw values (3, 'pc-portable-js', 1), (4, 'autre', 0);
insert into device_name values (333, 1, 'x', 'LV1-PORT'), (444, 1, 'y', 'TracksLive-FL');
""")
R = [(10, 0, 0, 0, 0, 0, 0), (10, 0, 1, 0, 0, 0, 1),          # X32 1-2 -> canal 0 A (L, R)
     (10, 1, 0, 0, 0, 1, 0), (10, 1, 1, 0, 0, 1, 1),          # LV1-PORT lecture 1-2 -> canal 0 B
     (10, 0, 0, 11, 1, 0, 0), (10, 0, 1, 11, 1, 0, 1),        # X32 1-2 -> LV1-PORT 1-2 (enregistrement)
     (10, 1, 5, 0, 3, 1, 1),                                  # LV1-PORT lecture 6 -> canal 3 B
     (10, 0, 8, 0, 7, 0, 1), (10, 0, 8, 11, 2, 0, 4)]         # X32 9 -> canal 7 A, envoyée vers un autre pilote
for k, (sc, si, sch, dc, di, ds, dch) in enumerate(R):
    db.execute("insert into routes values (?, ?, ?, -1, -1, ?, -1, -1, ?, ?, 0, ?, ?, -1, 0, 1)",
               (k, sc, si, sch, dc, di, ds, dch))
db.commit(); db.close()

name, rt = lv1_db.routing(path)
print(name, rt)
ok = name == "LV1-PORT" and rt == {0: {"rec": [0, 1], "play": [0, 1]}, 3: {"rec": [], "play": [5]}}
print("OK" if ok else "ÉCHEC")
sys.exit(0 if ok else 1)
