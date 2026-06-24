#!/usr/bin/env python3
import json
import math
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

# RB2 - Retour WiFi nouvelle logique
# Déclenche seulement si :
# - Retour WiFi armé dans l'interface RB2
# - heartbeat opérateur absent depuis HEARTBEAT_ABSENT_S
# - PA Alfa sans station connectée
# - Wi-Fi local wlan0 non connecté
# - dernière conduite assez récente
# - LIDAR arrière libre

AP_IFACE = "wlxXXXXXXXXXXXX"
LOCAL_IFACE = "wlan0"

HEARTBEAT_ABSENT_S = 15.0
RECENT_DRIVE_WINDOW_S = 900.0

BACK_MIN_CM = 20.0

CMD_REVERSE = "d-20,-20"
PULSE_S = 2.0
STOP_S = 0.8
MAX_PULSES = 5
LOOP_S = 1.0
COOLDOWN_S = 45.0

STATUS_FILE = Path("/tmp/rb2_wifi_dual_loss_return.json")
LIDAR_FILE = Path("/tmp/rb2_lidar.json")

last_trigger_time = 0.0


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def sh(cmd, timeout=2.0):
    try:
        r = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 999, "", str(e)


def http_json(path):
    try:
        with urllib.request.urlopen("http://127.0.0.1:5051" + path, timeout=2.0) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def post_form(path, data=None):
    if data is None:
        data = {}

    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:5051" + path,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req, timeout=2.5) as r:
            return True, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return False, str(e)


def stop_motors():
    return post_form("/stop", {})


def drive_cmd(cmd):
    # Compatible avec la route /cmd habituelle du panneau RB2.
    return post_form("/cmd", {"cmd": cmd})


def ap_has_station():
    rc, out, err = sh(["iw", "dev", AP_IFACE, "station", "dump"], timeout=2.0)

    if rc != 0:
        return False, f"PA {AP_IFACE}: station dump impossible"

    if "Station " in out:
        return True, f"PA {AP_IFACE}: station connectée"

    return False, f"PA {AP_IFACE}: aucune station"


def local_wifi_connected():
    rc, out, err = sh(["iw", "dev", LOCAL_IFACE, "link"], timeout=2.0)

    if rc != 0:
        return False, f"{LOCAL_IFACE}: iw link impossible"

    if "Connected to" in out:
        ssid = ""
        for line in out.splitlines():
            if line.strip().startswith("SSID:"):
                ssid = line.strip()
                break
        return True, f"{LOCAL_IFACE}: connecté {ssid}"

    return False, f"{LOCAL_IFACE}: non connecté"


def lidar_back_clear():
    try:
        d = json.loads(LIDAR_FILE.read_text(encoding="utf-8"))
        back = d.get("back_cm")
        n = float(back)
    except Exception as e:
        return False, f"LIDAR arrière absent/invalide: {e}", None

    if not math.isfinite(n):
        return False, "LIDAR arrière non fini", None

    if n <= BACK_MIN_CM:
        return False, f"LIDAR arrière bloqué {n:.1f} cm <= {BACK_MIN_CM:.0f} cm", n

    return True, f"LIDAR arrière libre {n:.1f} cm", n


def write_status(data):
    try:
        data["timestamp"] = time.time()
        STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def conditions():
    s = http_json("/wifi_return_status")

    armed = bool(s.get("armed"))
    active = bool(s.get("active"))
    heartbeat_age = float(s.get("heartbeat_age_s") or 0.0)
    last_drive_time = float(s.get("last_drive_time") or 0.0)

    now = time.time()
    drive_age = now - last_drive_time if last_drive_time > 0 else 999999.0

    ap_ok, ap_reason = ap_has_station()
    local_ok, local_reason = local_wifi_connected()
    back_ok, back_reason, back_cm = lidar_back_clear()

    heartbeat_lost = heartbeat_age >= HEARTBEAT_ABSENT_S
    recent_drive = drive_age <= RECENT_DRIVE_WINDOW_S

    both_wifi_lost = (not ap_ok) and (not local_ok)

    ready = (
        armed
        and not active
        and heartbeat_lost
        and both_wifi_lost
        and recent_drive
        and back_ok
    )

    reason_parts = []

    if not armed:
        reason_parts.append("Retour WiFi désarmé")
    if active:
        reason_parts.append("ancien retour déjà actif")
    if not heartbeat_lost:
        reason_parts.append(f"heartbeat présent {heartbeat_age:.1f}s < {HEARTBEAT_ABSENT_S:.0f}s")
    if not both_wifi_lost:
        reason_parts.append("au moins un Wi-Fi encore disponible")
    if not recent_drive:
        reason_parts.append(f"dernière conduite trop ancienne {drive_age:.1f}s > {RECENT_DRIVE_WINDOW_S:.0f}s")
    if not back_ok:
        reason_parts.append(back_reason)

    info = {
        "ok": True,
        "ready_to_return": ready,
        "armed": armed,
        "active": active,
        "heartbeat_age_s": round(heartbeat_age, 1),
        "heartbeat_lost": heartbeat_lost,
        "ap_ok": ap_ok,
        "ap_reason": ap_reason,
        "local_ok": local_ok,
        "local_reason": local_reason,
        "both_wifi_lost": both_wifi_lost,
        "recent_drive": recent_drive,
        "drive_age_s": round(drive_age, 1),
        "back_ok": back_ok,
        "back_cm": back_cm,
        "back_reason": back_reason,
        "reason": " ; ".join(reason_parts) if reason_parts else "conditions complètes",
    }

    write_status(info)
    return ready, info


def do_return_sequence(info):
    global last_trigger_time

    now = time.time()
    if now - last_trigger_time < COOLDOWN_S:
        log("Retour double Wi-Fi ignoré: cooldown actif")
        return

    last_trigger_time = now

    log("=== RETOUR DOUBLE PERTE WI-FI DÉCLENCHÉ ===")
    log(json.dumps(info, ensure_ascii=False))

    stop_motors()
    time.sleep(0.5)

    for pulse in range(1, MAX_PULSES + 1):
        # Réévaluer avant chaque impulsion
        ap_ok, ap_reason = ap_has_station()
        local_ok, local_reason = local_wifi_connected()
        back_ok, back_reason, back_cm = lidar_back_clear()

        if ap_ok or local_ok:
            log(f"Retour arrêté: Wi-Fi revenu. {ap_reason} ; {local_reason}")
            stop_motors()
            return

        if not back_ok:
            log(f"Retour arrêté: sécurité arrière. {back_reason}")
            stop_motors()
            return

        log(f"Impulsion retour {pulse}/{MAX_PULSES}: {CMD_REVERSE}")
        ok, resp = drive_cmd(CMD_REVERSE)
        if not ok:
            log("ERREUR commande recul: " + resp)
            stop_motors()
            return

        time.sleep(PULSE_S)
        stop_motors()
        time.sleep(STOP_S)

    log("Retour double Wi-Fi terminé: nombre maximal d'impulsions atteint")
    stop_motors()


def main():
    log("RB2 watchdog double perte Wi-Fi démarré")
    stop_motors()

    while True:
        try:
            ready, info = conditions()

            if ready:
                do_return_sequence(info)

        except Exception as e:
            write_status({"ok": False, "error": str(e)})
            log("ERREUR watchdog: " + str(e))
            try:
                stop_motors()
            except Exception:
                pass

        time.sleep(LOOP_S)


if __name__ == "__main__":
    main()
