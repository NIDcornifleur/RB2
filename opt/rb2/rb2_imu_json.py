#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import tempfile
import time
import sys

OUT_FILE = "/tmp/rb2_imu.json"

BUS_NUM = 1
ADDR = 0x28

# BNO055 registers
REG_CHIP_ID = 0x00
REG_PAGE_ID = 0x07
REG_CALIB = 0x35
REG_SYS_STAT = 0x39
REG_SYS_ERR = 0x3A
REG_UNIT_SEL = 0x3B
REG_OPR_MODE = 0x3D
REG_PWR_MODE = 0x3E

REG_ACC_X = 0x08
REG_GYR_X = 0x14
REG_EULER_H = 0x1A
REG_EULER_R = 0x1C
REG_EULER_P = 0x1E

MODE_CONFIG = 0x00
MODE_IMUPLUS = 0x08   # gyro + accel, sans magnétomètre
MODE_NDOF = 0x0C      # gyro + accel + magnétomètre

# Pour RB2 on commence volontairement sans magnétomètre.
# Les moteurs, BTS7960 et câbles de puissance peuvent perturber le magnétomètre.
MODE_USED = MODE_IMUPLUS
MODE_NAME = "IMUPLUS"

try:
    from smbus2 import SMBus
except ImportError:
    try:
        from smbus import SMBus
    except ImportError:
        print("ERREUR: module smbus/smbus2 absent", flush=True)
        sys.exit(1)


def atomic_write_json(path, data):
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".rb2_imu_", suffix=".json", dir=directory)

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


def s16(lo, hi):
    v = lo | (hi << 8)
    if v & 0x8000:
        v -= 65536
    return v


def read_s16(bus, reg):
    d = bus.read_i2c_block_data(ADDR, reg, 2)
    return s16(d[0], d[1])


def read_vec3(bus, reg, scale):
    d = bus.read_i2c_block_data(ADDR, reg, 6)

    x = s16(d[0], d[1]) / scale
    y = s16(d[2], d[3]) / scale
    z = s16(d[4], d[5]) / scale

    return x, y, z


def write_byte(bus, reg, val, delay=0.03):
    bus.write_byte_data(ADDR, reg, val)
    time.sleep(delay)


def read_euler(bus):
    heading = read_s16(bus, REG_EULER_H) / 16.0
    roll = read_s16(bus, REG_EULER_R) / 16.0
    pitch = read_s16(bus, REG_EULER_P) / 16.0
    return heading, roll, pitch


def norm_angle_180(deg):
    while deg > 180.0:
        deg -= 360.0
    while deg < -180.0:
        deg += 360.0
    return deg


def init_bno055(bus):
    time.sleep(0.7)

    chip = None
    for _ in range(10):
        try:
            chip = bus.read_byte_data(ADDR, REG_CHIP_ID)
            if chip == 0xA0:
                break
        except Exception:
            pass
        time.sleep(0.2)

    if chip != 0xA0:
        raise RuntimeError(f"BNO055 CHIP_ID inattendu: {chip!r}")

    write_byte(bus, REG_PAGE_ID, 0x00)
    write_byte(bus, REG_OPR_MODE, MODE_CONFIG, 0.08)
    write_byte(bus, REG_PWR_MODE, 0x00, 0.03)

    # Unités par défaut:
    # Euler en degrés, accel en m/s², gyro en degrés/s.
    write_byte(bus, REG_UNIT_SEL, 0x00, 0.03)

    write_byte(bus, REG_OPR_MODE, MODE_USED, 0.7)

    return chip


def auto_zero(bus, seconds=3.0):
    print("BNO055: zéro automatique roll/pitch, garder RB2 immobile et à plat...", flush=True)

    samples = []
    t_end = time.time() + seconds

    while time.time() < t_end:
        try:
            h, r, p = read_euler(bus)
            samples.append((h, r, p))
        except Exception:
            pass
        time.sleep(0.1)

    if len(samples) < 5:
        raise RuntimeError("pas assez d'échantillons pour zéro automatique")

    heading0 = sum(x[0] for x in samples) / len(samples)
    roll0 = sum(x[1] for x in samples) / len(samples)
    pitch0 = sum(x[2] for x in samples) / len(samples)

    print(
        f"BNO055: zéro établi heading0={heading0:.2f} roll0={roll0:.2f} pitch0={pitch0:.2f}",
        flush=True
    )

    return heading0, roll0, pitch0


