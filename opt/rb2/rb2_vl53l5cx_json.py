#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Pont JSON pour le VL53L5CX (ToF multizone, grille 4x4).
# Adresse I2C 0x29 (adresse par défaut, inchangée): le capteur passe par un
# cycle veille/réveil sur GPIO17 (LPn) au boot, piloté par
# rb2-tof-addr-init.service, pour laisser le VL53L1X se réassigner sans
# collision - ce service doit donc être actif avant celui-ci.
#
# Codes de statut ST (target_status) considérés valides ici: 5, 6, 9
# (mesure fiable / avertissement mineur / cible fusionnée) - les autres
# (ex: 255 = pas de cible) sont marqués invalides plutôt qu'ignorés.
#
# Bus i2c-3 (pas i2c-1): le contrôleur matériel DesignWare de i2c-1 se
# bloquait régulièrement sans déclencheur identifiable (dmesg: "controller
# timed out"), récupérable seulement par un débranchement physique des
# capteurs. i2c-3 est un bus i2c-gpio bit-bangé (overlay
# dtoverlay=i2c-gpio,bus=3, GPIO23/24) qui gère le stretching d'horloge en
# logiciel côté noyau.

import json
import os
import tempfile
import time
import sys

OUT_FILE = "/tmp/rb2_vl53l5cx.json"

ADDR = 0x29
RESOLUTION = "4x4"
GRID_SIZE = 16
RANGING_FREQUENCY_HZ = 15
I2C_BUS_NUM = 3

VALID_STATUS_CODES = (5, 6, 9)

try:
    import vl53l5cx_ctypes as vl53l5cx
    from smbus2 import SMBus
except ImportError:
    print("ERREUR: module vl53l5cx_ctypes/smbus2 absent (pip install --user --break-system-packages vl53l5cx-ctypes smbus2)", flush=True)
    sys.exit(1)


def atomic_write_json(path, data):
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".rb2_vl53l5cx_", suffix=".json", dir=directory)

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
        "source": "vl53l5cx",
        "address": f"0x{ADDR:02X}",
        "error": str(error_text),
    }
    atomic_write_json(OUT_FILE, data)


def run_once():
    tof = vl53l5cx.VL53L5CX(i2c_dev=SMBus(I2C_BUS_NUM))

    try:
        tof.set_resolution(vl53l5cx.RESOLUTION_4X4)
        tof.set_ranging_frequency_hz(RANGING_FREQUENCY_HZ)
        tof.start_ranging()

        print(f"RB2 VL53L5CX JSON actif: 0x{ADDR:02X} grille {RESOLUTION} -> {OUT_FILE}", flush=True)

        while True:
            if not tof.data_ready():
                time.sleep(0.02)
                continue

            frame = tof.get_data()

            distances = [int(v) for v in frame.distance_mm[0][:GRID_SIZE]]
            statuses = [int(v) for v in frame.target_status[0][:GRID_SIZE]]
            valid = [s in VALID_STATUS_CODES for s in statuses]

            valid_distances = [d for d, v in zip(distances, valid) if v]
            min_valid_distance_mm = min(valid_distances) if valid_distances else None

            data = {
                "ok": True,
                "stamp": time.time(),
                "source": "vl53l5cx",
                "address": f"0x{ADDR:02X}",
                "frame_id": "vl53l5cx_link",

                "resolution": RESOLUTION,
                "grid_size": GRID_SIZE,

                "distance_mm": distances,
                "status": statuses,
                "valid": valid,

                "min_valid_distance_mm": min_valid_distance_mm,
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
            print(f"RB2 VL53L5CX erreur: {e}", flush=True)
            write_error(e)
            time.sleep(2.0)


if __name__ == "__main__":
    main()
