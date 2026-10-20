"""Test : désinstallation de X32 Gain Recall -> son « lancer avec Windows » est retiré (20/10/2026, bundle Gain Recall 3.1).
- clé Run sous le VRAI nom « XM32 Gain Recall LV1 » (l'installeur cherchait « X32 Gain Recall » : jamais retirée) ;
- tâche planifiée 3.1 « XM32 Gain Recall LV1 » : suppression simple, sinon UNE demande UAC, puis vérification ;
- UAC refusée -> « PAS retirée » + consigne ; tâche ou clé d'une AUTRE copie -> rien ; tâche illisible -> consigne.
Registre et schtasks remplacés par des faux (le vrai démarrage de Joseph n'est jamais touché).

    py tests/test_desinstall_gr.py .
"""
import os
import sys
sys.path.insert(0, sys.argv[1])
import installer as I

ok, why = True, []
def check(name, cond):
    global ok
    if not cond: why.append(name)
    ok = ok and cond


TARGET = r"C:\Users\Test\AppData\Local\Programs\X32 Gain Recall"
EXE = os.path.join(TARGET, "XM32_Gain_Recall_LV1.exe")
OTHER = r"D:\Outils\XM32_Gain_Recall_LV1.exe"


def task_xml(exe):
    return ('<?xml version="1.0" encoding="UTF-16"?>\n<Task><Actions Context="Author"><Exec><Command>%s</Command>'
            '<Arguments>--at-login</Arguments></Exec></Actions></Task>' % exe.replace("&", "&amp;"))


class Fake:
    """Registre (valeurs Run) + Planificateur (une tâche) ; admin_ok : ce que fait la demande UAC."""
    def __init__(self, run=None, task=None, user_delete=False, admin_ok=True, query_denied=False):
        self.run, self.task = dict(run or {}), task
        self.user_delete, self.admin_ok, self.query_denied = user_delete, admin_ok, query_denied
        self.admin_calls, self.log = [], []
        I.run_value = lambda name: self.run.get(name)
        I.drop_run_value = lambda name: self.run.pop(name, None) is not None
        I.schtasks = self.schtasks
        I.schtasks_admin = self.schtasks_admin

    def schtasks(self, *args):
        if args[0] == "/Query":
            if self.query_denied:
                return 1, "ERROR: Access is denied."
            if self.task is None:
                return 1, "ERROR: The system cannot find the file specified."
            return 0, task_xml(self.task) if "/XML" in args else "XM32 Gain Recall LV1  Ready"
        if args[0] == "/Delete":
            if self.task is None:
                return 1, "ERROR: The system cannot find the file specified."
            if not self.user_delete:
                return 1, "ERROR: Access is denied."
            self.task = None
            return 0, "SUCCESS"
        return 1, "?"

    def schtasks_admin(self, *args):
        self.admin_calls.append(args)
        if not self.admin_ok:
            return None                                    # UAC refusée
        self.task = None
        return 0

    def go(self):
        I.gainrecall_autostart(TARGET, self.log.append)
        return " | ".join(self.log)


check("lecture de la tâche : exe avec & et guillemets",
      I.task_exe(task_xml('"C:\\A & B\\x.exe"')) == "C:\\A & B\\x.exe")

f = Fake(run={"XM32 Gain Recall LV1": '"%s" --at-login' % EXE})
out = f.go()
check("clé Run 3.0.1 (vrai nom) retirée", "XM32 Gain Recall LV1" not in f.run and "removed from Windows startup" in out)
check("pas de tâche : pas d'UAC", f.admin_calls == [])

f = Fake(run={"XM32 Gain Recall LV1": '"%s" --at-login' % OTHER})
f.go()
check("clé Run d'une autre copie : gardée", "XM32 Gain Recall LV1" in f.run)

f = Fake(task=EXE)
out = f.go()
check("tâche 3.1 : suppression refusée sans admin -> UNE demande UAC", f.admin_calls == [("/Delete", "/TN", I.GR_TASK, "/F")])
check("tâche 3.1 : retirée et annoncée", f.task is None and "startup task removed" in out)

f = Fake(task=EXE, user_delete=True)
out = f.go()
check("tâche supprimable sans admin : pas d'UAC", f.admin_calls == [] and f.task is None and "startup task removed" in out)

f = Fake(task=EXE, admin_ok=False)
out = f.go()
check("UAC refusée : tâche gardée, « NOT removed » + consigne", f.task == EXE and "NOT removed" in out
      and "Launch with Windows" in out)

f = Fake(task=OTHER)
out = f.go()
check("tâche d'une autre copie : pas touchée, pas d'UAC", f.task == OTHER and f.admin_calls == [] and out == "")

f = Fake(task=EXE, query_denied=True)
out = f.go()
check("tâche illisible : rien supprimé, consigne", f.task == EXE and f.admin_calls == [] and "access denied" in out
      and "Launch with Windows" in out)

f = Fake(run={"XM32 Gain Recall LV1": '"%s" --at-login' % EXE}, task=EXE)
f.go()
check("clé Run ET tâche (mise à jour 3.0.1 -> 3.1) : les deux retirées", not f.run and f.task is None)

print("OK" if ok else "ÉCHEC : " + ", ".join(why))
sys.exit(0 if ok else 1)
