#!/usr/bin/env python3
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
FAILS_BEFORE_TRIGGER = 6  # 6 x 10 s = environ 60 secondes

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

    # Ne jamais reconnecter automatiquement le Zero au Wi-Fi local.
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


def status_once():
    ap_active = zero_ap_active()
    ap_ok = pi5_ap_ok()
    local_ok = pi5_local_wifi_ok()

    print("=== Etat secours Zero ===")
    print(f"Zero PA actif       : {ap_active}")
    print(f"Pi5 RB2-ROS actif   : {ap_ok}")
    print(f"Pi5 Wi-Fi local OK  : {local_ok}")
    print(f"Declenchement si    : Pi5 RB2-ROS=False ET Pi5 Wi-Fi local=False")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="Affiche l'etat sans rien changer")
    parser.add_argument("--force", action="store_true", help="Force l'activation du PA secours")
    args = parser.parse_args()

    if args.status:
        return status_once()

    if args.force:
        activate_zero_ap()
        return 0

    log("RB2 Zero secours auto actif")
    log(f"Surveillance toutes les {CHECK_SECONDS}s; declenchement apres {FAILS_BEFORE_TRIGGER} echecs")

    fail_count = 0

    while True:
        if zero_ap_active():
            log("PA secours deja actif; maintien actif")
            time.sleep(60)
            continue

        ap_ok = pi5_ap_ok()
        local_ok = pi5_local_wifi_ok()

        log(f"Etat Pi5: RB2-ROS={ap_ok} WiFi-local={local_ok}")

        if not ap_ok and not local_ok:
            fail_count += 1
            log(f"Deux Wi-Fi Pi5 indisponibles: compteur {fail_count}/{FAILS_BEFORE_TRIGGER}")
        else:
            if fail_count:
                log("Au moins un Wi-Fi Pi5 est revenu; compteur remis a zero")
            fail_count = 0

        if fail_count >= FAILS_BEFORE_TRIGGER:
            activate_zero_ap()
            fail_count = 0

        time.sleep(CHECK_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
