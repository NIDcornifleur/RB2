#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Pont JSON pour le VL53L1X (télémètre ToF simple point).
# Adresse I2C 0x2A: le VL53L1X démarre à 0x29 (comme le VL53L5CX) et est
# réassigné à 0x2A au boot par rb2-tof-addr-init.service - ce service doit
# donc être actif avant celui-ci (voir dépendance systemd).
#
# Utilise la lib Adafruit CircuitPython (adafruit-circuitpython-vl53l1x),
# pas la lib Pimoroni (pip "vl53l1x"): cette dernière fait un poll bloquant
# côté extension C en attendant la fin de chaque mesure, ce qui gelait le
# bus i2c-1 au niveau matériel en quelques secondes (TimeoutError Errno 110,
# récupérable seulement par un débranchement/rebranchement physique du
# capteur - un simple reboot du Pi ne suffit pas). La lib Adafruit lit les
# registres directement en Python (via smbus), sans poll bloquant caché:
# testée en direct plus de 700 lectures consécutives sans geler le bus.

import json
import os
import tempfile
import time
import sys

OUT_FILE = "/tmp/rb2_vl53l1x.json"

ADDR = 0x2A
DISTANCE_MODE_LONG = 2  # jusqu'à ~3.6m, moins précis en pleine lumière
TIMING_BUDGET_MS = 50   # valeur discrète valide la plus proche de l'ancien budget (66ms)

try:
    import board
    import adafruit_vl53l1x
except ImportError:
    print(
        "ERREUR: module adafruit_vl53l1x absent "
        "(pip install --user --break-system-packages adafruit-circuitpython-vl53l1x)",
        flush=True,
    )
    sys.exit(1)


def atomic_write_json(path, data):
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".rb2_vl53l1x_", suffix=".json", dir=directory)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp_path, path)

    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


def write_error(error_text):
    data = {
        "ok": False,
        "stamp": time.time(),
        "source": "vl53l1x",
        "address": f"0x{ADDR:02X}",
        "error": str(error_text),
    }
    atomic_write_json(OUT_FILE, data)


def run_once():
    i2c = board.I2C()
    tof = adafruit_vl53l1x.VL53L1X(i2c, address=ADDR)

    try:
        tof.distance_mode = DISTANCE_MODE_LONG
        tof.timing_budget = TIMING_BUDGET_MS
        tof.start_ranging()

        print(f"RB2 VL53L1X JSON actif: 0x{ADDR:02X} -> {OUT_FILE}", flush=True)

        while True:
            if not tof.data_ready:
                time.sleep(0.01)
                continue

            # distance_cm est None si le registre RANGE_STATUS brut n'indique
            # pas "9" (mesure valide) - pas de code/texte détaillé exposé par
            # cette lib, contrairement à l'ancienne (Pimoroni).
            distance_cm = tof.distance
            tof.clear_interrupt()

            valid = distance_cm is not None
            distance_mm = round(distance_cm * 10) if valid else None

            data = {
                "ok": True,
                "stamp": time.time(),
                "source": "vl53l1x",
                "address": f"0x{ADDR:02X}",
                "frame_id": "vl53l1x_link",

                "distance_mm": distance_mm,
                "valid": valid,
            }

            atomic_write_json(OUT_FILE, data)

    finally:
        try:
            tof.stop_ranging()
        except Exception:
            pass


def main():
    while True:
        try:
            run_once()

        except KeyboardInterrupt:
            raise

        except Exception as e:
            print(f"RB2 VL53L1X erreur: {e}", flush=True)
            write_error(e)
            time.sleep(2.0)


if __name__ == "__main__":
    main()
