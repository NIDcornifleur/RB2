#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Le VL53L1X et le VL53L5CX démarrent tous les deux à l'adresse I2C 0x29.
# Le LPn du VL53L5CX est câblé sur GPIO17 (Pi 5, gpiochip4/pinctrl-rp1).
#
# Séquence au démarrage:
#   1. GPIO17 = 0  -> VL53L5CX en veille (LPn bas), seul le VL53L1X répond sur le bus
#   2. on écrit une nouvelle adresse dans le VL53L1X (registre I2C_SLAVE_DEVICE_ADDRESS)
#   3. GPIO17 = 1  -> VL53L5CX redémarre, reprend son adresse par défaut 0x29
#   4. les deux coexistent: VL53L1X à VL53L1X_NEW_ADDR, VL53L5CX à 0x29
#
# Le process reste ensuite résident et maintient GPIO17 à 1: rien ne garantit
# qu'il y ait un pull-up matériel sur ce pin, donc si on libère la ligne GPIO
# en quittant, le LPn du VL53L5CX pourrait flotter (et potentiellement
# repasser bas) tant qu'aucun autre process ne la maintient. Prévu pour
# tourner comme service systemd permanent (Restart=always), pas en one-shot.

import os
import signal
import socket
import sys
import time

BUS_NUM = 1
GPIO_CHIP = 4     # sur Pi 5, les GPIO du connecteur 40 broches sont sur gpiochip4 (pinctrl-rp1)
LPN_PIN = 17

VL53_DEFAULT_ADDR = 0x29
VL53L1X_NEW_ADDR = 0x2A

REG_I2C_SLAVE_DEVICE_ADDRESS = 0x0001
REG_MODEL_ID = 0x010F          # VL53L1X: doit valoir 0xEA
REG_FIRMWARE_SYSTEM_STATUS = 0x00E5  # bit0 = 1 quand le firmware a fini de booter

VL53L1X_MODEL_ID = 0xEA

BOOT_POLL_TIMEOUT_S = 1.0
BOOT_POLL_INTERVAL_S = 0.01

try:
    from smbus2 import SMBus
except ImportError:
    print("ERREUR: module smbus2 absent", flush=True)
    sys.exit(1)

try:
    import lgpio
except ImportError:
    print("ERREUR: module lgpio absent", flush=True)
    sys.exit(1)


def log(msg):
    print(msg, flush=True)


def sd_notify_ready():
    # Signale à systemd (Type=notify) que la réassignation d'adresse est
    # terminée - sans ça, After=/Requires= sur ce service ne garantit que le
    # lancement du process, pas la fin de cette séquence, et les services
    # rb2-vl53l1x-json / rb2-vl53l5cx-json peuvent démarrer et sonder le bus
    # avant que les adresses ne soient stabilisées (race condition observée
    # au boot le 2026-09-15).
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(addr)
        sock.sendall(b"READY=1")
    except OSError:
        pass
    finally:
        sock.close()


def read_reg8(bus, addr, reg16):
    hi = (reg16 >> 8) & 0xFF
    lo = reg16 & 0xFF
    bus.write_i2c_block_data(addr, hi, [lo])
    return bus.read_byte(addr)


def write_reg8(bus, addr, reg16, value):
    hi = (reg16 >> 8) & 0xFF
    lo = reg16 & 0xFF
    bus.write_i2c_block_data(addr, hi, [lo, value])


def probe(bus, addr):
    try:
        bus.read_byte(addr)
        return True
    except OSError:
        return False


def wait_boot_complete(bus, addr, timeout_s=BOOT_POLL_TIMEOUT_S):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            status = read_reg8(bus, addr, REG_FIRMWARE_SYSTEM_STATUS)
            if status & 0x01:
                return True
        except OSError:
            pass
        time.sleep(BOOT_POLL_INTERVAL_S)
    return False


