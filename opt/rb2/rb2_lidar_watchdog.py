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
COOLDOWN_S = 45.0
BRIDGE_SETTLE_S = 5.0
BRINGUP_SETTLE_S = 8.0

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

    while True:
        stale = stale_files()

        if stale:
            now = time.time()

            if now - last_action < COOLDOWN_S:
                time.sleep(CHECK_S)
                continue

            details = ", ".join(
                f"{path} age={age:.1f}s" for path, age in stale.items()
            )
            log("LIDAR stale détecté: " + details)

            log("Étape 1: redémarrage des ponts JSON LIDAR")
            restart_services(BRIDGE_SERVICES)
            last_action = time.time()
            time.sleep(BRIDGE_SETTLE_S)

            still_stale = stale_files()
            if still_stale:
                details = ", ".join(
                    f"{path} age={age:.1f}s" for path, age in still_stale.items()
                )
                log("Toujours stale après ponts JSON: " + details)

                log("Étape 2: redémarrage rb2-bringup puis ponts JSON")
                restart_services([BRINGUP_SERVICE])
                time.sleep(BRINGUP_SETTLE_S)
                restart_services(BRIDGE_SERVICES)
                last_action = time.time()

        time.sleep(CHECK_S)


if __name__ == "__main__":
    main()
