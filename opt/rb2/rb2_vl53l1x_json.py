#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Pont JSON pour le VL53L1X (télémètre ToF simple point).
# Adresse I2C 0x2A: le VL53L1X démarre à 0x29 (comme le VL53L5CX) et est
# réassigné à 0x2A au boot par rb2-tof-addr-init.service - ce service doit
# donc être actif avant celui-ci (voir dépendance systemd).

import json
import os
import tempfile
import time
import sys

OUT_FILE = "/tmp/rb2_vl53l1x.json"

BUS_NUM = 1
ADDR = 0x2A

try:
    import VL53L1X
except ImportError:
    print("ERREUR: module VL53L1X absent (pip install --user --break-system-packages vl53l1x)", flush=True)
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
    tof = VL53L1X.VL53L1X(i2c_bus=BUS_NUM, i2c_address=ADDR)
    tof.open()

    try:
        # Mode LONG (jusqu'à ~4m, moins précis en pleine lumière) par défaut:
        # convient à la détection d'obstacle mobile plutôt qu'à la précision fine.
        tof.set_timing_budget(66000)
        tof.set_inter_measurement_period(70)
        tof.start_ranging(VL53L1X.VL53L1xDistanceMode.LONG)

        print(f"RB2 VL53L1X JSON actif: 0x{ADDR:02X} -> {OUT_FILE}", flush=True)

        while True:
            distance_mm = tof.get_distance()
            status_code = tof.get_range_status()
            status_text = tof.get_range_status_string()

            # Code 0 = mesure valide (RangeStatus "Range valid"). Les autres codes
            # (ex: 1 signal insuffisant, 2 excès de bruit ambiant) restent renvoyés
            # tels quels: c'est au consommateur du JSON de décider s'il les ignore.
            data = {
                "ok": True,
                "stamp": time.time(),
                "source": "vl53l1x",
                "address": f"0x{ADDR:02X}",
                "frame_id": "vl53l1x_link",

                "distance_mm": distance_mm,
                "valid": status_code == 0,

                "status": {
                    "code": status_code,
                    "text": status_text,
                },
            }

            atomic_write_json(OUT_FILE, data)
            time.sleep(0.07)

    finally:
        try:
            tof.stop_ranging()
        except Exception:
            pass
        tof.close()


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
