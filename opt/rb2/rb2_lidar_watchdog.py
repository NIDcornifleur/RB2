#!/usr/bin/env python3
import os
import subprocess
import time

WATCH_FILES = [
    "/tmp/rb2_lidar.json",
    "/tmp/rb2_lidar_map.json",
]

STALE_S = 5.0
CHECK_S = 2.0

# Cooldown après une simple relance des ponts JSON (étape 1) : léger, peu perturbant.
BRIDGE_COOLDOWN_S = 45.0

# Cooldown après une relance complète de rb2-bringup (étape 2) : beaucoup plus long.
# L'étape 2 relance tous les nœuds ROS2 d'un coup (lidar, IMU, tickets-roues,
# odométrie) ; la redécouverte DDS a besoin de temps pour se stabiliser. Avec
# l'ancien cooldown unique de 45s, une nouvelle étape 2 pouvait se redéclencher
# avant que le graphe DDS ait fini de se stabiliser, créant une boucle de
# redémarrages qui ne se résolvait jamais toute seule et coupait les roues à
# répétition pendant la conduite (épisodes du 11 au 23 juillet 2026).
BRINGUP_COOLDOWN_S = 150.0

BRIDGE_SETTLE_S = 5.0
BRINGUP_SETTLE_S = 8.0

# Disjoncteur : si l'étape 2 se déclenche ce nombre de fois de suite sans qu'un
# cycle de vérification confirme un retour à la fraîcheur entre deux tentatives,
# on arrête d'essayer et on attend une longue pause avant de retenter, plutôt
# que de continuer à tout redémarrer indéfiniment sans jamais se stabiliser.
MAX_CONSECUTIVE_BRINGUP_RESTARTS = 3
GIVEUP_BACKOFF_S = 600.0

BRIDGE_SERVICES = [
    "rb2-lidar-json.service",
    "rb2-lidar-map-json.service",
]

BRINGUP_SERVICE = "rb2-bringup.service"


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def file_age_s(path):
    try:
        return time.time() - os.path.getmtime(path)
    except FileNotFoundError:
        return float("inf")


def stale_files():
    result = {}
    for path in WATCH_FILES:
        age = file_age_s(path)
        if age > STALE_S:
            result[path] = age
    return result


def restart_services(services):
    cmd = ["systemctl", "restart"] + list(services)
    log("RUN: " + " ".join(cmd))
    try:
        p = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=35,
        )
        output = (p.stdout or "").strip()
        if output:
            log(output)
        log(f"EXIT: {p.returncode}")
        return p.returncode == 0
    except Exception as e:
        log(f"ERREUR restart_services: {e}")
        return False


def main():
    log("RB2 LIDAR watchdog actif")
    log(f"Surveillance: {', '.join(WATCH_FILES)}")
    log(f"Seuil stale: {STALE_S} s")

    last_action = 0.0
    cooldown = BRIDGE_COOLDOWN_S
    consecutive_bringup_restarts = 0

    while True:
        stale = stale_files()

        if not stale:
            consecutive_bringup_restarts = 0
            time.sleep(CHECK_S)
            continue

        now = time.time()

        if now - last_action < cooldown:
            time.sleep(CHECK_S)
            continue

        details = ", ".join(
            f"{path} age={age:.1f}s" for path, age in stale.items()
        )
        log("LIDAR stale détecté: " + details)

        log("Étape 1: redémarrage des ponts JSON LIDAR")
        restart_services(BRIDGE_SERVICES)
        last_action = time.time()
        cooldown = BRIDGE_COOLDOWN_S
        time.sleep(BRIDGE_SETTLE_S)

        still_stale = stale_files()
        if still_stale:
            details = ", ".join(
                f"{path} age={age:.1f}s" for path, age in still_stale.items()
            )
            log("Toujours stale après ponts JSON: " + details)

            consecutive_bringup_restarts += 1

            if consecutive_bringup_restarts > MAX_CONSECUTIVE_BRINGUP_RESTARTS:
                log(
                    f"ABANDON: {MAX_CONSECUTIVE_BRINGUP_RESTARTS} relances complètes de "
                    f"rb2-bringup consécutives sans stabilisation. Pause de "
                    f"{GIVEUP_BACKOFF_S:.0f}s avant nouvelle tentative, pour éviter "
                    "de continuer à couper les roues en boucle."
                )
                last_action = time.time()
                cooldown = GIVEUP_BACKOFF_S
                consecutive_bringup_restarts = 0
                time.sleep(CHECK_S)
                continue

            log(
                f"Étape 2: redémarrage rb2-bringup puis ponts JSON "
                f"(tentative {consecutive_bringup_restarts}/{MAX_CONSECUTIVE_BRINGUP_RESTARTS})"
            )
            restart_services([BRINGUP_SERVICE])
            time.sleep(BRINGUP_SETTLE_S)
            restart_services(BRIDGE_SERVICES)
            last_action = time.time()
            cooldown = BRINGUP_COOLDOWN_S

        time.sleep(CHECK_S)


if __name__ == "__main__":
    main()