def reassign_vl53l1x_address(bus):
    # Idempotence: si le service redémarre sans coupure d'alimentation réelle
    # (ex. redémarrage du service seul), le VL53L1X garde l'adresse déjà
    # assignée précédemment - son registre d'adresse ne se réinitialise qu'à
    # une vraie coupure d'alim, pas à un restart logiciel. Dans ce cas il n'y
    # a rien à faire, inutile de chercher un VL53L1X (absent) à 0x29.
    if probe(bus, VL53L1X_NEW_ADDR):
        model_id = read_reg8(bus, VL53L1X_NEW_ADDR, REG_MODEL_ID)
        if model_id == VL53L1X_MODEL_ID:
            log("VL53L1X déjà à 0x{:02X} (MODEL_ID=0x{:02X}), rien à faire".format(
                VL53L1X_NEW_ADDR, model_id
            ))
            return

    if not wait_boot_complete(bus, VL53_DEFAULT_ADDR):
        raise RuntimeError("VL53L1X: timeout attente boot complete (FIRMWARE__SYSTEM_STATUS)")

    model_id = read_reg8(bus, VL53_DEFAULT_ADDR, REG_MODEL_ID)
    if model_id != VL53L1X_MODEL_ID:
        raise RuntimeError(
            "VL53L1X: MODEL_ID inattendu à 0x{:02X} (lu 0x{:02X}, attendu 0x{:02X}) "
            "- capteur non reconnu, on n'écrit pas l'adresse par sécurité".format(
                VL53_DEFAULT_ADDR, model_id, VL53L1X_MODEL_ID
            )
        )

    log("VL53L1X détecté à 0x{:02X} (MODEL_ID=0x{:02X}), réassignation vers 0x{:02X}".format(
        VL53_DEFAULT_ADDR, model_id, VL53L1X_NEW_ADDR
    ))

    write_reg8(bus, VL53_DEFAULT_ADDR, REG_I2C_SLAVE_DEVICE_ADDRESS, VL53L1X_NEW_ADDR)
    time.sleep(0.01)

    if probe(bus, VL53_DEFAULT_ADDR):
        raise RuntimeError(
            "VL53L1X: 0x{:02X} répond encore après réassignation, échec probable".format(VL53_DEFAULT_ADDR)
        )

    new_model_id = read_reg8(bus, VL53L1X_NEW_ADDR, REG_MODEL_ID)
    if new_model_id != VL53L1X_MODEL_ID:
        raise RuntimeError(
            "VL53L1X: MODEL_ID inattendu à la nouvelle adresse 0x{:02X} (lu 0x{:02X})".format(
                VL53L1X_NEW_ADDR, new_model_id
            )
        )

    log("VL53L1X confirmé à sa nouvelle adresse 0x{:02X}".format(VL53L1X_NEW_ADDR))


_running = True


def _on_sigterm(signum, frame):
    global _running
    _running = False


def main():
    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGINT, _on_sigterm)

    gpio_h = lgpio.gpiochip_open(GPIO_CHIP)
    lgpio.gpio_claim_output(gpio_h, LPN_PIN, 0)  # VL53L5CX en veille
    log("GPIO{} (LPn VL53L5CX) = 0, capteur en veille".format(LPN_PIN))
    time.sleep(0.05)

    bus = SMBus(BUS_NUM)
    try:
        reassign_vl53l1x_address(bus)

        lgpio.gpio_write(gpio_h, LPN_PIN, 1)
        log("GPIO{} (LPn VL53L5CX) = 1, capteur réveillé".format(LPN_PIN))
        time.sleep(0.1)

        if not probe(bus, VL53_DEFAULT_ADDR):
            log("ATTENTION: VL53L5CX ne répond pas à 0x{:02X} après réveil".format(VL53_DEFAULT_ADDR))
        else:
            log("VL53L5CX confirmé à 0x{:02X}".format(VL53_DEFAULT_ADDR))

        log("État final attendu sur i2c-{}: 0x28 BNO055, 0x{:02X} VL53L5CX, 0x{:02X} VL53L1X".format(
            BUS_NUM, VL53_DEFAULT_ADDR, VL53L1X_NEW_ADDR
        ))
    except Exception as exc:
        log("ERREUR réassignation VL53L1X: {}".format(exc))
        log("GPIO{} laissé à 1 par sécurité (VL53L5CX actif, adresse VL53L1X inchangée)".format(LPN_PIN))
        lgpio.gpio_write(gpio_h, LPN_PIN, 1)
    finally:
        bus.close()

    # Adresses stabilisées (avec ou sans erreur de réassignation - dans les
    # deux cas GPIO17 est déjà dans son état final), on peut prévenir
    # systemd que les services dépendants peuvent démarrer sans risquer de
    # sonder le bus trop tôt.
    sd_notify_ready()

    # Reste résident pour maintenir GPIO17 (LPn) à 1 tant qu'aucun pull-up
    # matériel n'est confirmé sur ce pin - voir le commentaire en tête de fichier.
    while _running:
        time.sleep(1)

    lgpio.gpio_free(gpio_h, LPN_PIN)
    lgpio.gpiochip_close(gpio_h)
    log("Arrêt, GPIO{} libéré".format(LPN_PIN))


if __name__ == "__main__":
    main()
