#!/usr/bin/env python3
import os
import subprocess
import time

WATCH_FILES = [
    "/tmp/rb2_vl53l1x.json",   # sol
    "/tmp/rb2_vl53l5cx.json",  # plafond
]

STALE_S = 10.0
CHECK_S = 2.0

# Étape 1 : simple redémarrage des deux ponts JSON ToF. Confirmé suffisant
# en pratique le 2026-09-17 (aucun débranchement physique nécessaire ce
# jour-là, contrairement aux incidents de gel i2c-1 plus sévères de
# septembre où un cycle d'alimentation physique des capteurs était requis
# en plus du redémarrage logiciel).
BRIDGE_COOLDOWN_S = 45.0
BRIDGE_SETTLE_S = 20.0  # le VL53L5CX prend ~15-17s pour uploader son firmware ULD

# Étape 2 : si l'étape 1 ne suffit pas, on redémarre aussi la
# réassignation d'adresse I2C (LPn/GPIO17) avant de relancer les ponts.
ADDR_COOLDOWN_S = 150.0
ADDR_SETTLE_S = 5.0

# Disjoncteur : si l'étape 2 ne stabilise rien après plusieurs tentatives
# consécutives, on arrête d'essayer tout seul. À ce stade, l'expérience
# des incidents i2c-1 de septembre 2026 suggère qu'un débranchement
# physique de l'alimentation des capteurs ToF peut être nécessaire.
MAX_CONSECUTIVE_ADDR_RESTARTS = 3
GIVEUP_BACKOFF_S = 600.0

BRIDGE_SERVICES = [
    "rb2-vl53l1x-json.service",
    "rb2-vl53l5cx-json.service",
]

ADDR_SERVICE = "rb2-tof-addr-init.service"


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
    log("RB2 ToF watchdog actif (sol=VL53L1X, plafond=VL53L5CX)")
    log(f"Surveillance: {', '.join(WATCH_FILES)}")
    log(f"Seuil stale: {STALE_S} s")

    last_action = 0.0
    cooldown = BRIDGE_COOLDOWN_S
    consecutive_addr_restarts = 0

    while True:
        stale = stale_files()

        if not stale:
            consecutive_addr_restarts = 0
            time.sleep(CHECK_S)
            continue

        now = time.time()

        if now - last_action < cooldown:
            time.sleep(CHECK_S)
            continue

        details = ", ".join(f"{path} age={age:.1f}s" for path, age in stale.items())
        log("ToF stale détecté: " + details)

        log("Étape 1: redémarrage des ponts JSON ToF")
        restart_services(BRIDGE_SERVICES)
        last_action = time.time()
        cooldown = BRIDGE_COOLDOWN_S
        time.sleep(BRIDGE_SETTLE_S)

        still_stale = stale_files()
        if still_stale:
            details = ", ".join(f"{path} age={age:.1f}s" for path, age in still_stale.items())
            log("Toujours stale après ponts JSON: " + details)

            consecutive_addr_restarts += 1

            if consecutive_addr_restarts > MAX_CONSECUTIVE_ADDR_RESTARTS:
                log(
                    f"ABANDON: {MAX_CONSECUTIVE_ADDR_RESTARTS} relances de "
                    f"{ADDR_SERVICE} consécutives sans stabilisation. Un "
                    "débranchement/rebranchement physique de l'alimentation "
                    f"des capteurs ToF est probablement nécessaire. Pause de "
                    f"{GIVEUP_BACKOFF_S:.0f}s avant nouvelle tentative."
                )
                last_action = time.time()
                cooldown = GIVEUP_BACKOFF_S
                consecutive_addr_restarts = 0
                time.sleep(CHECK_S)
                continue

            log(
                f"Étape 2: redémarrage {ADDR_SERVICE} puis ponts JSON "
                f"(tentative {consecutive_addr_restarts}/{MAX_CONSECUTIVE_ADDR_RESTARTS})"
            )
            restart_services([ADDR_SERVICE])
            time.sleep(ADDR_SETTLE_S)
            restart_services(BRIDGE_SERVICES)
            last_action = time.time()
            cooldown = ADDR_COOLDOWN_S

        time.sleep(CHECK_S)


if __name__ == "__main__":
    main()