def write_error(error_text):
    data = {
        "ok": False,
        "stamp": time.time(),
        "source": "bno055",
        "address": "0x28",
        "mode": MODE_NAME,
        "error": str(error_text),
    }
    atomic_write_json(OUT_FILE, data)


def run_once():
    with SMBus(BUS_NUM) as bus:
        chip = init_bno055(bus)
        heading0, roll0, pitch0 = auto_zero(bus, seconds=3.0)

        print(f"RB2 IMU JSON BNO055 actif: 0x{ADDR:02X} -> {OUT_FILE}", flush=True)

        while True:
            h_raw, r_raw, p_raw = read_euler(bus)

            # Convention RB2:
            # - roll: gauche/droite
            # - pitch: avant/arrière
            # Test observé: avant levé -> pitch BNO devient négatif.
            # On inverse donc pitch pour que avant levé devienne positif côté RB2.
            heading = norm_angle_180(h_raw - heading0)
            roll = r_raw - roll0
            pitch = -(p_raw - pitch0)

            ax, ay, az = read_vec3(bus, REG_ACC_X, 100.0)   # m/s²
            gx, gy, gz = read_vec3(bus, REG_GYR_X, 16.0)    # degrés/s

            cal = bus.read_byte_data(ADDR, REG_CALIB)
            sys_cal = (cal >> 6) & 3
            gyr_cal = (cal >> 4) & 3
            acc_cal = (cal >> 2) & 3
            mag_cal = cal & 3

            sys_stat = bus.read_byte_data(ADDR, REG_SYS_STAT)
            sys_err = bus.read_byte_data(ADDR, REG_SYS_ERR)
            opr_mode = bus.read_byte_data(ADDR, REG_OPR_MODE)

            # Le chip peut retomber en CONFIGMODE (ex: coupure/glitch d'alimentation
            # pendant une manipulation du câblage) sans qu'aucune lecture I2C n'échoue.
            # Dans ce cas les lectures restent "valides" mais figées à zéro, et le
            # service continuait avant ce correctif à répondre ok:true indéfiniment.
            # On force une réinitialisation dès que le mode ou le statut dérive.
            if opr_mode != MODE_USED or sys_stat == 1:
                raise RuntimeError(
                    f"BNO055 hors mode {MODE_NAME}: OPR_MODE=0x{opr_mode:02X} "
                    f"sys_stat={sys_stat} sys_err={sys_err} -> réinitialisation"
                )

            data = {
                "ok": True,
                "stamp": time.time(),
                "source": "bno055",
                "address": "0x28",
                "chip_id": f"0x{chip:02X}",
                "mode": MODE_NAME,
                "frame_id": "imu_link",

                "roll_deg": roll,
                "pitch_deg": pitch,
                "heading_deg": heading,

                "euler_raw": {
                    "heading_deg": h_raw,
                    "roll_deg": r_raw,
                    "pitch_deg": p_raw,
                },

                "zero": {
                    "heading_deg": heading0,
                    "roll_deg": roll0,
                    "pitch_deg": pitch0,
                },

                "accel": {
                    "x": ax,
                    "y": ay,
                    "z": az,
                },

                "gyro": {
                    "x": gx,
                    "y": gy,
                    "z": gz,
                },

                "calibration": {
                    "sys": sys_cal,
                    "gyro": gyr_cal,
                    "accel": acc_cal,
                    "mag": mag_cal,
                },

                "status": {
                    "sys_stat": sys_stat,
                    "sys_err": sys_err,
                    "opr_mode": f"0x{opr_mode:02X}",
                },
            }

            atomic_write_json(OUT_FILE, data)
            time.sleep(0.10)


def main():
    while True:
        try:
            run_once()

        except KeyboardInterrupt:
            raise

        except Exception as e:
            print(f"RB2 IMU BNO055 erreur: {e}", flush=True)
            write_error(e)
            time.sleep(2.0)


if __name__ == "__main__":
    main()
