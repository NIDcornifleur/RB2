#!/usr/bin/env python3
"""
RB2 - Activation automatique du PA de secours du Zero 2 W.

Chaîne de bascule Wi-Fi de RB2 :
  1. Wi-Fi local (WIFI-MAISON) ou PA opérateur RB2-ROS (Pi5, dongle Alfa) : normal.
  2. Les deux tombent  -> ce service lève RB2-ZERO-SECOURS (10.60.0.1) sur le Zero.
  3. Un Wi-Fi du Pi5 revient -> ce service RABAISSE le PA secours et rebranche
     le Zero sur le réseau local.

L'étape 3 manquait : une fois le PA secours actif, l'ancienne version se
contentait de « maintien actif » indéfiniment et laissait
connection.autoconnect=no en permanence sur WIFI-MAISON-2.4G. Le Zero restait
donc sur 10.60.0.1 même après le retour du Wi-Fi du Pi5, et un reboot ne le
rebranchait pas non plus. Corrigé ici : retour contrôlé au réseau local dès
que le Pi5 est de nouveau joignable en Wi-Fi pendant RESTORE_OK_CYCLES
cycles, plus une commande « --restore » pour forcer le retour à la main
(bouton de la page de secours).
"""
import argparse
import subprocess
import time
import sys

PI5 = "10.50.0.1"

PI5_AP_IF = "wlxXXXXXXXXXXXX"
PI5_AP_SSID = "RB2-ROS"
PI5_LOCAL_IF = "wlan0"

ZERO_AP_CON = "RB2-ZERO-OUVERT"
ZERO_LOCAL_CON = "WIFI-MAISON-2.4G"

CHECK_SECONDS = 10
FAILS_BEFORE_TRIGGER = 6   # 6 x 10 s = ~60 s de double perte avant d'activer le secours
RESTORE_OK_CYCLES = 6      # 6 x 10 s = ~60 s de Wi-Fi Pi5 revenu avant de rabaisser le secours

