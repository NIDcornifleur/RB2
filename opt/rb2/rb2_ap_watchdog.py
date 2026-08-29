#!/usr/bin/env python3
"""
RB2 - Chien de garde du point d'accès RB2-ROS (dongle Alfa wlxXXXXXXXXXXXX).

Problème traité
---------------
Le dongle Alfa (mt76x2u) se ré-énumère parfois sur le bus USB (brownout /
reset d'alimentation). Quand ça arrive :

- hostapd reste « active (running) » mais accroché à l'ancienne instance
  disparue de l'interface, coincé à l'état HT_SCAN ;
- rb2-ap-ip.service est un oneshot : il ne se rejoue pas, donc 10.42.0.1
  n'est jamais remis sur la nouvelle instance ;
- résultat : l'interface reste DOWN sans IP, RB2-ROS n'émet plus, alors
  que « systemctl status hostapd » affiche tout en vert.

C'est exactement ce qui s'est produit le 2026-08-29 (reset du dongle à
13:42, ~4 min après le boot) : RB2-ROS est resté mort jusqu'à un
« systemctl restart hostapd » manuel à 16:19.

Ce service vérifie périodiquement que le PA émet réellement et, sinon,
relance rb2-ap-ip.service puis hostapd.service — l'équivalent automatique
du dépannage manuel.

Un coupe-circuit évite la tempête de redémarrages si le dongle est
physiquement absent : après BACKOFF_AFTER réparations rapprochées, on
passe en surveillance lente pendant BACKOFF_S.
"""
import subprocess
import time

AP_IF = "wlxXXXXXXXXXXXX"
AP_SSID = "RB2-ROS"
AP_IP = "10.42.0.1"

IW = "/usr/sbin/iw"
IP = "/usr/sbin/ip"
SYSTEMCTL = "/usr/bin/systemctl"

CHECK_S = 15
FAILS_BEFORE_FIX = 2            # 2 x 15 s => ~30 s d'anomalie avant d'agir
COOLDOWN_S = 90                 # après une réparation, laisser hostapd réinitialiser
BACKOFF_AFTER = 4               # réparations rapprochées avant coupe-circuit
BACKOFF_S = 600                 # surveillance lente quand le coupe-circuit se déclenche
STABLE_RESET_S = 300            # PA sain pendant ce délai => on oublie les réparations passées


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def run(cmd, timeout=15):
    try:
        p = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return p.returncode, (p.stdout or "").strip()
    except Exception as e:
        return 999, str(e)


def ap_healthy():
    # 1. hostapd doit être actif.
    rc, _ = run([SYSTEMCTL, "is-active", "--quiet", "hostapd.service"])
    if rc != 0:
        return False, "hostapd inactif"

    # 2. L'interface doit exister, être en mode AP et avoir chargé le SSID.
    #    Quand hostapd est orphelin, « iw info » montre « type AP » mais
    #    ni « ssid » ni « channel » : c'est le signal le plus fiable.
    rc, out = run([IW, "dev", AP_IF, "info"])
    if rc != 0:
        return False, f"{AP_IF} absent (iw info rc={rc})"
    if "type AP" not in out:
        return False, f"{AP_IF} pas en mode AP"
    if f"ssid {AP_SSID}" not in out:
        return False, f"{AP_IF} SSID non chargé (hostapd non initialisé)"
    if "channel " not in out:
        return False, f"{AP_IF} sans canal (hostapd non initialisé)"

    # 3. Lien pas explicitement DOWN. Pour un AP nl80211 operstate vaut
    #    souvent « unknown » ; on ne rejette que « down ».
    rc, out = run(["/usr/bin/cat", f"/sys/class/net/{AP_IF}/operstate"])
    if out == "down":
        return False, f"{AP_IF} operstate=down"

    # 4. L'IP statique du PA doit être présente.
    rc, out = run([IP, "-4", "-o", "addr", "show", "dev", AP_IF])
    if AP_IP not in out:
        return False, f"{AP_IF} sans {AP_IP}"

    return True, "OK"


def repair():
    log("Réparation PA RB2-ROS : restart rb2-ap-ip.service puis hostapd.service")
    rc1, out1 = run([SYSTEMCTL, "restart", "rb2-ap-ip.service"], timeout=25)
    if rc1 != 0:
        log(f"  rb2-ap-ip.service restart rc={rc1} : {out1}")
    time.sleep(2)
    rc2, out2 = run([SYSTEMCTL, "restart", "hostapd.service"], timeout=25)
    if rc2 != 0:
        log(f"  hostapd.service restart rc={rc2} : {out2}")


def main():
    log("RB2 chien de garde PA RB2-ROS démarré")

    fails = 0
    repairs = 0
    last_repair = 0.0

    while True:
        ok, reason = ap_healthy()

        if ok:
            fails = 0
            if repairs and (time.time() - last_repair) > STABLE_RESET_S:
                log("PA stable ; compteur de réparations remis à zéro")
                repairs = 0
            time.sleep(CHECK_S)
            continue

        fails += 1
        log(f"PA anormal ({reason}) : {fails}/{FAILS_BEFORE_FIX}")

        if fails < FAILS_BEFORE_FIX:
            time.sleep(CHECK_S)
            continue

        repair()
        fails = 0
        repairs += 1
        last_repair = time.time()

        if repairs >= BACKOFF_AFTER:
            log(
                f"{repairs} réparations rapprochées : coupe-circuit, "
                f"surveillance lente pendant {BACKOFF_S}s "
                f"(dongle Alfa probablement débranché ?)"
            )
            time.sleep(BACKOFF_S)
            repairs = 0
        else:
            time.sleep(COOLDOWN_S)


if __name__ == "__main__":
    main()