SSH_BASE = [
    "ssh",
    "-i", "/home/rj/.ssh/id_ed25519",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=5",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "UserKnownHostsFile=/home/rj/.ssh/known_hosts",
    f"rj@{PI5}",
]


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def run(cmd, timeout=10):
    try:
        p = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return p.returncode, (p.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return 998, "timeout"
    except Exception as e:
        return 999, str(e)


def ssh_ok(remote_cmd):
    code, out = run(SSH_BASE + [remote_cmd], timeout=8)
    return code == 0, out


def zero_ap_active():
    code, out = run(["nmcli", "-t", "-f", "NAME,DEVICE", "con", "show", "--active"])
    if code != 0:
        return False
    for line in out.splitlines():
        if line.startswith(ZERO_AP_CON + ":"):
            return True
    return False


def pi5_ap_ok():
    cmd = (
        f"iw dev {PI5_AP_IF} info 2>/dev/null | grep -q 'type AP' "
        f"&& iw dev {PI5_AP_IF} info 2>/dev/null | grep -q 'ssid {PI5_AP_SSID}'"
    )
    ok, _ = ssh_ok(cmd)
    return ok


def pi5_local_wifi_ok():
    cmd = (
        f"iw dev {PI5_LOCAL_IF} info 2>/dev/null | grep -q 'type managed' "
        f"&& iw dev {PI5_LOCAL_IF} info 2>/dev/null | grep -q 'ssid '"
    )
    ok, _ = ssh_ok(cmd)
    return ok


def activate_zero_ap():
    log("Activation du PA secours Zero demandee")

    # Pendant le secours, aucun des deux profils ne doit se (re)connecter seul :
    # on évite que NetworkManager fasse osciller le Zero entre local et PA.
    run(["nmcli", "con", "modify", ZERO_AP_CON, "connection.autoconnect", "no"], timeout=10)
    run(["nmcli", "con", "modify", ZERO_LOCAL_CON, "connection.autoconnect", "no"], timeout=10)

    # Ferme le Wi-Fi local du Zero s'il etait actif.
    run(["nmcli", "con", "down", ZERO_LOCAL_CON], timeout=10)

    # Active le PA secours.
    code, out = run(["nmcli", "con", "up", ZERO_AP_CON], timeout=25)

    if code == 0:
        log("RB2-ZERO-SECOURS actif")
        return True

    log(f"ERREUR activation RB2-ZERO-SECOURS : code={code} sortie={out}")
    return False


def restore_local():
    """Rabaisse le PA secours et rebranche le Zero sur le réseau local."""
    log("Retour au Wi-Fi local du Zero demande")

    # Le réseau local a de nouveau le droit de se reconnecter tout seul.
    run(["nmcli", "con", "modify", ZERO_LOCAL_CON, "connection.autoconnect", "yes"], timeout=10)
    # Le PA secours, lui, ne doit se relever que sur décision de ce service.
    run(["nmcli", "con", "modify", ZERO_AP_CON, "connection.autoconnect", "no"], timeout=10)

    # Coupe le PA secours.
    run(["nmcli", "con", "down", ZERO_AP_CON], timeout=15)
    time.sleep(1)

    # Rebranche le Wi-Fi local.
    code, out = run(["nmcli", "con", "up", ZERO_LOCAL_CON], timeout=30)
    if code != 0:
        # Deuxième tentative : laisser NetworkManager choisir le profil.
        log(f"con up {ZERO_LOCAL_CON} code={code} ({out}); tentative via 'nmcli dev connect wlan0'")
        code, out = run(["nmcli", "dev", "connect", PI5_LOCAL_IF], timeout=30)

    if code == 0:
        log(f"{ZERO_LOCAL_CON} reconnecte")
        return True

    log(f"ERREUR reconnexion Wi-Fi local Zero : code={code} sortie={out}")
    return False


def status_once():
    ap_active = zero_ap_active()
    ap_ok = pi5_ap_ok()
    local_ok = pi5_local_wifi_ok()

    print("=== Etat secours Zero ===")
    print(f"Zero PA actif       : {ap_active}")
    print(f"Pi5 RB2-ROS actif   : {ap_ok}")
    print(f"Pi5 Wi-Fi local OK  : {local_ok}")
    print(f"Activation si       : Pi5 RB2-ROS=False ET Pi5 Wi-Fi local=False")
    print(f"Retour local si     : PA actif ET (RB2-ROS=True OU Wi-Fi local=True)")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="Affiche l'etat sans rien changer")
    parser.add_argument("--force", action="store_true", help="Force l'activation du PA secours")
    parser.add_argument("--restore", action="store_true", help="Force le retour au Wi-Fi local")
    args = parser.parse_args()

    if args.status:
        return status_once()

    if args.force:
        return 0 if activate_zero_ap() else 1

    if args.restore:
        return 0 if restore_local() else 1

    log("RB2 Zero secours auto actif")
    log(
        f"Surveillance toutes les {CHECK_SECONDS}s; "
        f"activation apres {FAILS_BEFORE_TRIGGER} echecs, "
        f"retour local apres {RESTORE_OK_CYCLES} cycles OK"
    )

    fail_count = 0
    ok_count = 0

    while True:
        ap_active = zero_ap_active()
        ap_ok = pi5_ap_ok()
        local_ok = pi5_local_wifi_ok()
        pi5_ok = ap_ok or local_ok

        log(f"Zero PA={ap_active} | Pi5: RB2-ROS={ap_ok} WiFi-local={local_ok}")

        if not ap_active:
            # --- Surveillance : faut-il lever le PA secours ? ---
            ok_count = 0

            if not pi5_ok:
                fail_count += 1
                log(f"Deux Wi-Fi Pi5 indisponibles: {fail_count}/{FAILS_BEFORE_TRIGGER}")
                if fail_count >= FAILS_BEFORE_TRIGGER:
                    activate_zero_ap()
                    fail_count = 0
            else:
                if fail_count:
                    log("Au moins un Wi-Fi Pi5 est revenu; compteur remis a zero")
                fail_count = 0
        else:
            # --- PA secours actif : faut-il revenir au reseau local ? ---
            fail_count = 0

            if pi5_ok:
                ok_count += 1
                log(f"Wi-Fi Pi5 retabli pendant le secours: {ok_count}/{RESTORE_OK_CYCLES}")
                if ok_count >= RESTORE_OK_CYCLES:
                    restore_local()
                    ok_count = 0
            else:
                if ok_count:
                    log("Wi-Fi Pi5 de nouveau indisponible; on garde le secours")
                ok_count = 0

        time.sleep(CHECK_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
