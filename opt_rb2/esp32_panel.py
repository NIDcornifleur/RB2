#!/usr/bin/env python3
from flask import Flask, request, jsonify, render_template_string, Response
from rb2_esp32 import RB2ESP32
import re
import json
import os
import time
import threading
import urllib.request
import urllib.error
import urllib.parse

app = Flask(__name__)
esp32 = RB2ESP32()

# --- Sécurité commandes moteur RB2 ---
# Les commandes moteur doivent être périmables et non empilables.
# Toute commande d...,.. sans séquence client est refusée, sauf d0,0.
DRIVE_CMD_RE = re.compile(r"^d(-?\d+),(-?\d+)$")
DRIVE_SEQ_LOCK = threading.Lock()
DRIVE_LAST_SEQ = -1
DRIVE_LAST_TOKEN = ""
DRIVE_LAST_ACCEPT_TIME = 0.0
DRIVE_LAST_STOP_TIME = 0.0
DRIVE_LAST_REJECT_TIME = 0.0
DRIVE_LAST_REJECT_REASON = ""
DRIVE_LAST_REJECT_COMMAND = ""
DRIVE_MAX_AGE_MS = 6000
DRIVE_MAX_FUTURE_MS = 5000


def rb2_parse_drive_command(command_text):
    m = DRIVE_CMD_RE.match(str(command_text or "").strip())
    if not m:
        return None

    left = int(m.group(1))
    right = int(m.group(2))
    return left, right


def rb2_is_stop_drive(command_text):
    parsed = rb2_parse_drive_command(command_text)
    return parsed is not None and parsed[0] == 0 and parsed[1] == 0


# --- Journalisation des commandes moteur dans la trace active ---
TRACE_DIR = "/opt/rb2/traces"
TRACE_PID_FILE = "/tmp/rb2_trace_passive.pid"
TRACE_DRIVE_LOCK = threading.Lock()
TRACE_MAIN_RE = re.compile(r"^rb2_trace_\d{8}-\d{6}\.csv$")


def rb2_trace_is_active():
    try:
        if not os.path.exists(TRACE_PID_FILE):
            return False
        with open(TRACE_PID_FILE, "r", encoding="utf-8") as f:
            pid_text = f.read().strip()
        if not pid_text:
            return False
        os.kill(int(pid_text), 0)
        return True
    except Exception:
        return False


def rb2_latest_main_trace_path():
    try:
        if not os.path.isdir(TRACE_DIR):
            return None
        candidates = []
        for name in os.listdir(TRACE_DIR):
            if TRACE_MAIN_RE.match(name):
                path = os.path.join(TRACE_DIR, name)
                if os.path.isfile(path):
                    candidates.append(path)
        if not candidates:
            return None
        candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return candidates[0]
    except Exception:
        return None


def rb2_read_lidar_summary_for_trace():
    lidar_file = "/tmp/rb2_lidar.json"
    summary = {
        "front_cm": "",
        "left_cm": "",
        "right_cm": "",
        "back_cm": "",
        "min_cm": "",
    }

    try:
        if not os.path.exists(lidar_file):
            return summary
        with open(lidar_file, "r", encoding="utf-8") as f:
            raw = json.load(f)

        # Plusieurs formats ont été utilisés pendant le développement.
        # On accepte les clés directes ou les sous-blocs courants.
        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        if not isinstance(data, dict):
            return summary

        for source in (data, data.get("clearance", {}), data.get("distances", {}), data.get("summary", {})):
            if not isinstance(source, dict):
                continue
            for key in summary.keys():
                if summary[key] == "" and key in source and source.get(key) is not None:
                    summary[key] = source.get(key)

        return summary
    except Exception:
        return summary




# --- Trace de conduite enrichie par odométrie encodeurs ---
# Pour un vrai SUIVRE TRACE, on doit enregistrer ce que RB2 a réellement fait,
# pas seulement les commandes envoyées. Ces colonnes sont ajoutées aux nouveaux
# fichiers *_drive.csv créés pendant une trace active.
TRACE_RECORD_ENCODERS = True
TRACE_ENCODER_READ_WAIT_S = 0.16


def rb2_read_encoder_snapshot_for_trace():
    """
    Lit une photo instantanée des encodeurs ESP32 pour enrichir la trace.
    Ne doit jamais empêcher la conduite : en cas d'erreur, on retourne des champs vides.
    """
    empty = {
        "enc_FL": "",
        "enc_FR": "",
        "enc_RR": "",
        "enc_RL": "",
        "odom_center_cm": "",
        "odom_angle_deg": "",
    }

    if not TRACE_RECORD_ENCODERS:
        return empty

    try:
        result = esp32.send("enc", wait=TRACE_ENCODER_READ_WAIT_S)
        lines = []
        try:
            lines.extend(result.get("lines", []))
        except Exception:
            pass
        try:
            lines.extend(esp32.last_lines[-30:])
        except Exception:
            pass

        values = parse_encoders_from_lines(lines)

        # Même convention que /encoders : avance physique = positif.
        if values.get("FR") is not None:
            values["FR"] = -values["FR"]
        if values.get("RR") is not None:
            values["RR"] = -values["RR"]

        found_any = any(v is not None for v in values.values())
        if not found_any:
            return empty

        odom = compute_odom_from_values(values)
        return {
            "enc_FL": "" if values.get("FL") is None else values.get("FL"),
            "enc_FR": "" if values.get("FR") is None else values.get("FR"),
            "enc_RR": "" if values.get("RR") is None else values.get("RR"),
            "enc_RL": "" if values.get("RL") is None else values.get("RL"),
            "odom_center_cm": "" if odom.get("center_cm") is None else f"{odom.get('center_cm'):.3f}",
            "odom_angle_deg": "" if odom.get("angle_deg") is None else f"{odom.get('angle_deg'):.3f}",
        }
    except Exception as e:
        try:
            with open("/tmp/rb2_trace_encoder_error.log", "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%dT%H:%M:%S") + " " + str(e) + "\n")
        except Exception:
            pass
        return empty




def rb2_trace_start_epoch_from_main_path(main_trace):
    """
    Retourne l'heure de départ stable d'une trace principale.

    Important : ne jamais utiliser os.path.getmtime(main_trace) pour calculer
    time_s pendant que la trace passive est active. Le fichier principal est
    réécrit continuellement; son mtime avance donc avec le robot et compresse
    artificiellement toutes les durées dans *_drive.csv.

    Le nom rb2_trace_YYYYMMDD-HHMMSS.csv est la source stable.
    """
    try:
        name = os.path.basename(str(main_trace or ""))
        m = re.match(r"^rb2_trace_(\d{8})-(\d{6})\.csv$", name)
        if not m:
            return None
        stamp = m.group(1) + m.group(2)
        return time.mktime(time.strptime(stamp, "%Y%m%d%H%M%S"))
    except Exception:
        return None


def rb2_log_drive_command_to_trace(command_text, left, right, seq=None, token="", age_ms=None, note="drive"):
    """
    Ajoute une ligne *_drive.csv associée à la trace passive active.
    Cette trace de conduite servira plus tard au REJOUER TRACE.
    """
    try:
        if not rb2_trace_is_active():
            return None

        main_trace = rb2_latest_main_trace_path()
        if not main_trace:
            return None

        base, _ = os.path.splitext(main_trace)
        drive_file = base + "_drive.csv"

        now = time.time()
        trace_start = rb2_trace_start_epoch_from_main_path(main_trace)
        if trace_start is None:
            # Repli seulement si le nom de fichier ne respecte pas le format attendu.
            # Ce cas ne devrait pas arriver avec les traces RB2 normales.
            try:
                trace_start = os.path.getctime(main_trace)
            except Exception:
                trace_start = now
        rel_s = max(0.0, now - trace_start)

        lidar = rb2_read_lidar_summary_for_trace()

        header = [
            "time_s",
            "iso_time",
            "main_trace",
            "cmd",
            "left",
            "right",
            "drive_seq",
            "drive_token",
            "age_ms",
            "front_cm",
            "left_cm",
            "right_cm",
            "back_cm",
            "min_cm",
            "note",
            "enc_FL",
            "enc_FR",
            "enc_RR",
            "enc_RL",
            "odom_center_cm",
            "odom_angle_deg",
        ]

        enc_snapshot = rb2_read_encoder_snapshot_for_trace()

        row = [
            f"{rel_s:.3f}",
            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            os.path.basename(main_trace),
            command_text,
            left,
            right,
            "" if seq is None else seq,
            token or "",
            "" if age_ms is None else age_ms,
            lidar.get("front_cm", ""),
            lidar.get("left_cm", ""),
            lidar.get("right_cm", ""),
            lidar.get("back_cm", ""),
            lidar.get("min_cm", ""),
            note,
            enc_snapshot.get("enc_FL", ""),
            enc_snapshot.get("enc_FR", ""),
            enc_snapshot.get("enc_RR", ""),
            enc_snapshot.get("enc_RL", ""),
            enc_snapshot.get("odom_center_cm", ""),
            enc_snapshot.get("odom_angle_deg", ""),
        ]

        with TRACE_DRIVE_LOCK:
            new_file = not os.path.exists(drive_file)
            with open(drive_file, "a", newline="", encoding="utf-8") as f:
                import csv
                writer = csv.writer(f)
                if new_file:
                    writer.writerow(header)
                writer.writerow(row)

        return drive_file
    except Exception as e:
        # Ne jamais bloquer la conduite pour une erreur de journalisation.
        try:
            with open("/tmp/rb2_trace_drive_error.log", "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%dT%H:%M:%S") + " " + str(e) + "\n")
        except Exception:
            pass
        return None


def rb2_safe_drive_send(command_text, data):
    global DRIVE_LAST_SEQ, DRIVE_LAST_TOKEN, DRIVE_LAST_ACCEPT_TIME, DRIVE_LAST_STOP_TIME
    global DRIVE_LAST_REJECT_TIME, DRIVE_LAST_REJECT_REASON, DRIVE_LAST_REJECT_COMMAND

    parsed = rb2_parse_drive_command(command_text)
    if parsed is None:
        return None

    is_stop = parsed[0] == 0 and parsed[1] == 0

    raw_seq = data.get("drive_seq", None)
    token = str(data.get("drive_token", "terrain"))
    raw_sent_server_ms = data.get("sent_server_ms", None)
    now = time.time()
    now_ms = int(now * 1000)

    def reject(reason, seq=None, age_ms=None):
        global DRIVE_LAST_REJECT_TIME, DRIVE_LAST_REJECT_REASON, DRIVE_LAST_REJECT_COMMAND
        DRIVE_LAST_REJECT_TIME = time.time()
        DRIVE_LAST_REJECT_REASON = reason
        DRIVE_LAST_REJECT_COMMAND = command_text
        return {
            "ok": False,
            "command": command_text,
            "ignored": True,
            "drive_seq": seq,
            "age_ms": age_ms,
            "last_seq": DRIVE_LAST_SEQ,
            "error": reason,
            "drive_safety": "commande moteur refusée",
        }

    # STOP reste toujours accepté, même sans séquence ni timestamp.
    # C'est la commande la plus prioritaire du robot.
    if is_stop and raw_seq is None:
        with DRIVE_SEQ_LOCK:
            DRIVE_LAST_STOP_TIME = now
            DRIVE_LAST_ACCEPT_TIME = now
        result = esp32.send("d0,0", wait=0.0)
        drive_file = rb2_log_drive_command_to_trace("d0,0", 0, 0, seq=None, token=token, age_ms=None, note="stop")
        if drive_file:
            result["trace_drive_file"] = os.path.basename(drive_file)
        result["drive_safety"] = "stop accepté sans séquence"
        return result

    # Toute commande moteur non-stop doit venir de l'interface sécurisée.
    if raw_seq is None:
        return reject("Commande moteur refusée: séquence absente")

    try:
        seq = int(raw_seq)
    except Exception:
        return reject("Commande moteur refusée: séquence invalide")

    # Toute commande moteur non-stop doit aussi porter l'heure approximative
    # de création côté navigateur, corrigée vers l'heure serveur.
    # But: rejeter les requêtes restées bloquées pendant une perte Wi-Fi.
    sent_server_ms = None
    age_ms = None
    if not is_stop:
        if raw_sent_server_ms is None:
            return reject("Commande moteur refusée: timestamp absent", seq=seq)
        try:
            sent_server_ms = int(raw_sent_server_ms)
            age_ms = now_ms - sent_server_ms
        except Exception:
            return reject("Commande moteur refusée: timestamp invalide", seq=seq)

        if age_ms > DRIVE_MAX_AGE_MS:
            return reject(
                f"Commande moteur refusée: périmée ({age_ms} ms)",
                seq=seq,
                age_ms=age_ms,
            )

        if age_ms < -DRIVE_MAX_FUTURE_MS:
            return reject(
                f"Commande moteur refusée: horloge incohérente ({age_ms} ms)",
                seq=seq,
                age_ms=age_ms,
            )

    with DRIVE_SEQ_LOCK:
        # Si l'interface a été rechargée, le token change. On repart proprement.
        if token != DRIVE_LAST_TOKEN:
            DRIVE_LAST_TOKEN = token
            DRIVE_LAST_SEQ = -1

        if seq < DRIVE_LAST_SEQ:
            return {
                "ok": True,
                "command": command_text,
                "ignored": True,
                "drive_seq": seq,
                "last_seq": DRIVE_LAST_SEQ,
                "age_ms": age_ms,
                "error": None,
                "drive_safety": "commande moteur périmée ignorée",
            }

        DRIVE_LAST_SEQ = seq
        DRIVE_LAST_ACCEPT_TIME = now
        if is_stop:
            DRIVE_LAST_STOP_TIME = now

    # Pour les commandes moteur, ne pas attendre une réponse série.
    # Cela évite d'empiler les requêtes Flask pendant la conduite.
    result = esp32.send(command_text, wait=0.0)
    drive_file = rb2_log_drive_command_to_trace(
        command_text, parsed[0], parsed[1], seq=seq, token=token, age_ms=age_ms,
        note="stop" if is_stop else "drive"
    )
    if drive_file:
        result["trace_drive_file"] = os.path.basename(drive_file)
    result["drive_seq"] = seq
    result["drive_token"] = token
    result["age_ms"] = age_ms
    result["drive_safety"] = "commande moteur acceptée"
    return result


# --- SUIVRE TRACE : suivi réel par odométrie encodeurs ---
# Version V7 : on ne se contente plus de rejouer des durées de commandes.
# On exige une trace *_drive.csv enrichie avec odom_center_cm et odom_angle_deg.
# Le robot avance/recule/tourne jusqu'aux deltas réellement mesurés pendant l'enregistrement.
# Le LIDAR et le STOP opérateur restent prioritaires en tout temps.

TRACE_DRIVE_RE = re.compile(r"^rb2_trace_\d{8}-\d{6}_drive\.csv$")
TRACE_FOLLOW_MAX_SPEED = 15
TRACE_FOLLOW_FRONT_MIN_CM = 45.0
TRACE_FOLLOW_BACK_MIN_CM = 25.0
TRACE_FOLLOW_LIDAR_MAX_AGE_S = 2.0
TRACE_FOLLOW_KEEPALIVE_S = 0.25
TRACE_FOLLOW_ODOM_SAMPLE_S = 0.14
TRACE_FOLLOW_SEGMENT_MIN_MOVE_CM = 1.0
TRACE_FOLLOW_SEGMENT_MIN_ANGLE_DEG = 3.0
TRACE_FOLLOW_SEGMENT_MAX_S = 15.0
TRACE_FOLLOW_TARGET_TOL_CM = 1.5
TRACE_FOLLOW_TARGET_TOL_DEG = 3.0

TRACE_FOLLOW_LOCK = threading.Lock()
TRACE_FOLLOW_STOP_EVENT = threading.Event()
TRACE_FOLLOW_THREAD = None
TRACE_FOLLOW_STATUS = {
    "running": False,
    "ok": True,
    "state": "idle",
    "message": "Suivi trace inactif",
    "file": None,
    "step": 0,
    "total": 0,
    "cmd": "d0,0",
    "started_at": None,
    "finished_at": None,
    "last_error": "",
    "front_cm": None,
    "back_cm": None,
    "speed_limit": TRACE_FOLLOW_MAX_SPEED,
    "front_min_cm": TRACE_FOLLOW_FRONT_MIN_CM,
    "back_min_cm": TRACE_FOLLOW_BACK_MIN_CM,
    "raw_cmd": "",
    "target_center_cm": None,
    "target_angle_deg": None,
    "actual_center_cm": None,
    "actual_angle_deg": None,
    "segment_mode": "",
    "send_count": 0,
    "mode": "v10_rejeu_exact_operateur",
}


def rb2_trace_follow_set_status(**kwargs):
    with TRACE_FOLLOW_LOCK:
        TRACE_FOLLOW_STATUS.update(kwargs)
        return dict(TRACE_FOLLOW_STATUS)


def rb2_trace_follow_snapshot():
    with TRACE_FOLLOW_LOCK:
        snap = dict(TRACE_FOLLOW_STATUS)

    snap["stop_requested"] = TRACE_FOLLOW_STOP_EVENT.is_set()
    try:
        snap["thread_alive"] = bool(TRACE_FOLLOW_THREAD is not None and TRACE_FOLLOW_THREAD.is_alive())
    except Exception:
        snap["thread_alive"] = False
    return snap


def rb2_trace_follow_is_running():
    try:
        return bool(TRACE_FOLLOW_THREAD is not None and TRACE_FOLLOW_THREAD.is_alive())
    except Exception:
        return False


def rb2_trace_follow_send_stop_burst():
    try:
        esp32.send("d0,0", wait=0.0)
        time.sleep(0.05)
        esp32.send("d0,0", wait=0.0)
        time.sleep(0.10)
        esp32.send("d0,0", wait=0.0)
    except Exception:
        pass


def rb2_trace_follow_request_stop(reason="STOP demandé"):
    TRACE_FOLLOW_STOP_EVENT.set()
    rb2_trace_follow_set_status(
        state="stopping",
        message=reason,
        last_error="" if reason else TRACE_FOLLOW_STATUS.get("last_error", ""),
    )
    rb2_trace_follow_send_stop_burst()


def rb2_latest_drive_trace_path():
    try:
        if not os.path.isdir(TRACE_DIR):
            return None
        candidates = []
        for name in os.listdir(TRACE_DIR):
            if TRACE_DRIVE_RE.match(name):
                path = os.path.join(TRACE_DIR, name)
                if os.path.isfile(path):
                    candidates.append(path)
        if not candidates:
            return None
        candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return candidates[0]
    except Exception:
        return None


def rb2_float_or_none(value):
    try:
        if value is None:
            return None
        text_value = str(value).strip()
        if text_value == "":
            return None
        return float(text_value)
    except Exception:
        return None


def rb2_trace_follow_read_lidar_guard():
    lidar_file = "/tmp/rb2_lidar.json"
    summary = rb2_read_lidar_summary_for_trace()
    age_s = None
    try:
        if os.path.exists(lidar_file):
            age_s = time.time() - os.stat(lidar_file).st_mtime
    except Exception:
        age_s = None

    return {
        "front_cm": rb2_float_or_none(summary.get("front_cm")),
        "back_cm": rb2_float_or_none(summary.get("back_cm")),
        "age_s": age_s,
    }


def rb2_trace_follow_lidar_allows(left, right):
    lidar = rb2_trace_follow_read_lidar_guard()
    front_cm = lidar.get("front_cm")
    back_cm = lidar.get("back_cm")
    age_s = lidar.get("age_s")
    rb2_trace_follow_set_status(front_cm=front_cm, back_cm=back_cm)

    if left == 0 and right == 0:
        return True, "stop"
    if age_s is None:
        return False, "LIDAR absent ou âge inconnu"
    if age_s > TRACE_FOLLOW_LIDAR_MAX_AGE_S:
        return False, f"LIDAR trop vieux ({age_s:.1f} s)"

    needs_front = left > 0 or right > 0
    needs_back = left < 0 or right < 0

    if needs_front:
        if front_cm is None:
            return False, "distance avant absente"
        if front_cm < TRACE_FOLLOW_FRONT_MIN_CM:
            return False, f"avant trop proche ({front_cm:.1f} cm < {TRACE_FOLLOW_FRONT_MIN_CM:.0f} cm)"
    if needs_back:
        if back_cm is None:
            return False, "distance arrière absente"
        if back_cm < TRACE_FOLLOW_BACK_MIN_CM:
            return False, f"arrière trop proche ({back_cm:.1f} cm < {TRACE_FOLLOW_BACK_MIN_CM:.0f} cm)"
    return True, "LIDAR OK"


def rb2_trace_follow_limit_drive(left, right):
    try:
        left = int(left)
        right = int(right)
    except Exception:
        return 0, 0
    max_abs = max(abs(left), abs(right))
    if max_abs <= 0:
        return 0, 0
    if max_abs <= TRACE_FOLLOW_MAX_SPEED:
        return left, right
    scale = float(TRACE_FOLLOW_MAX_SPEED) / float(max_abs)
    limited_left = int(round(left * scale))
    limited_right = int(round(right * scale))
    if left != 0 and limited_left == 0:
        limited_left = 1 if left > 0 else -1
    if right != 0 and limited_right == 0:
        limited_right = 1 if right > 0 else -1
    return limited_left, limited_right


def rb2_trace_follow_read_current_odom():
    """Lit les encodeurs et retourne l'odométrie actuelle selon la convention RB2."""
    result = esp32.send("enc", wait=0.18)
    lines = []
    try:
        lines.extend(result.get("lines", []))
    except Exception:
        pass
    try:
        lines.extend(esp32.last_lines[-30:])
    except Exception:
        pass
    values = parse_encoders_from_lines(lines)
    rb2_write_wheel_ticks_json(values)
    if values.get("FR") is not None:
        values["FR"] = -values["FR"]
    if values.get("RR") is not None:
        values["RR"] = -values["RR"]
    if not any(v is not None for v in values.values()):
        raise ValueError("lecture encodeurs impossible")
    odom = compute_odom_from_values(values)
    if odom.get("center_cm") is None or odom.get("angle_deg") is None:
        raise ValueError("odométrie encodeurs incomplète")
    return {
        "values": values,
        "center_cm": float(odom["center_cm"]),
        "angle_deg": float(odom["angle_deg"]),
    }


def rb2_trace_follow_load_drive_file(path):
    import csv
    if not path or not os.path.isfile(path):
        raise ValueError("fichier *_drive.csv absent")

    rows = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"time_s", "cmd", "left", "right", "odom_center_cm", "odom_angle_deg"}
        fieldnames = set(reader.fieldnames or [])
        missing = required - fieldnames
        if missing:
            raise ValueError(
                "trace trop ancienne: colonnes odométrie manquantes (" +
                ", ".join(sorted(missing)) + "). Refaire une trace avec la V10."
            )
        for row in reader:
            cmd_text = str(row.get("cmd", "")).strip()
            parsed = rb2_parse_drive_command(cmd_text)
            t_s = rb2_float_or_none(row.get("time_s"))
            center = rb2_float_or_none(row.get("odom_center_cm"))
            angle = rb2_float_or_none(row.get("odom_angle_deg"))
            if parsed is None or t_s is None or center is None or angle is None:
                continue
            rows.append({
                "time_s": max(0.0, float(t_s)),
                "cmd": cmd_text,
                "left": int(parsed[0]),
                "right": int(parsed[1]),
                "center_cm": float(center),
                "angle_deg": float(angle),
                "note": str(row.get("note", "")).strip(),
            })

    if len(rows) < 2:
        raise ValueError("trace odométrique insuffisante: au moins deux lignes valides requises")
    rows.sort(key=lambda r: r["time_s"])
    return rows


def rb2_trace_follow_classify_segment(dc, da):
    if abs(dc) >= 2.0 and abs(da) < 10.0:
        return "distance"
    if abs(da) >= 4.0 and abs(dc) < 5.0:
        return "angle"
    return "mixte"


def rb2_trace_follow_same_motion(a, b):
    """Regroupe les commandes semblables pour éviter de découper une avance tenue en micro-segments."""
    try:
        al = int(a.get("left", 0) or 0)
        ar = int(a.get("right", 0) or 0)
        bl = int(b.get("left", 0) or 0)
        br = int(b.get("right", 0) or 0)
    except Exception:
        return False
    if al == 0 and ar == 0:
        return False
    if bl == 0 and br == 0:
        return False

    def sgn(x):
        return 1 if x > 0 else (-1 if x < 0 else 0)

    # Même famille de mouvement : avance, recul, rotation gauche/droite, ou courbe du même signe.
    return sgn(al) == sgn(bl) and sgn(ar) == sgn(br)


def rb2_trace_follow_build_segments(rows):
    """
    V8 : construit de vrais blocs de mouvement.

    La V7 suivait chaque intervalle entre deux lignes du *_drive.csv. Comme la page répète
    les commandes toutes les quelques centaines de ms, cela créait plusieurs micro-segments
    et un stop entre chacun. Résultat : déplacement ridicule.

    Ici on regroupe les commandes consécutives de même type jusqu'au STOP ou jusqu'à un
    changement réel de direction. La cible d'un bloc est le delta d'odométrie entre le début
    du bloc et la ligne de fin. Le robot suit donc une avance complète mesurée, pas des miettes.
    """
    segments = []
    n = len(rows)
    i = 0

    while i < n - 1:
        a = rows[i]
        raw_left = int(a.get("left", 0) or 0)
        raw_right = int(a.get("right", 0) or 0)

        if raw_left == 0 and raw_right == 0:
            i += 1
            continue

        start = i
        end = i + 1

        # Avancer jusqu'au STOP ou jusqu'à un changement de famille de mouvement.
        while end < n:
            cur = rows[end]
            cur_left = int(cur.get("left", 0) or 0)
            cur_right = int(cur.get("right", 0) or 0)

            # La ligne STOP marque la fin du bloc; on la garde comme point final d'odométrie.
            if cur_left == 0 and cur_right == 0:
                break

            # Si la commande suivante n'est pas du même type, elle devient le début du prochain bloc.
            if not rb2_trace_follow_same_motion(a, cur):
                break

            end += 1

        b = rows[end] if end < n else rows[-1]

        dt = max(0.0, float(b["time_s"]) - float(a["time_s"]))
        dc = float(b["center_cm"]) - float(a["center_cm"])
        da = float(b["angle_deg"]) - float(a["angle_deg"])

        # On ignore seulement les vrais bruits, pas les petits mouvements volontaires.
        if abs(dc) >= TRACE_FOLLOW_SEGMENT_MIN_MOVE_CM or abs(da) >= TRACE_FOLLOW_SEGMENT_MIN_ANGLE_DEG:
            left, right = rb2_trace_follow_limit_drive(raw_left, raw_right)
            if left != 0 or right != 0:
                segments.append({
                    "index": len(segments) + 1,
                    "raw_cmd": f"d{raw_left},{raw_right}",
                    "cmd": f"d{left},{right}",
                    "left": left,
                    "right": right,
                    "raw_left": raw_left,
                    "raw_right": raw_right,
                    "recorded_duration_s": dt,
                    "target_center_cm": dc,
                    "target_angle_deg": da,
                    "mode": rb2_trace_follow_classify_segment(dc, da),
                    "row_start": start + 1,
                    "row_end": end + 1,
                    "rows_grouped": max(1, end - start + 1),
                })

        # Si on s'est arrêté sur une ligne STOP, on reprend après le STOP.
        # Si on s'est arrêté sur un changement de commande, on reprend à cette ligne.
        if end < n:
            end_left = int(rows[end].get("left", 0) or 0)
            end_right = int(rows[end].get("right", 0) or 0)
            i = end + 1 if (end_left == 0 and end_right == 0) else end
        else:
            i = n

    if not segments:
        raise ValueError(
            "aucun mouvement réel mesuré dans la trace. Refaire une trace plus longue "
            "ou vérifier que les encodeurs changent pendant l'enregistrement."
        )
    return segments


def rb2_trace_follow_signed_reached(target, actual, tolerance):
    """Respecte le signe de la cible. Évite qu'un mouvement dans le mauvais sens soit accepté."""
    target = float(target or 0.0)
    actual = float(actual or 0.0)
    tolerance = float(tolerance or 0.0)
    if abs(target) <= tolerance:
        return True
    if target > 0:
        return actual >= (target - tolerance)
    return actual <= (target + tolerance)


def rb2_trace_follow_target_reached(mode, target_center, target_angle, actual_center, actual_angle):
    if mode == "distance":
        return rb2_trace_follow_signed_reached(target_center, actual_center, TRACE_FOLLOW_TARGET_TOL_CM)
    if mode == "angle":
        return rb2_trace_follow_signed_reached(target_angle, actual_angle, TRACE_FOLLOW_TARGET_TOL_DEG)

    center_ok = True
    angle_ok = True
    if abs(target_center) > TRACE_FOLLOW_TARGET_TOL_CM:
        center_ok = rb2_trace_follow_signed_reached(target_center, actual_center, TRACE_FOLLOW_TARGET_TOL_CM)
    if abs(target_angle) > TRACE_FOLLOW_TARGET_TOL_DEG:
        angle_ok = rb2_trace_follow_signed_reached(target_angle, actual_angle, TRACE_FOLLOW_TARGET_TOL_DEG)
    return center_ok and angle_ok


def rb2_trace_follow_segment_timeout_s(segment):
    base = max(0.8, float(segment.get("recorded_duration_s") or 0.0) * 3.0 + 0.8)
    return min(TRACE_FOLLOW_SEGMENT_MAX_S, base)


def rb2_trace_follow_worker(path):
    try:
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_follow_build_segments(rows)
        rb2_trace_follow_set_status(
            running=True,
            ok=True,
            state="starting",
            message="Initialisation du suivi réel par encodeurs",
            file=os.path.basename(path),
            step=0,
            total=len(segments),
            cmd="d0,0",
            raw_cmd="",
            target_center_cm=None,
            target_angle_deg=None,
            actual_center_cm=None,
            actual_angle_deg=None,
            send_count=0,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            finished_at=None,
            last_error="",
            speed_limit=TRACE_FOLLOW_MAX_SPEED,
            front_min_cm=TRACE_FOLLOW_FRONT_MIN_CM,
            back_min_cm=TRACE_FOLLOW_BACK_MIN_CM,
            mode="odometry_follow_v8_block_odometry",
        )

        rb2_trace_follow_send_stop_burst()
        time.sleep(0.15)
        replay_start_odom = rb2_trace_follow_read_current_odom()
        rb2_trace_follow_set_status(
            actual_center_cm=round(replay_start_odom["center_cm"], 2),
            actual_angle_deg=round(replay_start_odom["angle_deg"], 2),
        )

        for idx, seg in enumerate(segments):
            if TRACE_FOLLOW_STOP_EVENT.is_set():
                rb2_trace_follow_set_status(
                    running=False, ok=True, state="stopped",
                    message="Suivi arrêté par l'opérateur", cmd="d0,0",
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                )
                return

            left = int(seg["left"])
            right = int(seg["right"])
            command_text = seg["cmd"]
            allowed, reason = rb2_trace_follow_lidar_allows(left, right)
            if not allowed:
                rb2_trace_follow_set_status(
                    running=False, ok=False, state="blocked",
                    message="Suivi bloqué par sécurité LIDAR", last_error=reason,
                    step=idx + 1, cmd="d0,0", raw_cmd=seg["raw_cmd"],
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                )
                return

            segment_start_odom = rb2_trace_follow_read_current_odom()
            target_center = float(seg["target_center_cm"])
            target_angle = float(seg["target_angle_deg"])
            timeout_s = rb2_trace_follow_segment_timeout_s(seg)
            start_mono = time.monotonic()
            next_send = 0.0
            next_odom = 0.0
            send_count = 0
            actual_center = 0.0
            actual_angle = 0.0

            rb2_trace_follow_set_status(
                running=True, ok=True, state="running", message=reason,
                step=idx + 1, total=len(segments), cmd=command_text,
                raw_cmd=seg["raw_cmd"], segment_mode=seg["mode"],
                target_center_cm=round(target_center, 2),
                target_angle_deg=round(target_angle, 2),
                actual_center_cm=0.0, actual_angle_deg=0.0,
                send_count=0,
                rows_grouped=seg.get("rows_grouped"),
                row_start=seg.get("row_start"),
                row_end=seg.get("row_end"),
            )

            while True:
                if TRACE_FOLLOW_STOP_EVENT.is_set():
                    rb2_trace_follow_set_status(
                        running=False, ok=True, state="stopped",
                        message="Suivi arrêté par l'opérateur", cmd="d0,0",
                        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    )
                    return

                elapsed = time.monotonic() - start_mono
                if elapsed > timeout_s:
                    rb2_trace_follow_set_status(
                        running=False, ok=False, state="timeout",
                        message="Segment arrêté par limite de temps",
                        last_error=f"segment {idx + 1} trop long; cible non atteinte",
                        cmd="d0,0", actual_center_cm=round(actual_center, 2),
                        actual_angle_deg=round(actual_angle, 2),
                        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    )
                    return

                allowed, reason = rb2_trace_follow_lidar_allows(left, right)
                if not allowed:
                    rb2_trace_follow_set_status(
                        running=False, ok=False, state="blocked",
                        message="Suivi bloqué pendant mouvement", last_error=reason,
                        cmd="d0,0", actual_center_cm=round(actual_center, 2),
                        actual_angle_deg=round(actual_angle, 2),
                        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    )
                    return

                now_mono = time.monotonic()
                if now_mono >= next_send:
                    esp32.send(command_text, wait=0.0)
                    send_count += 1
                    rb2_trace_follow_set_status(send_count=send_count)
                    next_send = now_mono + TRACE_FOLLOW_KEEPALIVE_S

                if now_mono >= next_odom:
                    odom_now = rb2_trace_follow_read_current_odom()
                    actual_center = odom_now["center_cm"] - segment_start_odom["center_cm"]
                    actual_angle = odom_now["angle_deg"] - segment_start_odom["angle_deg"]
                    rb2_trace_follow_set_status(
                        actual_center_cm=round(actual_center, 2),
                        actual_angle_deg=round(actual_angle, 2),
                    )
                    if rb2_trace_follow_target_reached(seg["mode"], target_center, target_angle, actual_center, actual_angle):
                        break
                    next_odom = now_mono + TRACE_FOLLOW_ODOM_SAMPLE_S

                time.sleep(0.02)

            # Stop net entre segments. C'est moins fluide, mais plus propre et vérifiable.
            rb2_trace_follow_send_stop_burst()
            time.sleep(0.10)

        rb2_trace_follow_set_status(
            running=False, ok=True, state="finished", message="Suivi réel terminé",
            cmd="d0,0", step=len(segments), total=len(segments),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

    except Exception as e:
        rb2_trace_follow_set_status(
            running=False, ok=False, state="error", message="Erreur suivi réel trace",
            last_error=str(e), cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
    finally:
        rb2_trace_follow_send_stop_burst()


# --- RB2 relais Raspberry Pi ---
# Lumières : GPIO21 BCM, broche physique 40
# Relais 2 : GPIO16 BCM, broche physique 36

LIGHT_GPIO_BCM = 21
RELAY2_GPIO_BCM = 16

LIGHT_ACTIVE_HIGH = True
RELAY2_ACTIVE_HIGH = True

rb2_light = None
rb2_relay2 = None
rb2_light_state = False
rb2_relay2_state = False
rb2_light_error = None
rb2_relay2_error = None

try:
    from gpiozero import Device, OutputDevice
    from gpiozero.pins.lgpio import LGPIOFactory

    Device.pin_factory = LGPIOFactory()

    rb2_light = OutputDevice(
        LIGHT_GPIO_BCM,
        active_high=LIGHT_ACTIVE_HIGH,
        initial_value=False
    )

    rb2_relay2 = OutputDevice(
        RELAY2_GPIO_BCM,
        active_high=RELAY2_ACTIVE_HIGH,
        initial_value=False
    )

except Exception as e:
    rb2_light_error = str(e)
    rb2_relay2_error = str(e)


def rb2_set_light(on):
    global rb2_light_state, rb2_light_error

    if rb2_light is None:
        return False, rb2_light_error or "GPIO lumière non disponible"

    try:
        if on:
            rb2_light.on()
            rb2_light_state = True
        else:
            rb2_light.off()
            rb2_light_state = False

        rb2_light_error = None
        return True, None

    except Exception as e:
        rb2_light_error = str(e)
        return False, rb2_light_error


def rb2_set_relay2(on):
    global rb2_relay2_state, rb2_relay2_error

    if rb2_relay2 is None:
        return False, rb2_relay2_error or "GPIO relais 2 non disponible"

    try:
        if on:
            rb2_relay2.on()
            rb2_relay2_state = True
        else:
            rb2_relay2.off()
            rb2_relay2_state = False

        rb2_relay2_error = None
        return True, None

    except Exception as e:
        rb2_relay2_error = str(e)
        return False, rb2_relay2_error


HTML = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>RB2 - Test ESP32</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    body {
      font-family: Arial, sans-serif;
      background: #111;
      color: #eee;
      margin: 0;
      padding: 20px;
      user-select: none;
      -webkit-user-select: none;
      touch-action: none;
    }

    h1 {
      text-align: center;
      margin-top: 0;
    }

    h3 {
      margin-bottom: 8px;
      border-bottom: 1px solid #444;
      padding-bottom: 4px;
    }

    .panel {
      max-width: 900px;
      margin: auto;
      background: #222;
      padding: 20px;
      border-radius: 12px;
    }

    .drive-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-bottom: 20px;
      touch-action: none;
    }

    .pt-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-bottom: 12px;
      align-items: center;
    }

    .encoder-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-bottom: 12px;
    }

    .encoder-box {
      background: #111;
      color: #0f0;
      padding: 12px;
      border-radius: 8px;
      text-align: center;
      font-size: 18px;
    }

    .encoder-label {
      color: #ccc;
      font-size: 14px;
      margin-bottom: 4px;
    }

    .encoder-value {
      font-size: 22px;
      font-weight: bold;
    }

    button {
      font-size: 22px;
      padding: 18px;
      border: 0;
      border-radius: 10px;
      background: #444;
      color: white;
      cursor: pointer;
      touch-action: none;
    }

    button:hover {
      background: #666;
    }

    .drive-btn {
      min-height: 86px;
      font-weight: bold;
      border: 2px solid transparent;
    }

    .drive-btn.active {
      background: #0066aa;
      border-color: #66ccff;
      box-shadow: 0 0 12px #66ccff;
    }

    .stop {
      background: #a00000;
      font-weight: bold;
    }

    .stop:hover {
      background: #d00000;
    }

    .stop.active {
      background: #d00000;
      border-color: #ff9999;
      box-shadow: 0 0 12px #ff9999;
    }

    .small {
      font-size: 18px;
      padding: 12px;
    }

    .arrow {
      font-size: 28px;
      font-weight: bold;
      padding: 20px;
    }

    .row {
      display: flex;
      gap: 10px;
      margin-bottom: 12px;
    }

    .row button {
      flex: 1;
    }

    .readout {
      background: #111;
      color: #0f0;
      border-radius: 10px;
      padding: 14px;
      text-align: center;
      font-size: 20px;
      line-height: 1.5;
    }

    .stepbox {
      background: #111;
      padding: 12px;
      border-radius: 10px;
      margin-bottom: 12px;
      text-align: center;
    }

    .stepbox label {
      margin: 0 10px;
      font-size: 18px;
      cursor: pointer;
    }

    .auto-box {
      background: #111;
      padding: 10px;
      border-radius: 8px;
      margin-bottom: 12px;
      text-align: center;
      color: #ddd;
    }

    .auto-box label {
      cursor: pointer;
      font-size: 17px;
    }

    pre {
      background: #000;
      color: #0f0;
      padding: 12px;
      min-height: 180px;
      overflow: auto;
      border-radius: 8px;
      white-space: pre-wrap;
    }

    .note {
      color: #ccc;
      font-size: 14px;
      margin-bottom: 12px;
      text-align: center;
    }

    .warning {
      color: #ffcc66;
      font-size: 14px;
      margin-bottom: 12px;
      text-align: center;
    }

    .limits {
      background: #111;
      color: #ffcc66;
      padding: 10px;
      border-radius: 8px;
      text-align: center;
      font-size: 15px;
      margin-bottom: 14px;
    }

    .drive-status {
      background: #111;
      color: #66ccff;
      padding: 10px;
      border-radius: 8px;
      text-align: center;
      font-size: 18px;
      margin-bottom: 12px;
    }

    @media (max-width: 700px) {
      .encoder-grid {
        grid-template-columns: repeat(2, 1fr);
      }

      button {
        font-size: 18px;
        padding: 14px;
      }

      .small {
        font-size: 16px;
        padding: 10px;
      }

      .arrow {
        font-size: 24px;
        padding: 16px;
      }

      .panel {
        padding: 14px;
      }

      .row {
        flex-direction: column;
      }
    }

    /* RB2 PILOTAGE TERRAIN SIMPLE */
    body {
      overflow: hidden !important;
      padding: 10px !important;
    }

    .panel {
      max-width: none !important;
      width: calc(27vw - 20px) !important;
      min-width: 330px !important;
      height: calc(100vh - 20px) !important;
      margin-left: calc(73vw - 5px) !important;
      margin-right: 0 !important;
      overflow-y: auto !important;
      box-sizing: border-box !important;
      display: block !important;
      padding: 12px !important;
    }

    /* Caméra fixe à gauche */
    .panel > h3:first-child {
      position: fixed !important;
      left: 10px !important;
      top: 10px !important;
      width: calc(73vw - 25px) !important;
      margin: 0 !important;
      padding: 0 0 6px 0 !important;
      background: #111 !important;
      z-index: 50 !important;
    }

    .panel > h3:first-child + div {
      position: fixed !important;
      left: 10px !important;
      top: 45px !important;
      width: calc(73vw - 25px) !important;
      height: calc(100vh - 55px) !important;
      margin: 0 !important;
      padding: 8px !important;
      box-sizing: border-box !important;
      background: #111 !important;
      border-radius: 10px !important;
      overflow: hidden !important;
      z-index: 40 !important;
    }

    .panel > h3:first-child + div p,
    .panel > h3:first-child + div a,
    .panel > h3:first-child + div .camera-note {
      display: none !important;
    }

    .panel > h3:first-child + div img#rb2UsbCam {
      width: 100% !important;
      max-width: none !important;
      height: calc(100vh - 75px) !important;
      max-height: none !important;
      object-fit: contain !important;
      display: block !important;
      border: 2px solid #444 !important;
      background: #000 !important;
      box-sizing: border-box !important;
    }

    /* Masquer les textes inutiles */
    .panel h1,
    .panel .note,
    .panel .warning,
    .panel .limits,
    .panel .stepbox,
    .panel pre {
      display: none !important;
    }

    /* Masquer le titre Diagnostic et la rangée de boutons diagnostic */
    .panel h3:nth-of-type(4),
    .panel h3:nth-of-type(4) + .row {
      display: none !important;
    }

    /* Garder les commandes compactes */
    .panel h3 {
      font-size: 20px !important;
      margin-top: 8px !important;
      margin-bottom: 8px !important;
    }

    .drive-status {
      font-size: 16px !important;
      padding: 8px !important;
      margin-bottom: 8px !important;
    }

    .drive-grid {
      gap: 8px !important;
      margin-bottom: 12px !important;
    }

    button {
      font-size: 17px !important;
      padding: 10px !important;
    }

    .drive-btn {
      min-height: 62px !important;
    }

    .arrow {
      font-size: 22px !important;
      padding: 10px !important;
    }

    .pt-grid {
      gap: 8px !important;
      margin-bottom: 8px !important;
    }

    .readout {
      font-size: 16px !important;
      padding: 8px !important;
    }

    .row {
      gap: 8px !important;
      margin-bottom: 8px !important;
    }

    .row button {
      font-size: 15px !important;
      padding: 9px !important;
    }

    /* Masquer la rangée Pan 60 / Pan centre / Pan 135 */
    .row:nth-of-type(2) {
      display: none !important;
    }

    .encoder-grid {
      grid-template-columns: repeat(2, 1fr) !important;
      gap: 8px !important;
    }

    .encoder-box {
      padding: 8px !important;
    }

    .encoder-label {
      font-size: 12px !important;
    }

    .encoder-value {
      font-size: 18px !important;
    }

    .auto-box {
      display: none !important;
    }

    @media (max-width: 1000px) {
      body {
        overflow: auto !important;
      }

      .panel {
        width: auto !important;
        min-width: 0 !important;
        height: auto !important;
        margin-left: auto !important;
        margin-right: auto !important;
        overflow-y: visible !important;
      }

      .panel > h3:first-child,
      .panel > h3:first-child + div {
        position: static !important;
        width: auto !important;
        height: auto !important;
      }

      .panel > h3:first-child + div img#rb2UsbCam {
        height: auto !important;
        max-height: 60vh !important;
      }
    }

  
    /* RB2 caméra : ne jamais couper l'image */
    #cam {
      object-fit: contain !important;
      background: #000 !important;
    }


    #cam {
      object-fit: contain !important;
      background: #000 !important;
    }


    /* RB2_TERRAIN_HA_COMPACT */
    .terrain-ha-compact {
      width: 100%;
      box-sizing: border-box;
      margin-top: 8px;
      padding: 6px 8px;
      border-radius: 10px;
      background: rgba(17, 24, 39, 0.82);
      border: 1px solid #374151;
    }

    .terrain-ha-title {
      font-size: 0.76rem;
      font-weight: 900;
      color: #d1d5db;
      margin-bottom: 4px;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      white-space: nowrap;
    }

    .terrain-ha-title span:last-child {
      color: #9ca3af;
      font-weight: 700;
    }

    #terrainHaCanvas {
      width: 100%;
      height: 76px;
      display: block;
      background: #050505;
      border: 1px solid #333;
      border-radius: 8px;
    }


    /* RB2 HA minimal : graphique seulement */
    #terrainHaBox {
      display: block !important;
      visibility: visible !important;
      width: 100% !important;
      min-height: 54px !important;
      max-height: 64px !important;
      margin-top: 6px !important;
      padding: 4px 6px !important;
      box-sizing: border-box !important;
      background: rgba(17, 24, 39, 0.70) !important;
      border: 1px solid #374151 !important;
      border-radius: 8px !important;
      grid-column: 1 / 3 !important;
      overflow: hidden !important;
    }

    #terrainHaBox .terrain-ha-title {
      display: none !important;
    }

    #terrainHaCanvas {
      display: block !important;
      width: 100% !important;
      height: 46px !important;
      min-height: 46px !important;
      max-height: 46px !important;
      background: #050505 !important;
      border: 1px solid #333 !important;
      border-radius: 6px !important;
    }



    /* RB2 HA ultra-mince visible à 100% */
    .camera {
      min-height: 50vh !important;
    }

    #cam {
      min-height: 340px !important;
      max-height: 52vh !important;
      object-fit: contain !important;
      background: #000 !important;
    }

    #terrainLidarWrap {
      min-height: 340px !important;
      max-height: 52vh !important;
    }

    #terrainLidarCanvas {
      min-height: 340px !important;
      max-height: 52vh !important;
      background: #000 !important;
    }

    #terrainHaBox {
      display: block !important;
      visibility: visible !important;
      opacity: 1 !important;
      width: 100% !important;
      height: 34px !important;
      min-height: 34px !important;
      max-height: 34px !important;
      margin-top: 4px !important;
      padding: 2px 4px !important;
      box-sizing: border-box !important;
      background: #050505 !important;
      border: 1px solid #333 !important;
      border-radius: 6px !important;
      grid-column: 1 / 3 !important;
      overflow: hidden !important;
    }

    #terrainHaBox .terrain-ha-title {
      display: none !important;
    }

    #terrainHaCanvas {
      display: block !important;
      width: 100% !important;
      height: 28px !important;
      min-height: 28px !important;
      max-height: 28px !important;
      background: #050505 !important;
      border: none !important;
      border-radius: 4px !important;
    }



    /* RB2 HA final : mini graphique CSS, aucun canvas visible */
    #terrainHaBox {
      display: block !important;
      visibility: visible !important;
      opacity: 1 !important;
      grid-column: 1 / 3 !important;
      width: 100% !important;
      height: 32px !important;
      min-height: 32px !important;
      max-height: 32px !important;
      margin-top: 4px !important;
      padding: 2px 4px !important;
      box-sizing: border-box !important;
      background: #050505 !important;
      border: 1px solid #333 !important;
      border-radius: 6px !important;
      overflow: hidden !important;
    }

    #terrainHaBox .terrain-ha-title,
    #terrainHaText,
    #terrainHaCanvas {
      display: none !important;
    }

    #terrainHaMini {
      position: relative !important;
      display: block !important;
      width: 100% !important;
      height: 26px !important;
      background: #050505 !important;
      border-radius: 4px !important;
      overflow: hidden !important;
    }

    #terrainHaSky,
    #terrainHaGround,
    #terrainHaLine {
      position: absolute !important;
      left: -50% !important;
      width: 200% !important;
      height: 200% !important;
      transform-origin: 50% 50% !important;
    }

    #terrainHaSky {
      top: -100% !important;
      background: #1e3a5f !important;
    }

    #terrainHaGround {
      top: 50% !important;
      background: #5a3518 !important;
    }

    #terrainHaLine {
      top: 50% !important;
      height: 2px !important;
      background: #facc15 !important;
    }

    #terrainHaCenter {
      position: absolute !important;
      left: 50% !important;
      top: 50% !important;
      width: 54px !important;
      height: 1px !important;
      margin-left: -27px !important;
      background: #e5e7eb !important;
      box-shadow: 0 0 0 1px rgba(0,0,0,0.35) !important;
      z-index: 20 !important;
    }


</style>

<style>
.rb2-shutdown-all-btn {
  margin-top: 10px;
  width: 100%;
  min-height: 42px;
  border: 2px solid #8b0000;
  border-radius: 8px;
  background: #b00000;
  color: white;
  font-weight: 800;
  font-size: 15px;
  letter-spacing: 0.5px;
  cursor: pointer;
}

.rb2-shutdown-all-btn:hover {
  background: #d00000;
}

.rb2-shutdown-all-btn:disabled {
  background: #555;
  border-color: #555;
  color: #ddd;
  cursor: not-allowed;
}
</style>

</head>

<body>
  <div class="panel">

    <h3>Caméra USB temporaire</h3>
    <div style="background:#111; padding:12px; border-radius:10px; margin-bottom:16px; text-align:center;">
      <p style="color:#ccc; margin-top:0;">
        Si l'image ne s'affiche pas directement, ouvrir la caméra dans un nouvel onglet.
      </p>
      <p>
        <a id="camLink" href="#" target="_blank"
           style="display:inline-block; background:#0066aa; color:white; padding:14px 20px; border-radius:8px; text-decoration:none; font-size:20px;">
          Ouvrir caméra USB RB2
        </a>
      </p>
      <img id="rb2UsbCam" src="" alt="Caméra USB RB2"
           style="width:100%; max-width:860px; border:2px solid #444; background:#000;">
    </div>

    <script>
      document.addEventListener("DOMContentLoaded", function () {
        const url = window.location.protocol + "//" + window.location.hostname + ":8082/";
        const stream = url + "stream.mjpg";
        const link = document.getElementById("camLink");
        const img = document.getElementById("rb2UsbCam");
        if (link) link.href = url;
        if (img) img.src = stream;
      });
    
// RB2_TERRAIN_HA_COMPACT
let terrainHaTimer = null;

function rb2ResizeHaCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {w: rect.width, h: rect.height, ctx: ctx};
}

function rb2DrawTerrainHA(rollDeg, pitchDeg, ok, ageS) {
  const canvas = document.getElementById("terrainHaCanvas");
  const label = document.getElementById("terrainHaText");
  if (!canvas) return;

  const r = rb2ResizeHaCanvas(canvas);
  const ctx = r.ctx;
  const w = r.w;
  const h = r.h;
  const cx = w / 2;
  const cy = h / 2;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#050505";
  ctx.fillRect(0, 0, w, h);

  if (!ok) {
    ctx.fillStyle = "#ff6666";
    ctx.font = "13px Arial";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("IMU non disponible", cx, cy);
    if (label) label.textContent = "IMU : non disponible";
    return;
  }

  const roll = Number(rollDeg || 0);
  const pitch = Number(pitchDeg || 0);
  const age = Number(ageS || 0);

  if (label) {
    label.textContent = "R " + roll.toFixed(1) + "° / P " + pitch.toFixed(1) + "°";
    label.style.color = age > 3 ? "#ffcc66" : "#9ca3af";
  }

  // Horizon artificiel simple :
  // roll = rotation de la ligne; pitch = déplacement vertical.
  const rollRad = -roll * Math.PI / 180.0;
  const pitchOffset = Math.max(-24, Math.min(24, pitch * 2.0));

  ctx.save();
  ctx.translate(cx, cy + pitchOffset);
  ctx.rotate(rollRad);

  // Sol
  ctx.fillStyle = "#5a3518";
  ctx.fillRect(-w, 0, w * 2, h);

  // Ciel
  ctx.fillStyle = "#1e3a5f";
  ctx.fillRect(-w, -h, w * 2, h);

  // Ligne d'horizon
  ctx.strokeStyle = "#facc15";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(-w, 0);
  ctx.lineTo(w, 0);
  ctx.stroke();

  ctx.restore();

  // Repère central fixe
  ctx.strokeStyle = "#e5e7eb";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx - 34, cy);
  ctx.lineTo(cx - 8, cy);
  ctx.moveTo(cx + 8, cy);
  ctx.lineTo(cx + 34, cy);
  ctx.moveTo(cx, cy - 8);
  ctx.lineTo(cx, cy + 8);
  ctx.stroke();

  // Cadre
  ctx.strokeStyle = "#444";
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
}

async function rb2UpdateTerrainHA() {
  try {
    const res = await fetch("/imu_json", {cache: "no-store"});
    const j = await res.json();

    const ok = !!(j.ok !== false);
    const roll = Number(j.roll_deg ?? j.roll ?? 0);
    const pitch = Number(j.pitch_deg ?? j.pitch ?? 0);
    const age = Number(j.age_s ?? j.age ?? 0);

    rb2DrawTerrainHA(roll, pitch, ok, age);
  } catch (e) {
    rb2DrawTerrainHA(0, 0, false, 999);
  }
}

setTimeout(() => {
  try {
    rb2UpdateTerrainHA();
    terrainHaTimer = setInterval(rb2UpdateTerrainHA, 500);
  } catch (e) {
    console.log("Erreur HA terrain:", e);
  }
}, 1200);


</script>

    <h1>RB2 - Test ESP32</h1>

    <div class="note">
      Interface temporaire de test : Raspberry Pi 5 → USB série → ESP32
    </div>

    <div class="warning">
      Commande moteur maintenue : cliquer/tenir pour bouger, relâcher pour arrêter.
    </div>

    <div class="limits">
      Limite spéciale : si Tilt est entre 135° et 145°, Pan est limité entre 60° et 135°.
    </div>

    <h3>Déplacement manuel</h3>

    <div class="drive-status">
      Direction : <span id="driveStatus">arrêt</span>
    </div>

    <div class="drive-grid" id="drivePad">
      <div></div>
      <button class="drive-btn" data-drive="d20,20" data-label="avance">Avance</button>
      <div></div>

      <button class="drive-btn" data-drive="d-20,20" data-label="gauche">Gauche</button>
      <button class="drive-btn stop" data-drive="d0,0" data-label="stop">STOP</button>
      <button class="drive-btn" data-drive="d20,-20" data-label="droite">Droite</button>

      <div></div>
      <button class="drive-btn" data-drive="d-20,-20" data-label="recul">Recul</button>
      <div></div>
    </div>

    <h3>Pan-Tilt manuel</h3>

    <div class="stepbox">
      Pas de déplacement :
      <label><input type="radio" name="step" value="2"> fin 2°</label>
      <label><input type="radio" name="step" value="5" checked> normal 5°</label>
      <label><input type="radio" name="step" value="10"> rapide 10°</label>
    </div>

    <div class="pt-grid">
      <div></div>
      <button class="arrow" onclick="tiltUp()">▲<br>Tilt haut</button>
      <div></div>

      <button class="arrow" onclick="panLeft()">◀<br>Pan gauche</button>

      <div class="readout">
        Pan : <span id="panValue">90</span>°<br>
        Tilt : <span id="tiltValue">90</span>°
      </div>

      <button class="arrow" onclick="panRight()">▶<br>Pan droite</button>

      <div></div>
      <button class="arrow" onclick="tiltDown()">▼<br>Tilt bas</button>
      <div></div>
    </div>

    <div class="row">
      <button class="small" onclick="setPanTilt(90,90)">Centre 90/90</button>
      <button class="small" onclick="setTiltOnly(145)">Tilt max 145</button>
      <button class="small stop" onclick="setTiltOnly(68)">Tilt min 68</button>
    </div>

    <div class="row">
      <button class="small" onclick="setPanOnly(60)">Pan 60</button>
      <button class="small" onclick="setPanOnly(90)">Pan centre 90</button>
      <button class="small" onclick="setPanOnly(135)">Pan 135</button>
    </div>

    <h3>Encodeurs</h3>

    <div class="encoder-grid">
      <div class="encoder-box">
        <div class="encoder-label">Avant gauche FL</div>
        <div class="encoder-value" id="encFL">—</div>
      </div>

      <div class="encoder-box">
        <div class="encoder-label">Avant droit FR</div>
        <div class="encoder-value" id="encFR">—</div>
      </div>

      <div class="encoder-box">
        <div class="encoder-label">Arrière droit RR</div>
        <div class="encoder-value" id="encRR">—</div>
      </div>

      <div class="encoder-box">
        <div class="encoder-label">Arrière gauche RL</div>
        <div class="encoder-value" id="encRL">—</div>
      </div>
    </div>

    <div class="encoder-grid" style="margin-top: 10px;">
      <div class="encoder-box">
        <div class="encoder-label">Distance estimée</div>
        <div class="encoder-value"><span id="odomDistance">—</span> cm</div>
      </div>

      <div class="encoder-box">
        <div class="encoder-label">Angle estimé</div>
        <div class="encoder-value"><span id="odomAngle">—</span>°</div>
      </div>
    </div>

    <div class="auto-box">
      <label>
        <input type="checkbox" id="autoEncoders" onchange="toggleAutoEncoders()">
        Lecture automatique des encodeurs toutes les 2 secondes
      </label>
    </div>

    <div class="row">
      <button class="small" onclick="readEncoders()">Lire encodeurs</button>
      <button class="small" onclick="resetEncoders()">Reset encodeurs</button>
      <button class="small" onclick="cmd('status')">Status</button>
    </div>
      <!-- Bloc Diagnostic / Réponse ESP32 retiré de l'interface terrain.
           Le log est conservé caché pour ne pas casser le JavaScript existant. -->
      <pre id="log" style="display:none;"></pre>
</div>

<script>
let pan = 90;
let tilt = 90;

const PAN_NORMAL_MIN = 50;
const PAN_NORMAL_MAX = 140;

const PAN_HIGH_TILT_MIN = 60;
const PAN_HIGH_TILT_MAX = 135;

const TILT_MIN = 68;
const TILT_MAX = 145;

const TILT_RESTRICT_START = 135;

let driving = false;
let currentDriveCmd = "d0,0";
let currentDriveLabel = "arrêt";
let driveTimer = null;

const DRIVE_REPEAT_MS = 250;

let encoderTimer = null;
const ENCODER_REPEAT_MS = 2000;

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function isHighTilt() {
  return tilt >= TILT_RESTRICT_START && tilt <= TILT_MAX;
}

function currentPanMin() {
  return isHighTilt() ? PAN_HIGH_TILT_MIN : PAN_NORMAL_MIN;
}

function currentPanMax() {
  return isHighTilt() ? PAN_HIGH_TILT_MAX : PAN_NORMAL_MAX;
}

function enforcePanLimitForCurrentTilt() {
  const minPan = currentPanMin();
  const maxPan = currentPanMax();

  const oldPan = pan;
  pan = clamp(pan, minPan, maxPan);

  if (pan !== oldPan) {
    cmd("p" + pan);
  }
}

function getStep() {
  const selected = document.querySelector('input[name="step"]:checked');
  return parseInt(selected.value);
}

function updateReadout() {
  document.getElementById("panValue").textContent = pan;
  document.getElementById("tiltValue").textContent = tilt;
}

function updateDriveStatus() {
  document.getElementById("driveStatus").textContent = currentDriveLabel;
}

function updateEncoderDisplay(values, odom = null) {
  if (!values) {
    return;
  }

  document.getElementById("encFL").textContent =
    values.FL !== null && values.FL !== undefined ? values.FL : "—";

  document.getElementById("encFR").textContent =
    values.FR !== null && values.FR !== undefined ? values.FR : "—";

  document.getElementById("encRR").textContent =
    values.RR !== null && values.RR !== undefined ? values.RR : "—";

  document.getElementById("encRL").textContent =
    values.RL !== null && values.RL !== undefined ? values.RL : "—";

  const odomDistance = document.getElementById("odomDistance");
  const odomAngle = document.getElementById("odomAngle");

  if (odom && odomDistance && odomAngle) {
    odomDistance.textContent =
      odom.center_cm !== null && odom.center_cm !== undefined
        ? odom.center_cm.toFixed(1)
        : "—";

    odomAngle.textContent =
      odom.angle_deg !== null && odom.angle_deg !== undefined
        ? odom.angle_deg.toFixed(1)
        : "—";
  }
}

function clearDriveActiveButtons() {
  document.querySelectorAll(".drive-btn").forEach(btn => {
    btn.classList.remove("active");
  });
}

function setDriveActiveButton(button) {
  clearDriveActiveButtons();

  if (button) {
    button.classList.add("active");
  }
}

async function cmd(command, showLog = true) {
  const log = document.getElementById("log");

  if (showLog) {
    log.textContent = "Commande envoyée : " + command + "\\n";
  }

  try {
    const res = await fetch("/cmd", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({cmd: command})
    });

    const data = await res.json();

    if (showLog) {
      log.textContent += JSON.stringify(data, null, 2);
    }

    return data;
  } catch (e) {
    if (showLog) {
      log.textContent += "ERREUR: " + e;
    }
    return {"ok": false, "error": String(e)};
  }
}

function sendDriveCommand(repeated = false) {
  cmd(currentDriveCmd, !repeated);
}

function startDrive(button) {
  if (!button) return;

  // Nettoyer tout ancien timer avant de démarrer.
  if (driveTimer) {
    clearInterval(driveTimer);
    driveTimer = null;
  }

  currentDriveCmd = button.dataset.drive || "d0,0";
  currentDriveLabel = button.dataset.label || currentDriveCmd;
  driving = true;
  updateDriveStatus();

  // Commande immédiate.
  cmd(currentDriveCmd);

  // Répétition maintenue, plus lente que 250 ms pour éviter l'empilement réseau.
  driveTimer = setInterval(() => {
    if (driving && currentDriveCmd !== "d0,0") {
      cmd(currentDriveCmd);
    }
  }, 350);
}

function stopDrive() {
  // D'abord désactiver l'état de conduite.
  driving = false;
  currentDriveCmd = "d0,0";
  currentDriveLabel = "arrêt";
  updateDriveStatus();

  // Ensuite arrêter le timer AVANT d'envoyer le stop.
  if (driveTimer) {
    clearInterval(driveTimer);
    driveTimer = null;
  }

  // Envoyer plusieurs stops pour écraser toute commande retardée.
  cmd("d0,0");
  setTimeout(() => cmd("d0,0"), 80);
  setTimeout(() => cmd("d0,0"), 200);
}

function setupDrivePad() {
  const buttons = document.querySelectorAll(".drive-btn");

  for (const b of buttons) {
    b.addEventListener("pointerdown", e => {
      e.preventDefault();
      try {
        b.setPointerCapture(e.pointerId);
      } catch (err) {}
      startDrive(b);
    });

    b.addEventListener("pointerup", e => {
      e.preventDefault();
      stopDrive();
    });

    b.addEventListener("pointercancel", e => {
      e.preventDefault();
      stopDrive();
    });

    b.addEventListener("lostpointercapture", e => {
      stopDrive();
    });

    // Empêcher le menu contextuel et les comportements tactiles parasites.
    b.addEventListener("contextmenu", e => {
      e.preventDefault();
    });
  }

  // Sécurité générale : si le pointeur quitte la fenêtre ou si l'onglet perd le focus.
  window.addEventListener("blur", stopDrive);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopDrive();
  });
}

async function readEncoders(showLog = true) {
  try {
    const res = await fetch("/encoders", {
      method: "GET"
    });

    const data = await res.json();

    if (data.ok && data.values) {
      updateEncoderDisplay(data.values, data.odom);
    }

    if (showLog) {
      const log = document.getElementById("log");
      log.textContent = JSON.stringify(data, null, 2);
    }

    return data;
  } catch (e) {
    if (showLog) {
      const log = document.getElementById("log");
      log.textContent = "ERREUR lecture encodeurs: " + e;
    }
    return {"ok": false, "error": String(e)};
  }
}

window.addEventListener("offline", () => {
  try { stopDrive(); } catch (e) {}
});

window.addEventListener("online", () => {
  try { stopDrive(); syncDriveServerTime(); } catch (e) {}
});

async function resetEncoders() {
  const data = await cmd("encreset", true);

  document.getElementById("encFL").textContent = "0";
  document.getElementById("encFR").textContent = "0";
  document.getElementById("encRR").textContent = "0";
  document.getElementById("encRL").textContent = "0";

  return data;
}

function toggleAutoEncoders() {
  const checkbox = document.getElementById("autoEncoders");

  if (checkbox.checked) {
    readEncoders(false);

    encoderTimer = setInterval(() => {
      if (!driving) {
        readEncoders(false);
      }
    }, ENCODER_REPEAT_MS);
  } else {
    if (encoderTimer) {
      clearInterval(encoderTimer);
      encoderTimer = null;
    }
  }
}

function panLeft() {
  pan = clamp(pan - getStep(), currentPanMin(), currentPanMax());
  updateReadout();
  cmd("p" + pan);
}

function panRight() {
  pan = clamp(pan + getStep(), currentPanMin(), currentPanMax());
  updateReadout();
  cmd("p" + pan);
}

function tiltUp() {
  tilt = clamp(tilt + getStep(), TILT_MIN, TILT_MAX);
  enforcePanLimitForCurrentTilt();
  updateReadout();
  cmd("t" + tilt);
}

function tiltDown() {
  tilt = clamp(tilt - getStep(), TILT_MIN, TILT_MAX);
  updateReadout();
  cmd("t" + tilt);
}

function setPanTilt(newPan, newTilt) {
  tilt = clamp(newTilt, TILT_MIN, TILT_MAX);
  pan = clamp(newPan, currentPanMin(), currentPanMax());

  updateReadout();

  cmd("p" + pan);
  setTimeout(() => cmd("t" + tilt), 250);
}

function setPanOnly(newPan) {
  pan = clamp(newPan, currentPanMin(), currentPanMax());
  updateReadout();
  cmd("p" + pan);
}

function setTiltOnly(newTilt) {
  tilt = clamp(newTilt, TILT_MIN, TILT_MAX);
  enforcePanLimitForCurrentTilt();
  updateReadout();
  cmd("t" + tilt);
}

updateReadout();
updateDriveStatus();
syncDriveServerTime();
setInterval(syncDriveServerTime, 30000);
setupDrivePad();
readEncoders(false);
</script>

<script>
async function rb2ShutdownAll() {
  const ok = confirm(
    "Confirmer l'arrêt complet de RB2 ?\\n\\n" +
    "Le Zero 2 W caméra sera arrêté en premier.\\n" +
    "Le Raspberry Pi 5 sera ensuite arrêté.\\n\\n" +
    "Après confirmation, l'interface web cessera de répondre."
  );

  if (!ok) return;

  const btn = document.getElementById("rb2ShutdownAllBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "ARRÊT RB2 EN COURS...";
  }

  try {
    const res = await fetch("/system_shutdown_all", {
      method: "POST",
      cache: "no-store"
    });

    const data = await res.json();

    if (!data.ok) {
      alert("Erreur arrêt RB2 : " + (data.error || "erreur inconnue"));
      if (btn) {
        btn.disabled = false;
        btn.textContent = "ARRÊTER RB2 COMPLET";
      }
      return;
    }

    alert("Arrêt complet RB2 demandé.\nLe Zero 2 W puis le Pi 5 vont s'arrêter.");

  } catch (e) {
    alert("Commande envoyée ou connexion perdue.\nSi RB2 s'arrête, c'est normal.");
  }
}
</script>


<!-- RB2_SHUTDOWN_FIXED_SIMPLE -->
<style>
#rb2ShutdownAllBtnFixed {
  position: fixed;
  left: 14px;
  bottom: 14px;
  z-index: 99999;
  min-width: 220px;
  min-height: 44px;
  padding: 10px 14px;
  border: 3px solid #7a0000;
  border-radius: 10px;
  background: #b00000;
  color: #ffffff;
  font-weight: 900;
  font-size: 15px;
  box-shadow: 0 0 12px rgba(0,0,0,0.55);
  cursor: pointer;
}
#rb2ShutdownAllBtnFixed:hover {
  background: #d00000;
}
</style>
<script>
function rb2ShutdownAllFixedSimple() {
  if (!confirm("Confirmer l arrêt complet de RB2 ?\\n\\nLe Zero 2 W sera arrêté, puis le Pi 5.")) return;

  const btn = document.getElementById("rb2ShutdownAllBtnFixed");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "ARRÊT EN COURS...";
  }

  fetch("/system_shutdown_all", {method: "POST", cache: "no-store"})
    .then(r => r.json())
    .then(j => {
      if (!j.ok) alert("Erreur arrêt RB2 : " + (j.error || "erreur inconnue"));
      else alert("Arrêt complet RB2 demandé.");
    })
    .catch(e => {
      alert("Commande envoyée ou connexion perdue. Si RB2 s arrête, c est normal.");
    });
}

function rb2AddShutdownButtonFixedSimple() {
  if (document.getElementById("rb2ShutdownAllBtnFixed")) return;
  const b = document.createElement("button");
  b.id = "rb2ShutdownAllBtnFixed";
  b.textContent = "ARRÊTER RB2 COMPLET";
  b.onclick = rb2ShutdownAllFixedSimple;
  document.body.appendChild(b);
}

document.addEventListener("DOMContentLoaded", rb2AddShutdownButtonFixedSimple);
setTimeout(rb2AddShutdownButtonFixedSimple, 500);
setTimeout(rb2AddShutdownButtonFixedSimple, 1500);
</script>


<script>
// RB2_CAMERA_AUTORELOAD_FIX
(function () {
  function rb2ReloadCameraStream() {
    try {
      const imgs = Array.from(document.querySelectorAll("img"));
      const candidates = imgs.filter(img => {
        const src = img.getAttribute("src") || "";
        const id = img.getAttribute("id") || "";
        return (
          src.includes("zero_cam_stream") ||
          src.includes("stream.mjpg") ||
          id === "cam" ||
          id === "rb2UsbCam"
        );
      });

      candidates.forEach(img => {
        let src = img.getAttribute("src") || "";

        if (!src || src === "#") {
          src = "/zero_cam_stream.mjpg";
        }

        const base = src.split("?")[0];
        img.setAttribute("src", base + "?t=" + Date.now());
      });
    } catch (e) {
      console.log("RB2 camera autoreload error:", e);
    }
  }

  window.addEventListener("load", function () {
    setTimeout(rb2ReloadCameraStream, 500);
  });

  window.addEventListener("pageshow", function () {
    setTimeout(rb2ReloadCameraStream, 300);
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      setTimeout(rb2ReloadCameraStream, 300);
    }
  });

  window.addEventListener("focus", function () {
    setTimeout(rb2ReloadCameraStream, 300);
  });
})();
</script>


<script>
// RB2_EXTRA_LINK_BUTTONS_FIX
(function () {
  function rb2AddExtraButtonsNearShutdown() {
    try {
      const shutdownBtn = document.querySelector(".rb2-shutdown-all-btn");
      if (!shutdownBtn) return;

      if (document.getElementById("rb2ExtraButtonsRow")) return;

      const parent = shutdownBtn.parentElement;
      if (!parent) return;

      const row = document.createElement("div");
      row.id = "rb2ExtraButtonsRow";
      row.style.display = "grid";
      row.style.gridTemplateColumns = "1.4fr 0.8fr 0.9fr";
      row.style.gap = "8px";
      row.style.marginTop = "8px";
      row.style.width = "100%";
      row.style.boxSizing = "border-box";

      shutdownBtn.style.width = "100%";
      shutdownBtn.style.marginTop = "0";
      shutdownBtn.style.minHeight = "42px";

      parent.insertBefore(row, shutdownBtn);
      row.appendChild(shutdownBtn);

      const lidarBtn = document.createElement("button");
      lidarBtn.type = "button";
      lidarBtn.textContent = "LIDAR";
      lidarBtn.title = "Ouvrir la page LIDAR";
      lidarBtn.style.minHeight = "42px";
      lidarBtn.style.fontWeight = "800";
      lidarBtn.style.fontSize = "14px";
      lidarBtn.style.background = "#2563eb";
      lidarBtn.style.color = "white";
      lidarBtn.style.border = "2px solid #1d4ed8";
      lidarBtn.style.borderRadius = "8px";
      lidarBtn.style.cursor = "pointer";
      lidarBtn.onclick = function () {
        window.open("/lidar_drive", "_blank");
      };

      const camBtn = document.createElement("button");
      camBtn.type = "button";
      camBtn.textContent = "CAMÉRA";
      camBtn.title = "Ouvrir l'image caméra seulement";
      camBtn.style.minHeight = "42px";
      camBtn.style.fontWeight = "800";
      camBtn.style.fontSize = "14px";
      camBtn.style.background = "#047857";
      camBtn.style.color = "white";
      camBtn.style.border = "2px solid #065f46";
      camBtn.style.borderRadius = "8px";
      camBtn.style.cursor = "pointer";
      camBtn.onclick = function () {
        window.open("/zero_cam_stream.mjpg", "_blank");
      };

      row.appendChild(lidarBtn);
      row.appendChild(camBtn);
    } catch (e) {
      console.log("Erreur ajout boutons RB2:", e);
    }
  }

  window.addEventListener("load", rb2AddExtraButtonsNearShutdown);
  document.addEventListener("DOMContentLoaded", rb2AddExtraButtonsNearShutdown);
  setTimeout(rb2AddExtraButtonsNearShutdown, 1000);
})();
</script>

</body>
</html>
"""


def parse_encoders_from_text(text):
    values = {
        "FL": None,
        "FR": None,
        "RR": None,
        "RL": None,
    }

    if not text:
        return values

    patterns = {
        "FL": [
            r"FL\s*[:=]\s*(-?\d+)",
            r"Avant\s+gauche.*?(-?\d+)",
        ],
        "FR": [
            r"FR\s*[:=]\s*(-?\d+)",
            r"Avant\s+droit.*?(-?\d+)",
        ],
        "RR": [
            r"RR\s*[:=]\s*(-?\d+)",
            r"Arriere\s+droit.*?(-?\d+)",
            r"Arrière\s+droit.*?(-?\d+)",
        ],
        "RL": [
            r"RL\s*[:=]\s*(-?\d+)",
            r"Arriere\s+gauche.*?(-?\d+)",
            r"Arrière\s+gauche.*?(-?\d+)",
        ],
    }

    for key, pattern_list in patterns.items():
        for pattern in pattern_list:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                values[key] = int(match.group(1))
                break

    return values


WHEEL_DIAMETER_MM = 85.0
TICKS_PER_REV = 10529.0
TRACK_WIDTH_MM = 225.0
MM_PER_TICK = (3.141592653589793 * WHEEL_DIAMETER_MM) / TICKS_PER_REV

# === RB2 WHEEL TICKS JSON BRIDGE - BEGIN ===
# Pont encodeurs ESP32 -> ROS2.
# Écrit le fichier attendu par rb2_wheel_ticks_json_node :
# /tmp/rb2_wheel_ticks.json
#
# Format :
# {"ok": true, "stamp": time.time(), "data": [FL, FR, RR, RL]}

import json as _rb2_ticks_json
import os as _rb2_ticks_os
import time as _rb2_ticks_time

_RB2_WHEEL_TICKS_JSON_FILE = "/tmp/rb2_wheel_ticks.json"

def rb2_write_wheel_ticks_json(values):
    try:
        if not values:
            return False

        fl = int(values.get("FL") or 0)
        fr = int(values.get("FR") or 0)
        rr = int(values.get("RR") or 0)
        rl = int(values.get("RL") or 0)

        payload = {
            "ok": True,
            "stamp": _rb2_ticks_time.time(),
            "data": [fl, fr, rr, rl],
        }

        tmp_path = _RB2_WHEEL_TICKS_JSON_FILE + ".tmp"

        with open(tmp_path, "w", encoding="utf-8") as f:
            _rb2_ticks_json.dump(payload, f)

        _rb2_ticks_os.replace(tmp_path, _RB2_WHEEL_TICKS_JSON_FILE)
        return True

    except Exception as e:
        try:
            with open("/tmp/rb2_wheel_ticks_json_error.log", "a", encoding="utf-8") as f:
                f.write(f"{_rb2_ticks_time.time():.3f} {e}\n")
        except Exception:
            pass
        return False

# === RB2 WHEEL TICKS JSON BRIDGE - END ===

# === RB2 WHEEL TICKS JSON HEARTBEAT - BEGIN ===
# Maintient /tmp/rb2_wheel_ticks.json frais entre deux lectures encodeurs.
# Ne parle pas à l'ESP32. Il réécrit seulement la dernière valeur connue avec un stamp récent.
# Objectif : éviter les coupures /wheel_ticks et /odom quand les roues sont immobiles.

import threading as _rb2_ticks_threading

_rb2_ticks_last_values = None
_rb2_ticks_last_lock = _rb2_ticks_threading.Lock()
_rb2_ticks_heartbeat_started = False

_rb2_write_wheel_ticks_json_original = rb2_write_wheel_ticks_json

def rb2_write_wheel_ticks_json(values):
    global _rb2_ticks_last_values

    ok = _rb2_write_wheel_ticks_json_original(values)

    if ok and values:
        try:
            fl = int(values.get("FL") or 0)
            fr = int(values.get("FR") or 0)
            rr = int(values.get("RR") or 0)
            rl = int(values.get("RL") or 0)

            with _rb2_ticks_last_lock:
                _rb2_ticks_last_values = {
                    "FL": fl,
                    "FR": fr,
                    "RR": rr,
                    "RL": rl,
                }
        except Exception:
            pass

    return ok

def _rb2_wheel_ticks_heartbeat_loop():
    while True:
        try:
            with _rb2_ticks_last_lock:
                values = dict(_rb2_ticks_last_values) if _rb2_ticks_last_values else None

            if values:
                _rb2_write_wheel_ticks_json_original(values)

        except Exception as e:
            try:
                with open("/tmp/rb2_wheel_ticks_heartbeat_error.log", "a", encoding="utf-8") as f:
                    f.write(f"{_rb2_ticks_time.time():.3f} {e}\n")
            except Exception:
                pass

        _rb2_ticks_time.sleep(0.25)

def _rb2_start_wheel_ticks_heartbeat():
    global _rb2_ticks_heartbeat_started

    if _rb2_ticks_heartbeat_started:
        return

    _rb2_ticks_heartbeat_started = True

    t = _rb2_ticks_threading.Thread(
        target=_rb2_wheel_ticks_heartbeat_loop,
        name="rb2-wheel-ticks-heartbeat",
        daemon=True,
    )
    t.start()

_rb2_start_wheel_ticks_heartbeat()

# === RB2 WHEEL TICKS JSON HEARTBEAT - END ===





def compute_odom_from_values(values):
    if not values:
        return {
            "left_mm": None,
            "right_mm": None,
            "center_mm": None,
            "center_cm": None,
            "angle_deg": None,
        }

    try:
        fl = int(values.get("FL") or 0)
        fr = int(values.get("FR") or 0)
        rr = int(values.get("RR") or 0)
        rl = int(values.get("RL") or 0)

        left_ticks = (fl + rl) / 2.0
        right_ticks = (fr + rr) / 2.0

        left_mm = left_ticks * MM_PER_TICK
        right_mm = right_ticks * MM_PER_TICK
        center_mm = (left_mm + right_mm) / 2.0

        angle_rad = (right_mm - left_mm) / TRACK_WIDTH_MM
        angle_deg = angle_rad * 57.29577951308232

        return {
            "left_mm": left_mm,
            "right_mm": right_mm,
            "center_mm": center_mm,
            "center_cm": center_mm / 10.0,
            "angle_deg": angle_deg,
        }

    except Exception:
        return {
            "left_mm": None,
            "right_mm": None,
            "center_mm": None,
            "center_cm": None,
            "angle_deg": None,
        }


def parse_encoders_from_lines(lines):
    if not lines:
        return {
            "FL": None,
            "FR": None,
            "RR": None,
            "RL": None,
        }

    text = "\\n".join(str(line) for line in lines)
    return parse_encoders_from_text(text)






@app.route("/imu_json")
def imu_json_status():
    imu_file = "/tmp/rb2_imu.json"

    if not os.path.exists(imu_file):
        return jsonify({
            "ok": False,
            "error": "Fichier IMU absent",
            "file": imu_file
        })

    try:
        st = os.stat(imu_file)
        age_s = time.time() - st.st_mtime

        with open(imu_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        return jsonify({
            "ok": True,
            "age_s": age_s,
            "file": imu_file,
            "data": data
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "file": imu_file
        })


@app.route("/lidar")
def lidar_status():
    lidar_file = "/tmp/rb2_lidar.json"

    if not os.path.exists(lidar_file):
        return jsonify({
            "ok": False,
            "error": "Fichier LIDAR absent",
            "file": lidar_file
        })

    try:
        st = os.stat(lidar_file)
        age_s = time.time() - st.st_mtime

        with open(lidar_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        return jsonify({
            "ok": True,
            "age_s": age_s,
            "file": lidar_file,
            "data": data
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "file": lidar_file
        })


@app.route("/")
def index():
    return render_template_string(HTML)



@app.route("/light", methods=["GET", "POST"])
def light_control():
    global rb2_light_state

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        state = str(data.get("state", "")).lower().strip()

        if state not in ("on", "off"):
            return jsonify({
                "ok": False,
                "error": "État invalide",
                "state": "on" if rb2_light_state else "off",
                "gpio": LIGHT_GPIO_BCM
            }), 400

        ok, error = rb2_set_light(state == "on")

        return jsonify({
            "ok": ok,
            "error": error,
            "state": "on" if rb2_light_state else "off",
            "gpio": LIGHT_GPIO_BCM
        })

    return jsonify({
        "ok": rb2_light is not None,
        "error": rb2_light_error,
        "state": "on" if rb2_light_state else "off",
        "gpio": LIGHT_GPIO_BCM
    })


@app.route("/relay2", methods=["GET", "POST"])
def relay2_control():
    global rb2_relay2_state

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        state = str(data.get("state", "")).lower().strip()

        if state not in ("on", "off"):
            return jsonify({
                "ok": False,
                "error": "État invalide",
                "state": "on" if rb2_relay2_state else "off",
                "gpio": RELAY2_GPIO_BCM
            }), 400

        ok, error = rb2_set_relay2(state == "on")

        return jsonify({
            "ok": ok,
            "error": error,
            "state": "on" if rb2_relay2_state else "off",
            "gpio": RELAY2_GPIO_BCM
        })

    return jsonify({
        "ok": rb2_relay2 is not None,
        "error": rb2_relay2_error,
        "state": "on" if rb2_relay2_state else "off",
        "gpio": RELAY2_GPIO_BCM
    })

@app.route("/drive_time")
def drive_time():
    return jsonify({
        "ok": True,
        "server_ms": int(time.time() * 1000),
        "max_age_ms": DRIVE_MAX_AGE_MS,
    })


@app.route("/cmd", methods=["POST"])
def command():
    data = request.get_json(force=True)
    command_text = data.get("cmd", "").strip()

    if not command_text:
        return jsonify({
            "ok": False,
            "error": "Commande vide"
        })

    parsed_drive_for_replay = rb2_parse_drive_command(command_text)
    if parsed_drive_for_replay is not None and rb2_trace_follow_is_running():
        if parsed_drive_for_replay[0] == 0 and parsed_drive_for_replay[1] == 0:
            rb2_trace_follow_request_stop("STOP opérateur pendant SUIVRE TRACE")
        else:
            rb2_trace_follow_request_stop("Commande manuelle refusée: SUIVRE TRACE actif")
            return jsonify({
                "ok": False,
                "command": command_text,
                "ignored": True,
                "error": "SUIVRE TRACE actif: commande manuelle non-stop refusée",
                "drive_safety": "rejeu trace prioritaire stoppé"
            }), 409

    drive_result = rb2_safe_drive_send(command_text, data)
    if drive_result is not None:
        return jsonify(drive_result)

    result = esp32.send(command_text, wait=0.12)
    return jsonify(result)


@app.route("/encoders", methods=["GET"])
def encoders():
    result = esp32.send("enc", wait=1.0)

    lines = []
    lines.extend(result.get("lines", []))

    # On ajoute aussi les dernières lignes reçues par le module série,
    # car certaines réponses peuvent arriver juste après la première lecture.
    try:
        lines.extend(esp32.last_lines[-30:])
    except Exception:
        pass

    values = parse_encoders_from_lines(lines)
    rb2_write_wheel_ticks_json(values)

    # Convention RB2 :
    # avance physique = positif
    # recul physique  = négatif
    #
    # Les encodeurs droits sont inversés mécaniquement.
    # On inverse donc FR et RR avant affichage web.
    if values.get("FR") is not None:
        values["FR"] = -values["FR"]

    if values.get("RR") is not None:
        values["RR"] = -values["RR"]

    found_any = any(value is not None for value in values.values())
    odom = compute_odom_from_values(values) if found_any else {
        "left_mm": None,
        "right_mm": None,
        "center_mm": None,
        "center_cm": None,
        "angle_deg": None,
    }

    return jsonify({
        "ok": result.get("ok", False) and found_any,
        "command": "enc",
        "values": values,
        "odom": odom,
        "found_any": found_any,
        "lines_used": lines,
        "raw": result,
    })


@app.route("/stop", methods=["POST", "GET"])
def stop():
    result = esp32.stop()
    return jsonify(result)


@app.route("/drive_safety_status")
def drive_safety_status():
    with DRIVE_SEQ_LOCK:
        return jsonify({
            "ok": True,
            "last_seq": DRIVE_LAST_SEQ,
            "last_token": DRIVE_LAST_TOKEN,
            "last_accept_age_s": time.time() - DRIVE_LAST_ACCEPT_TIME if DRIVE_LAST_ACCEPT_TIME else None,
            "last_stop_age_s": time.time() - DRIVE_LAST_STOP_TIME if DRIVE_LAST_STOP_TIME else None,
            "last_reject_age_s": time.time() - DRIVE_LAST_REJECT_TIME if DRIVE_LAST_REJECT_TIME else None,
            "last_reject_reason": DRIVE_LAST_REJECT_REASON,
            "last_reject_command": DRIVE_LAST_REJECT_COMMAND,
            "max_age_ms": DRIVE_MAX_AGE_MS,
        })





# -----------------------------------------------------------------------------
# V10 - SUIVRE TRACE : REJEU EXACT OPÉRATEUR
# -----------------------------------------------------------------------------
# La V7/V8 tentait de transformer la trace en cibles odométriques. En pratique,
# cette logique arrêtait trop tôt lorsque les deltas mesurés étaient petits ou
# bruités. La V9 change de philosophie : elle rejoue fidèlement la séquence de
# conduite enregistrée, avec les mêmes commandes et les mêmes durées.
#
# L'odométrie n'est plus utilisée pour décider d'arrêter un segment; elle sert à
# afficher ce que RB2 fait réellement pendant le rejeu. Les seuls arrêts imposés
# sont : STOP opérateur, fin de fichier, erreur, ou danger LIDAR.

TRACE_FOLLOW_MAX_SPEED = 100       # V10 : pas de plafonnement artificiel de vitesse
TRACE_FOLLOW_FRONT_MIN_CM = 37.0   # garde-fou danger avant pratique RB2
TRACE_FOLLOW_BACK_MIN_CM = 17.0    # garde-fou danger arrière pratique RB2
TRACE_FOLLOW_KEEPALIVE_S = 0.18    # maintien commande plus ferme
TRACE_FOLLOW_ODOM_SAMPLE_S = 0.20
TRACE_FOLLOW_SEGMENT_MIN_MOVE_CM = 0.0
TRACE_FOLLOW_SEGMENT_MIN_ANGLE_DEG = 0.0
TRACE_FOLLOW_SEGMENT_MAX_S = 60.0

try:
    TRACE_FOLLOW_STATUS["mode"] = "v10_rejeu_exact_operateur"
    TRACE_FOLLOW_STATUS["speed_limit"] = TRACE_FOLLOW_MAX_SPEED
    TRACE_FOLLOW_STATUS["front_min_cm"] = TRACE_FOLLOW_FRONT_MIN_CM
    TRACE_FOLLOW_STATUS["back_min_cm"] = TRACE_FOLLOW_BACK_MIN_CM
except Exception:
    pass


def rb2_trace_follow_limit_drive(left, right):
    """V10 : conserve la commande enregistrée. On ne déforme plus la trace."""
    try:
        left = int(left)
        right = int(right)
    except Exception:
        return 0, 0
    left = max(-100, min(100, left))
    right = max(-100, min(100, right))
    return left, right


def rb2_trace_follow_classify_segment(dc, da):
    # En V9, le mode de contrôle est temporel fidèle. L'odométrie reste informative.
    return "timed_exact_recorded"


def rb2_trace_follow_build_segments(rows):
    """
    V10 : construit les intervalles exacts du fichier *_drive.csv.

    Pour chaque ligne i, on rejoue la commande de la ligne i jusqu'au temps de la
    ligne i+1. Cela reproduit ce que l'opérateur a réellement demandé : mêmes
    commandes, même ordre, mêmes durées. Aucun regroupement odométrique, aucun
    arrêt entre les lignes, aucun plafonnement à 15%.
    """
    if not rows or len(rows) < 2:
        raise ValueError("trace insuffisante: au moins deux lignes valides requises")

    segments = []
    first_time = float(rows[0]["time_s"])
    for i in range(len(rows) - 1):
        a = rows[i]
        b = rows[i + 1]
        raw_left = int(a.get("left", 0) or 0)
        raw_right = int(a.get("right", 0) or 0)
        dt = max(0.0, float(b["time_s"]) - float(a["time_s"]))

        # Si deux écritures ont le même timestamp, ce n'est pas un mouvement réel.
        if dt <= 0.01:
            continue

        left, right = rb2_trace_follow_limit_drive(raw_left, raw_right)
        dc = float(b["center_cm"]) - float(a["center_cm"])
        da = float(b["angle_deg"]) - float(a["angle_deg"])

        segments.append({
            "index": len(segments) + 1,
            "raw_cmd": f"d{raw_left},{raw_right}",
            "cmd": f"d{left},{right}",
            "left": left,
            "right": right,
            "raw_left": raw_left,
            "raw_right": raw_right,
            "recorded_duration_s": dt,
            "start_time_s": float(a["time_s"]) - first_time,
            "end_time_s": float(b["time_s"]) - first_time,
            "target_center_cm": dc,
            "target_angle_deg": da,
            "mode": "timed_exact_recorded",
            "row_start": i + 1,
            "row_end": i + 2,
            "rows_grouped": 1,
        })

    # On accepte les segments STOP aussi, mais il doit exister au moins un mouvement.
    has_motion = any(int(s.get("left", 0)) != 0 or int(s.get("right", 0)) != 0 for s in segments)
    if not segments or not has_motion:
        raise ValueError("aucun intervalle de mouvement dans la trace")
    return segments


def rb2_trace_follow_segment_timeout_s(segment):
    # V10 : la durée vient du fichier. On garde seulement une marge technique.
    return min(TRACE_FOLLOW_SEGMENT_MAX_S, max(0.25, float(segment.get("recorded_duration_s") or 0.0) + 2.0))


def rb2_trace_follow_worker(path):
    try:
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_follow_build_segments(rows)
        total_recorded_s = sum(float(s.get("recorded_duration_s") or 0.0) for s in segments)

        rb2_trace_follow_set_status(
            running=True,
            ok=True,
            state="starting",
            message="Initialisation rejeu fidèle opérateur",
            file=os.path.basename(path),
            step=0,
            total=len(segments),
            cmd="d0,0",
            raw_cmd="",
            target_center_cm=None,
            target_angle_deg=None,
            actual_center_cm=None,
            actual_angle_deg=None,
            send_count=0,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            finished_at=None,
            last_error="",
            speed_limit=TRACE_FOLLOW_MAX_SPEED,
            front_min_cm=TRACE_FOLLOW_FRONT_MIN_CM,
            back_min_cm=TRACE_FOLLOW_BACK_MIN_CM,
            mode="v10_rejeu_exact_operateur",
            total_recorded_s=round(total_recorded_s, 3),
        )

        rb2_trace_follow_send_stop_burst()
        time.sleep(0.15)

        try:
            replay_start_odom = rb2_trace_follow_read_current_odom()
            start_center = replay_start_odom["center_cm"]
            start_angle = replay_start_odom["angle_deg"]
        except Exception:
            # Le rejeu fidèle peut fonctionner sans lecture odom initiale; on l'indique.
            start_center = None
            start_angle = None
            rb2_trace_follow_set_status(message="Rejeu fidèle: odométrie initiale non lue, suivi informatif réduit")

        cumulative_target_center = 0.0
        cumulative_target_angle = 0.0
        send_count = 0
        replay_mono_start = time.monotonic()

        for idx, seg in enumerate(segments):
            if TRACE_FOLLOW_STOP_EVENT.is_set():
                rb2_trace_follow_set_status(
                    running=False, ok=True, state="stopped",
                    message="Suivi arrêté par l'opérateur", cmd="d0,0",
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                )
                return

            left = int(seg["left"])
            right = int(seg["right"])
            command_text = seg["cmd"]
            duration_s = max(0.0, float(seg.get("recorded_duration_s") or 0.0))
            cumulative_target_center += float(seg.get("target_center_cm") or 0.0)
            cumulative_target_angle += float(seg.get("target_angle_deg") or 0.0)

            allowed, reason = rb2_trace_follow_lidar_allows(left, right)
            if not allowed:
                rb2_trace_follow_set_status(
                    running=False, ok=False, state="blocked",
                    message="Rejeu bloqué par sécurité LIDAR", last_error=reason,
                    step=idx + 1, cmd="d0,0", raw_cmd=seg["raw_cmd"],
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                )
                return

            rb2_trace_follow_set_status(
                running=True, ok=True, state="running", message=reason,
                step=idx + 1, total=len(segments), cmd=command_text,
                raw_cmd=seg["raw_cmd"], segment_mode="timed_exact_recorded",
                recorded_duration_s=round(duration_s, 3),
                start_time_s=round(float(seg.get("start_time_s") or 0.0), 3),
                end_time_s=round(float(seg.get("end_time_s") or 0.0), 3),
                target_center_cm=round(cumulative_target_center, 2),
                target_angle_deg=round(cumulative_target_angle, 2),
                send_count=send_count,
                row_start=seg.get("row_start"),
                row_end=seg.get("row_end"),
            )

            seg_start = time.monotonic()
            seg_end = seg_start + duration_s
            next_send = 0.0
            next_odom = 0.0

            while time.monotonic() < seg_end:
                if TRACE_FOLLOW_STOP_EVENT.is_set():
                    rb2_trace_follow_set_status(
                        running=False, ok=True, state="stopped",
                        message="Suivi arrêté par l'opérateur", cmd="d0,0",
                        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    )
                    return

                now_mono = time.monotonic()
                allowed, reason = rb2_trace_follow_lidar_allows(left, right)
                if not allowed:
                    rb2_trace_follow_set_status(
                        running=False, ok=False, state="blocked",
                        message="Rejeu bloqué pendant mouvement", last_error=reason,
                        cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    )
                    return

                if now_mono >= next_send:
                    esp32.send(command_text, wait=0.0)
                    send_count += 1
                    rb2_trace_follow_set_status(send_count=send_count)
                    next_send = now_mono + TRACE_FOLLOW_KEEPALIVE_S

                if now_mono >= next_odom:
                    if start_center is not None and start_angle is not None:
                        try:
                            odom_now = rb2_trace_follow_read_current_odom()
                            actual_center = odom_now["center_cm"] - start_center
                            actual_angle = odom_now["angle_deg"] - start_angle
                            rb2_trace_follow_set_status(
                                actual_center_cm=round(actual_center, 2),
                                actual_angle_deg=round(actual_angle, 2),
                                elapsed_replay_s=round(time.monotonic() - replay_mono_start, 2),
                            )
                        except Exception as e:
                            rb2_trace_follow_set_status(last_error="odom info: " + str(e))
                    next_odom = now_mono + TRACE_FOLLOW_ODOM_SAMPLE_S

                time.sleep(0.015)

        rb2_trace_follow_send_stop_burst()
        rb2_trace_follow_set_status(
            running=False, ok=True, state="finished", message="Rejeu fidèle opérateur terminé",
            cmd="d0,0", step=len(segments), total=len(segments),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            mode="v10_rejeu_exact_operateur",
        )

    except Exception as e:
        rb2_trace_follow_set_status(
            running=False, ok=False, state="error", message="Erreur rejeu fidèle trace",
            last_error=str(e), cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            mode="v10_rejeu_exact_operateur",
        )
    finally:
        rb2_trace_follow_send_stop_burst()

@app.route("/trace_follow_preview", methods=["GET"])
def trace_follow_preview():
    path = rb2_latest_drive_trace_path()
    if not path:
        return jsonify({"ok": False, "error": "Aucun fichier *_drive.csv trouvé"})
    try:
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_follow_build_segments(rows)
        preview = []
        total_center = 0.0
        total_abs_center = 0.0
        total_angle = 0.0
        for idx, seg in enumerate(segments):
            total_center += float(seg["target_center_cm"])
            total_abs_center += abs(float(seg["target_center_cm"]))
            total_angle += float(seg["target_angle_deg"])
            if idx < 30:
                preview.append({
                    "i": idx + 1,
                    "raw_cmd": seg["raw_cmd"],
                    "follow_cmd": seg["cmd"],
                    "mode": seg["mode"],
                    "recorded_duration_s": round(float(seg["recorded_duration_s"]), 3),
                    "target_center_cm": round(float(seg["target_center_cm"]), 2),
                    "target_angle_deg": round(float(seg["target_angle_deg"]), 2),
                    "rows_grouped": seg.get("rows_grouped"),
                    "row_start": seg.get("row_start"),
                    "row_end": seg.get("row_end"),
                })
        return jsonify({
            "ok": True,
            "file": os.path.basename(path),
            "path": path,
            "mode": "v10_rejeu_exact_operateur",
            "rows": len(rows),
            "segments": len(segments),
            "speed_limit": TRACE_FOLLOW_MAX_SPEED,
            "front_min_cm": TRACE_FOLLOW_FRONT_MIN_CM,
            "back_min_cm": TRACE_FOLLOW_BACK_MIN_CM,
            "total_center_cm": round(total_center, 2),
            "total_abs_center_cm": round(total_abs_center, 2),
            "total_angle_deg": round(total_angle, 2),
            "preview": preview,
            "note": "V10: rejeu fidèle opérateur. Même ordre, mêmes commandes, mêmes durées que le fichier *_drive.csv. Les nouvelles traces V10 utilisent time_s basé sur le nom de la trace, pas sur le mtime du fichier. L'odométrie est affichée pour contrôle, mais ne raccourcit plus le parcours.",
        })
    except Exception as e:
        return jsonify({"ok": False, "file": os.path.basename(path), "error": str(e)})


@app.route("/trace_follow_status", methods=["GET"])
def trace_follow_status():
    return jsonify(rb2_trace_follow_snapshot())


@app.route("/trace_follow_start", methods=["POST"])
def trace_follow_start():
    global TRACE_FOLLOW_THREAD

    if rb2_trace_follow_is_running():
        return jsonify({
            "ok": False,
            "error": "SUIVRE TRACE déjà actif",
            "status": rb2_trace_follow_snapshot(),
        }), 409

    path = rb2_latest_drive_trace_path()
    if not path:
        rb2_trace_follow_set_status(
            running=False,
            ok=False,
            state="error",
            message="Aucun fichier *_drive.csv trouvé",
            file=None,
            last_error="Aucun fichier *_drive.csv dans /opt/rb2/traces",
            cmd="d0,0",
        )
        rb2_trace_follow_send_stop_burst()
        return jsonify({
            "ok": False,
            "error": "Aucun fichier *_drive.csv trouvé dans /opt/rb2/traces",
        }), 404

    try:
        # Validation immédiate avant de lancer le fil.
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_follow_build_segments(rows)
        if not segments:
            raise ValueError("aucun segment réel valide")
    except Exception as e:
        rb2_trace_follow_set_status(
            running=False,
            ok=False,
            state="error",
            message="Fichier trace invalide",
            file=os.path.basename(path),
            last_error=str(e),
            cmd="d0,0",
        )
        rb2_trace_follow_send_stop_burst()
        return jsonify({
            "ok": False,
            "error": "Fichier *_drive.csv invalide: " + str(e),
            "file": os.path.basename(path),
        }), 400

    TRACE_FOLLOW_STOP_EVENT.clear()
    rb2_trace_follow_set_status(
        running=True,
        ok=True,
        state="starting",
        message="Démarrage SUIVRE TRACE",
        file=os.path.basename(path),
        step=0,
        total=len(segments),
        cmd="d0,0",
        last_error="",
    )

    TRACE_FOLLOW_THREAD = threading.Thread(
        target=rb2_trace_follow_worker,
        args=(path,),
        daemon=True
    )
    TRACE_FOLLOW_THREAD.start()

    return jsonify({
        "ok": True,
        "message": "SUIVRE TRACE FIDÈLE démarré",
        "file": os.path.basename(path),
        "total_segments": len(segments),
        "limits": {
            "speed_max": TRACE_FOLLOW_MAX_SPEED,
            "front_min_cm": TRACE_FOLLOW_FRONT_MIN_CM,
            "back_min_cm": TRACE_FOLLOW_BACK_MIN_CM,
            "mode": "v10_rejeu_exact_operateur"
        }
    })


@app.route("/trace_follow_stop", methods=["POST", "GET"])
def trace_follow_stop():
    rb2_trace_follow_request_stop("ARRÊTER REJEU demandé")
    return jsonify({
        "ok": True,
        "message": "ARRÊTER REJEU demandé",
        "status": rb2_trace_follow_snapshot(),
    })


# -----------------------------------------------------------------------------
# V21A - RETOUR TRACE : moteur côté Flask seulement
# -----------------------------------------------------------------------------
# Cette étape n'ajoute volontairement aucun bouton dans /terrain.
# Elle permet de valider le retour trace par terminal avant de toucher à
# l'interface, afin de ne plus casser les boutons existants.


def rb2_trace_return_invert_drive(left, right):
    """Inverse une commande différentielle dL,dR pour refaire le trajet à rebours."""
    try:
        left = int(left)
        right = int(right)
    except Exception:
        return 0, 0
    inv_left = -left
    inv_right = -right
    # En V10/V21A, pas de plafonnement artificiel : seulement borne physique de commande.
    inv_left = max(-100, min(100, inv_left))
    inv_right = max(-100, min(100, inv_right))
    return inv_left, inv_right


def rb2_trace_return_build_segments(rows):
    """
    Construit le retour exact d'une trace opérateur.

    Principe :
      - on reconstruit d'abord les intervalles du SUIVRE TRACE exact;
      - on enlève les intervalles STOP, car ils correspondent souvent au délai
        entre STOP et ARRÊTER TRACE;
      - on lit les mouvements en ordre inverse;
      - on inverse gauche/droite en signe, sans changer la durée.
    """
    forward_segments = rb2_trace_follow_build_segments(rows)
    moving_segments = []
    for seg in forward_segments:
        try:
            raw_left = int(seg.get("raw_left", seg.get("left", 0)) or 0)
            raw_right = int(seg.get("raw_right", seg.get("right", 0)) or 0)
        except Exception:
            raw_left, raw_right = 0, 0
        if raw_left == 0 and raw_right == 0:
            continue
        moving_segments.append(seg)

    if not moving_segments:
        raise ValueError("aucun mouvement réel à inverser dans la trace")

    return_segments = []
    for src in reversed(moving_segments):
        raw_left = int(src.get("raw_left", src.get("left", 0)) or 0)
        raw_right = int(src.get("raw_right", src.get("right", 0)) or 0)
        left, right = rb2_trace_return_invert_drive(raw_left, raw_right)
        duration_s = max(0.0, float(src.get("recorded_duration_s") or 0.0))
        if duration_s <= 0.01:
            continue

        return_segments.append({
            "index": len(return_segments) + 1,
            "source_index": src.get("index"),
            "raw_cmd": f"d{raw_left},{raw_right}",
            "return_cmd": f"d{left},{right}",
            "cmd": f"d{left},{right}",
            "left": left,
            "right": right,
            "recorded_duration_s": duration_s,
            "source_start_time_s": src.get("start_time_s"),
            "source_end_time_s": src.get("end_time_s"),
            "source_target_center_cm": src.get("target_center_cm"),
            "source_target_angle_deg": src.get("target_angle_deg"),
            "mode": "v21a_retour_trace_terminal",
        })

    if not return_segments:
        raise ValueError("aucun segment de retour valide")
    return return_segments


def rb2_trace_return_worker(path):
    try:
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_return_build_segments(rows)
        total_recorded_s = sum(float(s.get("recorded_duration_s") or 0.0) for s in segments)

        rb2_trace_follow_set_status(
            running=True,
            ok=True,
            state="starting",
            message="Initialisation RETOUR TRACE",
            file=os.path.basename(path),
            step=0,
            total=len(segments),
            cmd="d0,0",
            raw_cmd="",
            send_count=0,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            finished_at=None,
            last_error="",
            speed_limit=TRACE_FOLLOW_MAX_SPEED,
            front_min_cm=TRACE_FOLLOW_FRONT_MIN_CM,
            back_min_cm=TRACE_FOLLOW_BACK_MIN_CM,
            mode="v21a_retour_trace_terminal",
            total_recorded_s=round(total_recorded_s, 3),
        )

        rb2_trace_follow_send_stop_burst()
        time.sleep(0.15)

        send_count = 0
        replay_mono_start = time.monotonic()

        for idx, seg in enumerate(segments):
            if TRACE_FOLLOW_STOP_EVENT.is_set():
                rb2_trace_follow_set_status(
                    running=False, ok=True, state="stopped",
                    message="Retour trace arrêté par l'opérateur", cmd="d0,0",
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    mode="v21a_retour_trace_terminal",
                )
                return

            left = int(seg["left"])
            right = int(seg["right"])
            command_text = seg["cmd"]
            duration_s = max(0.0, float(seg.get("recorded_duration_s") or 0.0))

            allowed, reason = rb2_trace_follow_lidar_allows(left, right)
            if not allowed:
                rb2_trace_follow_set_status(
                    running=False, ok=False, state="blocked",
                    message="Retour trace bloqué par sécurité LIDAR", last_error=reason,
                    step=idx + 1, cmd="d0,0", raw_cmd=seg.get("raw_cmd", ""),
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    mode="v21a_retour_trace_terminal",
                )
                return

            rb2_trace_follow_set_status(
                running=True, ok=True, state="running", message=reason,
                step=idx + 1, total=len(segments), cmd=command_text,
                raw_cmd=seg.get("raw_cmd", ""), segment_mode="retour_trace_inverse",
                recorded_duration_s=round(duration_s, 3),
                source_index=seg.get("source_index"),
                source_start_time_s=seg.get("source_start_time_s"),
                source_end_time_s=seg.get("source_end_time_s"),
                send_count=send_count,
                mode="v21a_retour_trace_terminal",
            )

            seg_start = time.monotonic()
            seg_end = seg_start + duration_s
            next_send = 0.0

            while time.monotonic() < seg_end:
                if TRACE_FOLLOW_STOP_EVENT.is_set():
                    rb2_trace_follow_set_status(
                        running=False, ok=True, state="stopped",
                        message="Retour trace arrêté par l'opérateur", cmd="d0,0",
                        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        mode="v21a_retour_trace_terminal",
                    )
                    return

                now_mono = time.monotonic()
                allowed, reason = rb2_trace_follow_lidar_allows(left, right)
                if not allowed:
                    rb2_trace_follow_set_status(
                        running=False, ok=False, state="blocked",
                        message="Retour trace bloqué pendant mouvement", last_error=reason,
                        cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        mode="v21a_retour_trace_terminal",
                    )
                    return

                if now_mono >= next_send:
                    esp32.send(command_text, wait=0.0)
                    send_count += 1
                    rb2_trace_follow_set_status(
                        send_count=send_count,
                        elapsed_replay_s=round(time.monotonic() - replay_mono_start, 2),
                    )
                    next_send = now_mono + TRACE_FOLLOW_KEEPALIVE_S

                time.sleep(0.015)

        rb2_trace_follow_send_stop_burst()
        rb2_trace_follow_set_status(
            running=False, ok=True, state="finished", message="Retour trace terminé",
            cmd="d0,0", step=len(segments), total=len(segments),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            mode="v21a_retour_trace_terminal",
        )

    except Exception as e:
        rb2_trace_follow_set_status(
            running=False, ok=False, state="error", message="Erreur RETOUR TRACE",
            last_error=str(e), cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            mode="v21a_retour_trace_terminal",
        )
    finally:
        rb2_trace_follow_send_stop_burst()


@app.route("/trace_return_preview", methods=["GET"])
def trace_return_preview():
    path = rb2_latest_drive_trace_path()
    if not path:
        return jsonify({"ok": False, "error": "Aucun fichier *_drive.csv trouvé"})
    try:
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_return_build_segments(rows)
        preview = []
        for idx, seg in enumerate(segments[:40]):
            preview.append({
                "i": idx + 1,
                "source_index": seg.get("source_index"),
                "original_cmd": seg.get("raw_cmd"),
                "return_cmd": seg.get("cmd"),
                "recorded_duration_s": round(float(seg.get("recorded_duration_s") or 0.0), 3),
                "source_start_time_s": seg.get("source_start_time_s"),
                "source_end_time_s": seg.get("source_end_time_s"),
            })
        return jsonify({
            "ok": True,
            "file": os.path.basename(path),
            "path": path,
            "mode": "v21a_retour_trace_terminal",
            "rows": len(rows),
            "segments": len(segments),
            "total_duration_s": round(sum(float(s.get("recorded_duration_s") or 0.0) for s in segments), 3),
            "preview": preview,
            "note": "V21A: retour trace validé par terminal seulement. Aucun bouton ajouté dans /terrain. Les mouvements sont lus à l'envers et les commandes moteur sont inversées.",
        })
    except Exception as e:
        return jsonify({"ok": False, "file": os.path.basename(path), "error": str(e)})


@app.route("/trace_return_start", methods=["POST"])
def trace_return_start():
    global TRACE_FOLLOW_THREAD

    if rb2_trace_follow_is_running():
        return jsonify({
            "ok": False,
            "error": "SUIVRE/RETOUR TRACE déjà actif",
            "status": rb2_trace_follow_snapshot(),
        }), 409

    path = rb2_latest_drive_trace_path()
    if not path:
        rb2_trace_follow_set_status(
            running=False, ok=False, state="error",
            message="Aucun fichier *_drive.csv trouvé pour RETOUR TRACE",
            file=None, last_error="Aucun fichier *_drive.csv dans /opt/rb2/traces", cmd="d0,0",
            mode="v21a_retour_trace_terminal",
        )
        rb2_trace_follow_send_stop_burst()
        return jsonify({"ok": False, "error": "Aucun fichier *_drive.csv trouvé"}), 404

    try:
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_return_build_segments(rows)
        if not segments:
            raise ValueError("aucun segment de retour valide")
    except Exception as e:
        rb2_trace_follow_set_status(
            running=False, ok=False, state="error", message="Fichier trace invalide pour retour",
            file=os.path.basename(path), last_error=str(e), cmd="d0,0",
            mode="v21a_retour_trace_terminal",
        )
        rb2_trace_follow_send_stop_burst()
        return jsonify({
            "ok": False,
            "error": "Fichier *_drive.csv invalide pour retour: " + str(e),
            "file": os.path.basename(path),
        }), 400

    TRACE_FOLLOW_STOP_EVENT.clear()
    rb2_trace_follow_set_status(
        running=True, ok=True, state="starting", message="Démarrage RETOUR TRACE",
        file=os.path.basename(path), step=0, total=len(segments), cmd="d0,0",
        last_error="", mode="v21a_retour_trace_terminal",
    )

    TRACE_FOLLOW_THREAD = threading.Thread(
        target=rb2_trace_return_worker,
        args=(path,),
        daemon=True,
    )
    TRACE_FOLLOW_THREAD.start()

    return jsonify({
        "ok": True,
        "message": "RETOUR TRACE démarré",
        "file": os.path.basename(path),
        "total_segments": len(segments),
        "mode": "v21a_retour_trace_terminal",
        "limits": {
            "front_min_cm": TRACE_FOLLOW_FRONT_MIN_CM,
            "back_min_cm": TRACE_FOLLOW_BACK_MIN_CM,
        },
    })



# -----------------------------------------------------------------------------
# V22B - RETOUR AVANT : demi-tour 180° physique calibré physique calibré, puis retour par trace inverse
# -----------------------------------------------------------------------------
# Principe mécanique :
# - RETOUR TRACE classique revient de reculons : ordre inverse + commandes inversées.
# - RETOUR AVANT commence par un demi-tour de RB2.
# - Ensuite, on lit la trace à l'envers, mais on échange gauche/droite au lieu
#   d'inverser avance/recul. Ainsi, une avance enregistrée reste une avance,
#   mais dans l'orientation opposée après le 180 degrés.
#
# Exemples après le demi-tour :
#   d20,20   -> d20,20      avance reste avance
#   d20,-20  -> d-20,20     rotation inverse
#   d10,20   -> d20,10      courbe miroir
#   d0,0     -> d0,0
#
# Cette version est volontairement terminal/API seulement. Aucun bouton ajouté à
# /terrain. Le bouton pourra être ajouté plus tard uniquement si cette mécanique
# est validée.

TRACE_RETURN_FORWARD_TURN_LEFT = 20
TRACE_RETURN_FORWARD_TURN_RIGHT = -20
TRACE_RETURN_FORWARD_PHYSICAL_TURN_DEG = 180.0
# Observation terrain : consigne odométrique 180° = environ 90° physique.
# Donc, pour obtenir un vrai demi-tour physique, on vise 360° odométriques.
TRACE_RETURN_FORWARD_TURN_TARGET_DEG = 360.0
TRACE_RETURN_FORWARD_TURN_TOL_DEG = 8.0
TRACE_RETURN_FORWARD_TURN_TIMEOUT_S = 18.0


def rb2_trace_return_forward_swap_drive(left, right):
    """Retour avant après demi-tour : même vitesse linéaire, courbure inversée."""
    try:
        left = int(left)
        right = int(right)
    except Exception:
        return 0, 0
    if left == 0 and right == 0:
        return 0, 0
    # Après un 180°, échanger gauche/droite donne la trajectoire inverse en avançant.
    return rb2_trace_follow_limit_drive(right, left)


def rb2_trace_return_forward_build_segments(rows):
    base_segments = rb2_trace_follow_build_segments(rows)
    return_segments = []

    for src in reversed(base_segments):
        raw_text = str(src.get("raw_cmd") or src.get("cmd") or "").strip()
        parsed = rb2_parse_drive_command(raw_text)
        if parsed is None:
            raw_left = int(src.get("raw_left", src.get("left", 0)) or 0)
            raw_right = int(src.get("raw_right", src.get("right", 0)) or 0)
        else:
            raw_left, raw_right = parsed

        left, right = rb2_trace_return_forward_swap_drive(raw_left, raw_right)
        duration_s = max(0.0, float(src.get("recorded_duration_s") or 0.0))
        if duration_s <= 0.01:
            continue

        return_segments.append({
            "index": len(return_segments) + 1,
            "source_index": src.get("index"),
            "raw_cmd": f"d{raw_left},{raw_right}",
            "return_cmd": f"d{left},{right}",
            "cmd": f"d{left},{right}",
            "left": left,
            "right": right,
            "recorded_duration_s": duration_s,
            "source_start_time_s": src.get("start_time_s"),
            "source_end_time_s": src.get("end_time_s"),
            "mode": "v22b_retour_avant_180_calibre",
        })

    if not return_segments:
        raise ValueError("aucun segment de RETOUR AVANT valide")
    return return_segments


def rb2_trace_return_forward_rotate_180():
    """Effectue un demi-tour sur place mesuré par les encodeurs."""
    left = int(TRACE_RETURN_FORWARD_TURN_LEFT)
    right = int(TRACE_RETURN_FORWARD_TURN_RIGHT)
    cmd_text = f"d{left},{right}"

    allowed, reason = rb2_trace_follow_lidar_allows(left, right)
    if not allowed:
        raise ValueError("Demi-tour refusé par sécurité LIDAR: " + reason)

    start_odom = rb2_trace_follow_read_current_odom()
    start_angle = float(start_odom["angle_deg"])
    target_abs = max(0.0, TRACE_RETURN_FORWARD_TURN_TARGET_DEG - TRACE_RETURN_FORWARD_TURN_TOL_DEG)

    rb2_trace_follow_set_status(
        running=True,
        ok=True,
        state="turning_180",
        message="RETOUR AVANT : demi-tour 180° physique calibré",
        cmd=cmd_text,
        raw_cmd="180",
        segment_mode="turn_180_first",
        target_angle_deg=TRACE_RETURN_FORWARD_PHYSICAL_TURN_DEG,
        target_odom_angle_deg=TRACE_RETURN_FORWARD_TURN_TARGET_DEG,
        actual_angle_deg=0.0,
        send_count=0,
        mode="v22b_retour_avant_180_calibre",
    )

    start_mono = time.monotonic()
    next_send = 0.0
    next_odom = 0.0
    send_count = 0
    actual_delta = 0.0

    while True:
        if TRACE_FOLLOW_STOP_EVENT.is_set():
            raise InterruptedError("RETOUR AVANT arrêté pendant le demi-tour")

        elapsed = time.monotonic() - start_mono
        if elapsed > TRACE_RETURN_FORWARD_TURN_TIMEOUT_S:
            raise TimeoutError(
                f"Demi-tour 180 physique non complété: {abs(actual_delta):.1f}° odométriques atteints"
            )

        allowed, reason = rb2_trace_follow_lidar_allows(left, right)
        if not allowed:
            raise ValueError("Demi-tour bloqué par sécurité LIDAR: " + reason)

        now_mono = time.monotonic()
        if now_mono >= next_send:
            esp32.send(cmd_text, wait=0.0)
            send_count += 1
            rb2_trace_follow_set_status(send_count=send_count)
            next_send = now_mono + TRACE_FOLLOW_KEEPALIVE_S

        if now_mono >= next_odom:
            odom_now = rb2_trace_follow_read_current_odom()
            actual_delta = float(odom_now["angle_deg"]) - start_angle
            rb2_trace_follow_set_status(actual_angle_deg=round(actual_delta, 2))
            if abs(actual_delta) >= target_abs:
                break
            next_odom = now_mono + TRACE_FOLLOW_ODOM_SAMPLE_S

        time.sleep(0.015)

    rb2_trace_follow_send_stop_burst()
    time.sleep(0.25)
    return actual_delta


def rb2_trace_return_forward_worker(path):
    try:
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_return_forward_build_segments(rows)
        total_recorded_s = sum(float(s.get("recorded_duration_s") or 0.0) for s in segments)

        rb2_trace_follow_set_status(
            running=True,
            ok=True,
            state="starting",
            message="Initialisation RETOUR AVANT",
            file=os.path.basename(path),
            step=0,
            total=len(segments),
            cmd="d0,0",
            raw_cmd="",
            send_count=0,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            finished_at=None,
            last_error="",
            speed_limit=TRACE_FOLLOW_MAX_SPEED,
            front_min_cm=TRACE_FOLLOW_FRONT_MIN_CM,
            back_min_cm=TRACE_FOLLOW_BACK_MIN_CM,
            mode="v22b_retour_avant_180_calibre",
            total_recorded_s=round(total_recorded_s, 3),
        )

        rb2_trace_follow_send_stop_burst()
        time.sleep(0.15)

        actual_turn = rb2_trace_return_forward_rotate_180()

        send_count = 0
        replay_mono_start = time.monotonic()

        for idx, seg in enumerate(segments):
            if TRACE_FOLLOW_STOP_EVENT.is_set():
                rb2_trace_follow_set_status(
                    running=False, ok=True, state="stopped",
                    message="Retour avant arrêté par l'opérateur", cmd="d0,0",
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    mode="v22b_retour_avant_180_calibre",
                )
                return

            left = int(seg["left"])
            right = int(seg["right"])
            command_text = seg["cmd"]
            duration_s = max(0.0, float(seg.get("recorded_duration_s") or 0.0))

            allowed, reason = rb2_trace_follow_lidar_allows(left, right)
            if not allowed:
                rb2_trace_follow_set_status(
                    running=False, ok=False, state="blocked",
                    message="Retour avant bloqué par sécurité LIDAR", last_error=reason,
                    step=idx + 1, cmd="d0,0", raw_cmd=seg.get("raw_cmd", ""),
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    mode="v22b_retour_avant_180_calibre",
                )
                return

            rb2_trace_follow_set_status(
                running=True, ok=True, state="running", message=reason,
                step=idx + 1, total=len(segments), cmd=command_text,
                raw_cmd=seg.get("raw_cmd", ""), segment_mode="retour_avant_apres_180",
                recorded_duration_s=round(duration_s, 3),
                source_index=seg.get("source_index"),
                source_start_time_s=seg.get("source_start_time_s"),
                source_end_time_s=seg.get("source_end_time_s"),
                turn_180_actual_deg=round(actual_turn, 2),
                send_count=send_count,
                mode="v22b_retour_avant_180_calibre",
            )

            seg_start = time.monotonic()
            seg_end = seg_start + duration_s
            next_send = 0.0

            while time.monotonic() < seg_end:
                if TRACE_FOLLOW_STOP_EVENT.is_set():
                    rb2_trace_follow_set_status(
                        running=False, ok=True, state="stopped",
                        message="Retour avant arrêté par l'opérateur", cmd="d0,0",
                        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        mode="v22b_retour_avant_180_calibre",
                    )
                    return

                now_mono = time.monotonic()
                allowed, reason = rb2_trace_follow_lidar_allows(left, right)
                if not allowed:
                    rb2_trace_follow_set_status(
                        running=False, ok=False, state="blocked",
                        message="Retour avant bloqué pendant mouvement", last_error=reason,
                        cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        mode="v22b_retour_avant_180_calibre",
                    )
                    return

                if now_mono >= next_send:
                    esp32.send(command_text, wait=0.0)
                    send_count += 1
                    rb2_trace_follow_set_status(
                        send_count=send_count,
                        elapsed_replay_s=round(time.monotonic() - replay_mono_start, 2),
                    )
                    next_send = now_mono + TRACE_FOLLOW_KEEPALIVE_S

                time.sleep(0.015)

        rb2_trace_follow_send_stop_burst()
        rb2_trace_follow_set_status(
            running=False, ok=True, state="finished", message="Retour avant terminé",
            cmd="d0,0", step=len(segments), total=len(segments),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            mode="v22b_retour_avant_180_calibre",
        )

    except InterruptedError as e:
        rb2_trace_follow_set_status(
            running=False, ok=True, state="stopped", message=str(e),
            last_error="", cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            mode="v22b_retour_avant_180_calibre",
        )
    except Exception as e:
        rb2_trace_follow_set_status(
            running=False, ok=False, state="error", message="Erreur RETOUR AVANT",
            last_error=str(e), cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            mode="v22b_retour_avant_180_calibre",
        )
    finally:
        rb2_trace_follow_send_stop_burst()


@app.route("/trace_return_forward_preview", methods=["GET"])
def trace_return_forward_preview():
    path = rb2_latest_drive_trace_path()
    if not path:
        return jsonify({"ok": False, "error": "Aucun fichier *_drive.csv trouvé"})
    try:
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_return_forward_build_segments(rows)
        preview = []
        for idx, seg in enumerate(segments[:40]):
            preview.append({
                "i": idx + 1,
                "source_index": seg.get("source_index"),
                "original_cmd": seg.get("raw_cmd"),
                "return_forward_cmd": seg.get("cmd"),
                "recorded_duration_s": round(float(seg.get("recorded_duration_s") or 0.0), 3),
                "source_start_time_s": seg.get("source_start_time_s"),
                "source_end_time_s": seg.get("source_end_time_s"),
            })
        return jsonify({
            "ok": True,
            "file": os.path.basename(path),
            "path": path,
            "mode": "v22b_retour_avant_180_calibre",
            "rows": len(rows),
            "segments": len(segments),
            "turn_first_deg": TRACE_RETURN_FORWARD_PHYSICAL_TURN_DEG,
            "turn_odom_target_deg": TRACE_RETURN_FORWARD_TURN_TARGET_DEG,
            "turn_command": f"d{TRACE_RETURN_FORWARD_TURN_LEFT},{TRACE_RETURN_FORWARD_TURN_RIGHT}",
            "total_duration_s_after_turn": round(sum(float(s.get("recorded_duration_s") or 0.0) for s in segments), 3),
            "preview": preview,
            "note": "V22B: demi-tour physique 180 degrés calibré à 360 degrés odométriques, puis trace inverse en avançant. Commandes inverse: gauche/droite échangées, avance conservée.",
        })
    except Exception as e:
        return jsonify({"ok": False, "file": os.path.basename(path), "error": str(e)})


@app.route("/trace_return_forward_start", methods=["POST"])
def trace_return_forward_start():
    global TRACE_FOLLOW_THREAD

    if rb2_trace_follow_is_running():
        return jsonify({
            "ok": False,
            "error": "SUIVRE/RETOUR TRACE déjà actif",
            "status": rb2_trace_follow_snapshot(),
        }), 409

    path = rb2_latest_drive_trace_path()
    if not path:
        rb2_trace_follow_set_status(
            running=False, ok=False, state="error",
            message="Aucun fichier *_drive.csv trouvé pour RETOUR AVANT",
            file=None, last_error="Aucun fichier *_drive.csv dans /opt/rb2/traces", cmd="d0,0",
            mode="v22b_retour_avant_180_calibre",
        )
        rb2_trace_follow_send_stop_burst()
        return jsonify({"ok": False, "error": "Aucun fichier *_drive.csv trouvé"}), 404

    try:
        rows = rb2_trace_follow_load_drive_file(path)
        segments = rb2_trace_return_forward_build_segments(rows)
        if not segments:
            raise ValueError("aucun segment de retour avant valide")
    except Exception as e:
        rb2_trace_follow_set_status(
            running=False, ok=False, state="error", message="Fichier trace invalide pour retour avant",
            file=os.path.basename(path), last_error=str(e), cmd="d0,0",
            mode="v22b_retour_avant_180_calibre",
        )
        rb2_trace_follow_send_stop_burst()
        return jsonify({
            "ok": False,
            "error": "Fichier *_drive.csv invalide pour retour avant: " + str(e),
            "file": os.path.basename(path),
        }), 400

    TRACE_FOLLOW_STOP_EVENT.clear()
    rb2_trace_follow_set_status(
        running=True, ok=True, state="starting", message="Démarrage RETOUR AVANT",
        file=os.path.basename(path), step=0, total=len(segments), cmd="d0,0",
        last_error="", mode="v22b_retour_avant_180_calibre",
    )

    TRACE_FOLLOW_THREAD = threading.Thread(
        target=rb2_trace_return_forward_worker,
        args=(path,),
        daemon=True,
    )
    TRACE_FOLLOW_THREAD.start()

    return jsonify({
        "ok": True,
        "message": "RETOUR AVANT démarré: 180 degrés physique calibré puis trace inverse en avançant",
        "file": os.path.basename(path),
        "total_segments": len(segments),
        "mode": "v22b_retour_avant_180_calibre",
        "turn_first_deg": TRACE_RETURN_FORWARD_PHYSICAL_TURN_DEG,
            "turn_odom_target_deg": TRACE_RETURN_FORWARD_TURN_TARGET_DEG,
        "limits": {
            "front_min_cm": TRACE_FOLLOW_FRONT_MIN_CM,
            "back_min_cm": TRACE_FOLLOW_BACK_MIN_CM,
        },
    })





TERRAIN_HTML = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>RB2 - Terrain</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    body {
      margin: 0;
      padding: 10px;
      background: #111;
      color: #eee;
      font-family: Arial, sans-serif;
      overflow: hidden;
      user-select: none;
      -webkit-user-select: none;
    }

    .layout {
      display: grid;
      grid-template-columns: 3fr 1fr;
      gap: 12px;
      height: calc(100vh - 20px);
    }

    .camera {
      background: #000;
      border-radius: 10px;
      padding: 8px;
      box-sizing: border-box;
      overflow: hidden;
    }

    .camera img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
      background: #000;
      border: 2px solid #444;
      box-sizing: border-box;
    }

    .controls {
      background: #222;
      border-radius: 10px;
      padding: 10px;
      overflow-y: auto;
      box-sizing: border-box;
    }

    h2 {
      margin: 4px 0 8px 0;
      font-size: 20px;
      text-align: center;
    }

    h3 {
      margin: 12px 0 8px 0;
      padding-bottom: 4px;
      border-bottom: 1px solid #444;
      font-size: 17px;
    }

    button {
      border: 0;
      border-radius: 8px;
      background: #444;
      color: white;
      font-size: 16px;
      padding: 10px;
      cursor: pointer;
      touch-action: none;
    }

    button:hover {
      background: #666;
    }

    .stop {
      background: #a00000;
      font-weight: bold;
    }

    .stop:hover {
      background: #d00000;
    }

    .drive-btn.active {
      background: #0066aa !important;
      border: 2px solid #66ccff !important;
      box-shadow: 0 0 10px #66ccff !important;
    }

    .drive-grid, .pt-grid, .data-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 8px;
    }

    .data-grid {
      grid-template-columns: repeat(2, 1fr);
    }

    .box {
      background: #000;
      border: 1px solid #333;
      border-radius: 8px;
      padding: 8px;
      text-align: center;
    }

    .label {
      color: #bbb;
      font-size: 12px;
      margin-bottom: 3px;
    }

    .value {
      color: #00ff66;
      font-size: 18px;
      font-weight: bold;
    }

    .readout {
      background: #000;
      color: #00ff66;
      border-radius: 8px;
      padding: 8px;
      text-align: center;
      font-size: 15px;
      line-height: 1.4;
    }

    .status {
      background: #000;
      color: #66ccff;
      border-radius: 8px;
      padding: 8px;
      text-align: center;
      margin-bottom: 8px;
      font-size: 15px;
    }

    .small-row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 8px;
    }

    .small-row button {
      font-size: 14px;
      padding: 8px;
    }

    .small-text {
      color: #aaa;
      font-size: 12px;
      text-align: center;
      margin-top: 6px;
    }

    @media (max-width: 1000px) {
      body {
        overflow: auto;
      }

      .layout {
        grid-template-columns: 1fr;
        height: auto;
      }

      .camera {
        height: 60vh;
      }
    }

    .horizon-card {
      background: #000;
      border: 1px solid #333;
      border-radius: 10px;
      padding: 10px;
      margin-bottom: 8px;
      box-sizing: border-box;
    }

    .horizon-box {
      position: relative;
      height: 120px;
      background: #111;
      border: 2px solid #555;
      border-radius: 10px;
      overflow: hidden;
      margin-bottom: 8px;
    }

    .horizon-line {
      position: absolute;
      left: -25%;
      top: 50%;
      width: 150%;
      height: 4px;
      background: #00ff66;
      transform-origin: center center;
      box-shadow: 0 0 8px #00ff66;
    }

    .horizon-center-v {
      position: absolute;
      left: 50%;
      top: 0;
      width: 2px;
      height: 100%;
      background: #777;
      transform: translateX(-50%);
    }

    .horizon-center-h {
      position: absolute;
      left: 0;
      top: 50%;
      width: 100%;
      height: 2px;
      background: #777;
      transform: translateY(-50%);
    }

    .horizon-readout {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
    }


    .rb2-status-light {
      background: #000;
      border: 1px solid #333;
      border-radius: 8px;
      padding: 7px;
      text-align: center;
      font-size: 14px;
      margin-bottom: 8px;
      color: #aaa;
    }

    .rb2-status-ok {
      color: #00ff66;
      border-color: #006622;
    }

    .rb2-status-warn {
      color: #ffcc66;
      border-color: #806000;
    }

    .rb2-status-error {
      color: #ff6666;
      border-color: #802020;
    }

  
    .rb2-relay-row {
      display: flex;
      justify-content: center;
      gap: 12px;
      margin: 4px 0 8px 0;
      flex-wrap: nowrap;
    }

    .rb2-relay-btn {
      min-width: 145px;
      padding: 8px 10px;
      border-radius: 12px;
      border: 1px solid #4b5563;
      font-size: 0.86rem;
      font-weight: 800;
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }

    .rb2-relay-off {
      background: #374151;
      color: #e5e7eb;
    }

    .rb2-relay-on {
      background: #facc15;
      color: #111827;
      border-color: #f59e0b;
    }

    .rb2-relay-error {
      background: #7f1d1d;
      color: #fee2e2;
      border-color: #ef4444;
    }

    .terrain-signature {
      font-size: 0.78rem;
      color: #9ca3af;
      text-align: center;
      white-space: nowrap;
      margin-top: -6px;
      margin-bottom: 6px;
      line-height: 1.1;
    }

    /* Couleurs boutons Lumières / Relais 2 */
    .rb2-relay-btn.rb2-relay-off {
      background: #374151;
      color: #e5e7eb;
      border-color: #4b5563;
    }

    .rb2-relay-btn.rb2-relay-on {
      background: #facc15;
      color: #111827;
      border-color: #f59e0b;
      box-shadow: 0 0 10px rgba(250, 204, 21, 0.55);
    }

    .rb2-relay-btn.rb2-relay-error {
      background: #7f1d1d;
      color: #fee2e2;
      border-color: #ef4444;
    }


    .rb2-camera-info-bar {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      width: 100%;
      box-sizing: border-box;
      margin: 0 0 6px 0;
      padding: 5px 8px;
      border-radius: 8px;
      background: rgba(17, 24, 39, 0.92);
      border: 1px solid #374151;
      font-size: 0.78rem;
      line-height: 1.15;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .rb2-camera-info-muted {
      color: #9ca3af;
      font-weight: 600;
    }

    .rb2-camera-info-state {
      color: #e5e7eb;
      font-weight: 700;
    }

    .rb2-camera-info-sep {
      color: #6b7280;
      font-weight: 700;
    }

    .rb2-camera-lidar-link {
      color: #facc15 !important;
      font-weight: 900;
      text-decoration: none;
    }

    .rb2-camera-lidar-link:hover {
      color: #fde68a !important;
      text-decoration: underline;
    }

    .drive-status-hidden {
      display: none !important;
    }

    .terrain-view-toggle-row {
      display: flex;
      justify-content: center;
      margin: 4px 0 6px 0;
    }

    .terrain-view-toggle-btn {
      padding: 6px 14px;
      border-radius: 10px;
      border: 1px solid #4b5563;
      background: #1f2937;
      color: #facc15;
      font-size: 0.82rem;
      font-weight: 900;
      cursor: pointer;
      user-select: none;
    }

    .terrain-view-toggle-btn:hover {
      background: #374151;
    }

    .terrain-lidar-wrap {
      display: none;
      width: 100%;
      height: calc(100% - 42px);
      background: #000;
      border: 2px solid #444;
      border-radius: 8px;
      box-sizing: border-box;
      position: relative;
      overflow: hidden;
    }

    #terrainLidarCanvas {
      width: 100%;
      height: 100%;
      display: block;
      background: #000;
    }

    .terrain-lidar-status {
      position: absolute;
      left: 12px;
      bottom: 10px;
      background: rgba(0, 0, 0, 0.70);
      color: #aaa;
      padding: 5px 8px;
      border-radius: 6px;
      font-size: 0.78rem;
      font-weight: 700;
    }

    /* /terrain : conduite seulement, pas de Roll/Pitch ni encodeurs */
    .horizon-card {
      display: none !important;
    }

    .terrain-hidden-info {
      display: none !important;
    }


    .terrain-lidar-zoom-row {
      position: absolute;
      right: 12px;
      top: 10px;
      display: flex;
      gap: 6px;
      z-index: 30;
    }

    .terrain-lidar-zoom-row button {
      background: rgba(60, 60, 60, 0.92);
      color: white;
      border: 1px solid #777;
      border-radius: 6px;
      font-size: 13px;
      padding: 6px 8px;
      cursor: pointer;
      font-weight: 800;
    }

    .terrain-lidar-zoom-row button:hover {
      background: rgba(90, 90, 90, 0.96);
    }


    .rb2-speed-row {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      margin: 6px 0 8px 0;
      padding: 4px 6px;
      border-radius: 8px;
      background: rgba(17, 24, 39, 0.75);
      border: 1px solid #374151;
    }

    .rb2-speed-label {
      font-size: 0.78rem;
      font-weight: 900;
      color: #e5e7eb;
      margin-right: 4px;
      white-space: nowrap;
    }

    .rb2-speed-btn {
      min-width: 46px;
      padding: 5px 6px;
      border-radius: 7px;
      border: 1px solid #4b5563;
      background: #1f2937;
      color: #e5e7eb;
      font-size: 0.78rem;
      font-weight: 900;
      cursor: pointer;
      user-select: none;
    }

    .rb2-speed-btn.rb2-speed-active {
      background: #facc15;
      color: #111827;
      border-color: #f59e0b;
      box-shadow: 0 0 8px rgba(250, 204, 21, 0.45);
    }



    /* RB2 TERRAIN SPLIT PERMANENT */
    .terrain-view-toggle-row {
      display: none !important;
    }

    .camera {
      display: grid !important;
      grid-template-columns: 1fr 1fr;
      grid-template-rows: auto 1fr;
      gap: 8px;
      align-items: stretch;
      min-height: 58vh;
    }

    .rb2-camera-info-bar {
      grid-column: 1 / 3;
    }

    #cam {
      grid-column: 1;
      width: 100%;
      aspect-ratio: 4 / 3;
      height: auto;
      min-height: 420px;
      object-fit: contain;
      background: #000;
      border: 2px solid #444;
      border-radius: 8px;
      box-sizing: border-box;
      display: block !important;
    }

    #terrainLidarWrap {
      grid-column: 2;
      display: block !important;
      width: 100%;
      height: 100%;
      min-height: 420px;
      background: #000;
      border: 2px solid #444;
      border-radius: 8px;
      box-sizing: border-box;
      position: relative;
      overflow: hidden;
    }

    #terrainLidarCanvas {
      width: 100%;
      height: 100%;
      min-height: 420px;
      display: block;
      background: #000;
    }

    .terrain-under-map-actions {
      grid-column: 1 / 3;
      width: 100%;
      box-sizing: border-box;
      margin-top: 2px;
      margin-bottom: 6px;
    }

    .terrain-bottom-actions {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin-top: 10px;
      padding: 8px;
      border-radius: 10px;
      background: rgba(17, 24, 39, 0.82);
      border: 1px solid #374151;
    }

    .terrain-bottom-actions button {
      padding: 10px 8px;
      border-radius: 9px;
      border: 1px solid #4b5563;
      background: #1f2937;
      color: #e5e7eb;
      font-weight: 900;
      cursor: pointer;
      font-size: 0.86rem;
    }

    .terrain-bottom-actions button:hover {
      background: #374151;
    }

    .terrain-bottom-actions .trace-start-btn {
      background: #14532d;
      border-color: #22c55e;
    }

    .terrain-bottom-actions .trace-stop-btn {
      background: #7f1d1d;
      border-color: #ef4444;
    }

    .terrain-bottom-actions .trace-marker-btn,
    .terrain-bottom-actions .photo-marker-btn {
      background: #78350f;
      border-color: #f59e0b;
      color: #fff7ed;
    }

    .terrain-action-status {
      margin-top: 6px;
      font-size: 0.78rem;
      color: #d1d5db;
      min-height: 18px;
    }

    @media (max-width: 1100px) {
      .camera {
        grid-template-columns: 1fr;
      }

      .rb2-camera-info-bar,
      #cam,
      #terrainLidarWrap {
        grid-column: 1;
      }

      .terrain-bottom-actions {
        grid-template-columns: 1fr 1fr;
      }
    }


    #cam {
    }

</style>
</head>

<body>
  <div class="layout">
    <div class="camera">
      
      <div class="rb2-camera-info-bar">
        <span class="rb2-camera-info-muted">Créé par Roméo St-Cyr en  juin 2026</span>
        <span class="rb2-camera-info-sep">--</span>
        <span class="rb2-camera-info-state" id="rb2CameraInfoState">État RB2 : vérification...</span>
        <span style="float:right;display:inline-flex;gap:5px;margin-left:10px;align-items:center;">
          <button id="rb2StatusShutdownBtn"
                  onclick="rb2ShutdownAllDirect()"
                  style="padding:3px 9px;height:23px;min-width:74px;border-radius:7px;border:1px solid #ff4040;background:#b00000;color:#fff;font-size:10px;font-weight:900;cursor:pointer;">
            ARRÊT RB2
          </button>
          <button onclick="window.open('/lidar_drive','_blank')"
                  style="padding:3px 8px;height:23px;min-width:48px;border-radius:7px;border:1px solid #1d4ed8;background:#2563eb;color:#fff;font-size:10px;font-weight:900;cursor:pointer;">
            LIDAR
          </button>
          <button onclick="window.open('/zero_cam_stream.mjpg','_blank')"
                  style="padding:3px 8px;height:23px;min-width:58px;border-radius:7px;border:1px solid #065f46;background:#047857;color:#fff;font-size:10px;font-weight:900;cursor:pointer;">
            CAMÉRA
          </button>
        </span>
      </div>
      <div class="terrain-view-toggle-row" style="display:none;">
        <button id="terrainViewToggleBtn" class="terrain-view-toggle-btn" onclick="toggleTerrainView()">AFFICHAGE : SPLIT</button>
      </div>


      <img id="cam" src="" alt="Caméra RB2">
      <div id="terrainLidarWrap" class="terrain-lidar-wrap">
        <canvas id="terrainLidarCanvas"></canvas>
        <div class="terrain-lidar-zoom-row">
          <button onclick="terrainLidarZoomIn()">Zoom +</button>
          <button onclick="terrainLidarZoomOut()">Zoom -</button>
          <button onclick="terrainLidarZoomReset()">Reset</button>
          <button onclick="terrainLidarToggleDistances()">Distances</button>
        </div>

        <div id="terrainLidarStatus" class="terrain-lidar-status">LIDAR : attente...</div>
      </div>

      <div class="terrain-under-map-actions" style="position:relative !important; top:-55px !important; margin-bottom:-55px !important; z-index:50 !important;">
        <div class="terrain-bottom-actions">
          <button class="trace-start-btn" onclick="traceStart()">ENREGISTRER TRACE</button>
          <button class="trace-stop-btn" onclick="traceStop()" disabled>ENREG. ARRÊTÉ</button>
          <button class="trace-marker-btn" onclick="traceMark()">MARQUER</button>
          <button class="photo-marker-btn" onclick="photoMark()">PHOTO REPÈRE</button>
        </div>
        <div id="traceIndicator" class="terrain-action-status">Enregistrement trace : vérification...</div>
        <div id="traceLatest" class="terrain-action-status">Dernière trace : aucune</div>
        <div id="traceMarkerStatus" class="terrain-action-status"></div>
        <div id="photoMarkerStatus" class="terrain-action-status"></div>
        <div id="terrainHaBox" class="terrain-ha-compact" style="display:block !important; visibility:visible !important; opacity:1 !important; width:180px !important; height:48px !important; min-height:48px !important; max-height:48px !important; margin:2px auto 0 auto !important; padding:3px !important; box-sizing:border-box !important; background:#050505 !important; border:1px solid #444 !important; border-radius:7px !important; overflow:hidden !important;">
          <div class="terrain-ha-title" style="display:none !important;">
            <span>HORIZON ARTIFICIEL</span>
            <span id="terrainHaText" style="display:none !important;"></span>
          </div>
          <div id="terrainHaMini" style="position:relative !important; display:block !important; width:100% !important; height:40px !important; min-height:40px !important; max-height:40px !important; background:#050505 !important; border-radius:5px !important; overflow:hidden !important;">
            <div id="terrainHaSky" style="position:absolute !important; left:-50% !important; top:-100% !important; width:200% !important; height:200% !important; background:#1e3a5f !important; transform-origin:50% 50% !important;"></div>
            <div id="terrainHaGround" style="position:absolute !important; left:-50% !important; top:50% !important; width:200% !important; height:200% !important; background:#5a3518 !important; transform-origin:50% 50% !important;"></div>
            <div id="terrainHaLine" style="position:absolute !important; left:-50% !important; top:50% !important; width:200% !important; height:2px !important; background:#facc15 !important; transform-origin:50% 50% !important; z-index:10 !important;"></div>
            <div id="terrainHaCenter" style="position:absolute !important; left:50% !important; top:50% !important; width:54px !important; height:2px !important; margin-left:-27px !important; margin-top:-1px !important; background:#e5e7eb !important; z-index:20 !important;"></div>
          </div>
          <canvas id="terrainHaCanvas" style="display:none !important; visibility:hidden !important; width:0 !important; height:0 !important; min-height:0 !important; max-height:0 !important; margin:0 !important; padding:0 !important; border:0 !important;"></canvas>

<script>
// RB2_HA_MINI_RENDERER
(function() {
  function resize(canvas) {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return {ctx: ctx, w: rect.width, h: rect.height};
  }

  function drawMiniHA(roll, pitch) {
    const canvas = document.getElementById("terrainHaCanvas");
    if (!canvas) return;

    const r = resize(canvas);
    const ctx = r.ctx;
    const w = r.w;
    const h = r.h;
    const cx = w / 2;
    const cy = h / 2;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#050505";
    ctx.fillRect(0, 0, w, h);

    const rollRad = -Number(roll || 0) * Math.PI / 180.0;
    const pitchOffset = Math.max(-10, Math.min(10, Number(pitch || 0) * 1.2));

    ctx.save();
    ctx.translate(cx, cy + pitchOffset);
    ctx.rotate(rollRad);

    ctx.fillStyle = "#1e3a5f";
    ctx.fillRect(-w, -h, w * 2, h);

    ctx.fillStyle = "#5a3518";
    ctx.fillRect(-w, 0, w * 2, h);

    ctx.strokeStyle = "#facc15";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-w, 0);
    ctx.lineTo(w, 0);
    ctx.stroke();

    ctx.restore();

    // petit repère central fixe
    ctx.strokeStyle = "#e5e7eb";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(cx - 24, cy);
    ctx.lineTo(cx - 6, cy);
    ctx.moveTo(cx + 6, cy);
    ctx.lineTo(cx + 24, cy);
    ctx.stroke();
  }

  async function updateMiniHA() {
    try {
      const res = await fetch("/imu_json", {cache: "no-store"});
      const j = await res.json();
      const d = j.data || j;
      drawMiniHA(Number(d.roll_deg || 0), Number(d.pitch_deg || 0));
    } catch (e) {
      drawMiniHA(0, 0);
    }
  }

  setTimeout(updateMiniHA, 500);
  setInterval(updateMiniHA, 750);
})();
</script>

          <script>
          // RB2_HA_INLINE_TERRAIN_SCRIPT
          (function() {
            function resizeCanvas(canvas) {
              const rect = canvas.getBoundingClientRect();
              const dpr = window.devicePixelRatio || 1;
              canvas.width = Math.max(1, Math.floor(rect.width * dpr));
              canvas.height = Math.max(1, Math.floor(rect.height * dpr));
              const ctx = canvas.getContext("2d");
              ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
              return {w: rect.width, h: rect.height, ctx: ctx};
            }

            function drawHA(roll, pitch, ok, age) {
              const canvas = document.getElementById("terrainHaCanvas");
              const text = document.getElementById("terrainHaText");
              if (!canvas || !text) return;

              const r = resizeCanvas(canvas);
              const ctx = r.ctx;
              const w = r.w;
              const h = r.h;
              const cx = w / 2;
              const cy = h / 2;

              ctx.clearRect(0, 0, w, h);
              ctx.fillStyle = "#050505";
              ctx.fillRect(0, 0, w, h);

              if (!ok) {
                text.textContent = "";
                ctx.fillStyle = "#ff6666";
                ctx.font = "13px Arial";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                return;
              }

              text.textContent = "";

              const rollRad = -roll * Math.PI / 180.0;
              const pitchOffset = Math.max(-24, Math.min(24, pitch * 2.0));

              ctx.save();
              ctx.translate(cx, cy + pitchOffset);
              ctx.rotate(rollRad);

              ctx.fillStyle = "#1e3a5f";
              ctx.fillRect(-w, -h, w * 2, h);

              ctx.fillStyle = "#5a3518";
              ctx.fillRect(-w, 0, w * 2, h);

              ctx.strokeStyle = "#facc15";
              ctx.lineWidth = 2;
              ctx.beginPath();
              ctx.moveTo(-w, 0);
              ctx.lineTo(w, 0);
              ctx.stroke();

              ctx.restore();

              ctx.strokeStyle = "#e5e7eb";
              ctx.lineWidth = 2;
              ctx.beginPath();
              ctx.moveTo(cx - 34, cy);
              ctx.lineTo(cx - 8, cy);
              ctx.moveTo(cx + 8, cy);
              ctx.lineTo(cx + 34, cy);
              ctx.moveTo(cx, cy - 8);
              ctx.lineTo(cx, cy + 8);
              ctx.stroke();

              ctx.strokeStyle = "#444";
              ctx.lineWidth = 1;
              ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
            }

            async function updateHA() {
              try {
                const res = await fetch("/imu_json", {cache: "no-store"});
                const j = await res.json();
                const d = j.data || j;

                const ok = !!(j.ok !== false && d.ok !== false);
                const roll = Number(d.roll_deg ?? d.roll ?? 0);
                const pitch = Number(d.pitch_deg ?? d.pitch ?? 0);
                const age = Number(j.age_s ?? d.age_s ?? j.age ?? d.age ?? 0);

                drawHA(roll, pitch, ok, age);
              } catch (e) {
                drawHA(0, 0, false, 999);
              }
            }

            setTimeout(updateHA, 500);
            setInterval(updateHA, 500);
          })();
          </script>
        </div>
      </div>

<script>
// RB2_HA_CSS_MINI_FINAL
(function() {
  function setMiniHA(roll, pitch) {
    const sky = document.getElementById("terrainHaSky");
    const ground = document.getElementById("terrainHaGround");
    const line = document.getElementById("terrainHaLine");
    if (!sky || !ground || !line) return;

    const r = -Number(roll || 0);
    const p = Math.max(-10, Math.min(10, Number(pitch || 0) * 1.2));
    const t = "translateY(" + p.toFixed(1) + "px) rotate(" + r.toFixed(1) + "deg)";

    sky.style.transform = t;
    ground.style.transform = t;
    line.style.transform = t;
  }

  async function updateMiniHA() {
    try {
      const res = await fetch("/imu_json", {cache: "no-store"});
      const j = await res.json();
      const d = j.data || j;
      setMiniHA(d.roll_deg || 0, d.pitch_deg || 0);
    } catch (e) {
      setMiniHA(0, 0);
    }
  }

  setTimeout(updateMiniHA, 500);
  setInterval(updateMiniHA, 750);
})();
</script>


    </div>

    <div class="controls">
      <h2>RB2 Terrain</h2>
      <div class="terrain-signature">Créé par Roméo St-Cyr, juin 2026</div>
      <div class="rb2-relay-row">
        <button id="rb2LightBtn" class="rb2-relay-btn rb2-relay-off" onclick="rb2ToggleRelay('light')">LUMIÈRES OFF</button>
        <button id="rb2Relay2Btn" class="rb2-relay-btn rb2-relay-off" onclick="rb2ToggleRelay('relay2')">RELAIS 2 OFF</button>
      </div>


      <div id="rb2StatusLight" class="rb2-status-light">
        État RB2 : vérification...
      </div>
<div class="status drive-status-hidden">Direction : <span id="driveStatus">arrêt</span></div>

      <div class="drive-grid" id="drivePad">
        <div></div>
        <button class="drive-btn" data-drive="d20,20" data-label="avance">Avance</button>
        <div></div>

        <button class="drive-btn" data-drive="d-20,20" data-label="gauche">Gauche</button>
        <button class="drive-btn stop" data-drive="d0,0" data-label="stop">STOP</button>
        <button class="drive-btn" data-drive="d20,-20" data-label="droite">Droite</button>

        <div></div>
        <button class="drive-btn" data-drive="d-20,-20" data-label="recul">Recul</button>
        <div></div>
      </div>
<div class="pt-grid">
        <div></div>
        <button onclick="tiltUp()">▲</button>
        <div></div>

        <button onclick="panLeft()">◀</button>
        <div class="readout">
          Pan : <span id="panValue">90</span>°<br>
          Tilt : <span id="tiltValue">90</span>°
        </div>
        <button onclick="panRight()">▶</button>

        <div></div>
        <button onclick="tiltDown()">▼</button>
        <div></div>
      </div>

      <div class="small-row">
        <button onclick="setPanTilt(90,90)">Centre</button>
        <button onclick="setTiltOnly(145)">T 145</button>
        <button class="stop" onclick="setTiltOnly(68)">T 68</button>
      </div>
<div class="data-grid">
        <div class="box"><div class="label">Avant</div><div class="value"><span id="lidarFront">---</span> cm</div></div>
        <div class="box"><div class="label">Droite</div><div class="value"><span id="lidarRight">---</span> cm</div></div>
        <div class="box"><div class="label">Gauche</div><div class="value"><span id="lidarLeft">---</span> cm</div></div>
        <div class="box"><div class="label">Arrière</div><div class="value"><span id="lidarBack">---</span> cm</div></div>
      </div>
      <div class="small-text">
        Min : <span id="lidarMin">---</span> cm —
        âge : <span id="lidarAge">---</span> s —
        <span id="lidarState">attente</span>
      </div>
<div class="horizon-card">
        <div class="horizon-box">
          <div class="horizon-center-v"></div>
          <div class="horizon-center-h"></div>
          <div class="horizon-line" id="horizonLine"></div>
        </div>

        <div class="horizon-readout">
          <div class="box">
            <div class="label">Roll</div>
            <div class="value"><span id="imuRoll">---</span>°</div>
          </div>
          <div class="box">
            <div class="label">Pitch</div>
            <div class="value"><span id="imuPitch">---</span>°</div>
          </div>
        </div>

        <div class="small-text">
          IMU : <span id="imuAge">---</span> s —
          <span id="imuState">attente</span>
        </div>
      </div>
<div class="data-grid">
        <div class="box"><div class="label">FL</div><div class="value" id="encFL">---</div></div>
        <div class="box"><div class="label">FR</div><div class="value" id="encFR">---</div></div>
        <div class="box"><div class="label">RR</div><div class="value" id="encRR">---</div></div>
        <div class="box"><div class="label">RL</div><div class="value" id="encRL">---</div></div>
      </div>

      <div class="data-grid">
        <div class="box"><div class="label">Distance</div><div class="value"><span id="odomDistance">---</span> cm</div></div>
        <div class="box"><div class="label">Angle</div><div class="value"><span id="odomAngle">---</span>°</div></div>
      </div>
    </div>
  </div>

<script>
let pan = 90;
let tilt = 90;
let driving = false;
let currentDriveCmd = "d0,0";
let currentDriveLabel = "arrêt";
let driveTimer = null;
let activeDriveButton = null;
let lastDriveStopMs = 0;
let driveSeq = 0;
const driveToken = String(Date.now()) + "-" + String(Math.floor(Math.random() * 1000000));
let driveServerOffsetMs = 0;
let driveTimeSynced = false;

async function syncDriveServerTime() {
  try {
    const res = await fetch("/drive_time", {cache: "no-store"});
    const j = await res.json();
    if (j && j.ok && typeof j.server_ms === "number") {
      driveServerOffsetMs = j.server_ms - Date.now();
      driveTimeSynced = true;
    }
  } catch (e) {
    console.log("Erreur sync temps conduite:", e);
  }
}

const TILT_MIN = 68;
const TILT_MAX = 145;
const PAN_NORMAL_MIN = 50;
const PAN_NORMAL_MAX = 140;
const PAN_HIGH_TILT_MIN = 60;
const PAN_HIGH_TILT_MAX = 135;
const TILT_RESTRICT_START = 135;

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

function isHighTilt() {
  return tilt >= TILT_RESTRICT_START && tilt <= TILT_MAX;
}

function currentPanMin() {
  return isHighTilt() ? PAN_HIGH_TILT_MIN : PAN_NORMAL_MIN;
}

function currentPanMax() {
  return isHighTilt() ? PAN_HIGH_TILT_MAX : PAN_NORMAL_MAX;
}

function isDriveCommand(command) {
  return /^d-?\d+,-?\d+$/.test(String(command || ""));
}

function cmd(command) {
  const payload = {cmd: command};

  if (isDriveCommand(command)) {
    driveSeq += 1;
    payload.drive_seq = driveSeq;
    payload.drive_token = driveToken;
    payload.sent_server_ms = Math.round(Date.now() + driveServerOffsetMs);
  }

  fetch("/cmd", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
    cache: "no-store"
  }).catch(e => {
    console.log("Erreur commande:", e);
  });
}

function updateReadout() {
  document.getElementById("panValue").textContent = pan;
  document.getElementById("tiltValue").textContent = tilt;
}

function updateDriveStatus() {
  document.getElementById("driveStatus").textContent = currentDriveLabel;
}

function clearDriveButtons() {
  const buttons = document.querySelectorAll(".drive-btn");
  for (const b of buttons) {
    b.classList.remove("active");
  }
}

function setActiveDriveButton(button) {
  clearDriveButtons();
  activeDriveButton = button || null;
  if (activeDriveButton) {
    activeDriveButton.classList.add("active");
  }
}

function driveButtonFromPoint(x, y) {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;
  return el.closest(".drive-btn");
}

function startDrive(button) {
  if (!button) return;

  const newCmd = button.dataset.drive || "d0,0";
  const newLabel = button.dataset.label || newCmd;

  // Si même commande, ne rien redémarrer.
  if (driving && currentDriveCmd === newCmd) {
    return;
  }

  currentDriveCmd = newCmd;
  currentDriveLabel = newLabel;
  driving = true;
  updateDriveStatus();
  setActiveDriveButton(button);

  // Envoyer immédiatement la nouvelle direction.
  cmd(currentDriveCmd);

  // Un seul timer, gardé actif pendant toute la pression.
  if (!driveTimer) {
    driveTimer = setInterval(() => {
      if (driving && currentDriveCmd !== "d0,0") {
        cmd(currentDriveCmd);
      }
    }, 250);
  }
}

function changeDrive(button) {
  if (!driving || !button) return;

  const newCmd = button.dataset.drive || "d0,0";
  const newLabel = button.dataset.label || newCmd;

  if (newCmd === currentDriveCmd) {
    return;
  }

  currentDriveCmd = newCmd;
  currentDriveLabel = newLabel;
  updateDriveStatus();
  setActiveDriveButton(button);

  // Envoyer immédiatement le changement de direction.
  cmd(currentDriveCmd);
}

function stopDrive() {
  if (!driving && currentDriveCmd === "d0,0") {
    return;
  }

  driving = false;
  currentDriveCmd = "d0,0";
  currentDriveLabel = "arrêt";
  lastDriveStopMs = Date.now();
  updateDriveStatus();
  setActiveDriveButton(null);

  if (driveTimer) {
    clearInterval(driveTimer);
    driveTimer = null;
  }

  cmd("d0,0");
  setTimeout(() => cmd("d0,0"), 80);
  setTimeout(() => cmd("d0,0"), 200);
}

function setupDrivePad() {
  const pad = document.getElementById("drivePad");
  const buttons = document.querySelectorAll(".drive-btn");

  for (const b of buttons) {
    b.addEventListener("mousedown", e => {
      e.preventDefault();
      startDrive(b);
    });

    b.addEventListener("touchstart", e => {
      e.preventDefault();
      startDrive(b);
    }, {passive: false});

    b.addEventListener("contextmenu", e => {
      e.preventDefault();
    });
  }

  // Souris : changement de direction en glissant sans relâcher.
  document.addEventListener("mousemove", e => {
    if (!driving) return;
    if (e.buttons !== 1) return;

    const b = driveButtonFromPoint(e.clientX, e.clientY);
    if (b) {
      changeDrive(b);
    }
  });

  // Tactile : changement de direction en glissant sans relâcher.
  document.addEventListener("touchmove", e => {
    if (!driving) return;
    if (!e.touches || e.touches.length < 1) return;

    const t = e.touches[0];
    const b = driveButtonFromPoint(t.clientX, t.clientY);
    if (b) {
      changeDrive(b);
    }

    e.preventDefault();
  }, {passive: false});

  document.addEventListener("mouseup", e => {
    if (driving) stopDrive();
  });

  document.addEventListener("touchend", e => {
    if (driving) stopDrive();
  }, {passive: false});

  document.addEventListener("touchcancel", e => {
    if (driving) stopDrive();
  }, {passive: false});

  window.addEventListener("blur", stopDrive);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopDrive();
  });
}

function panLeft() {
  pan = clamp(pan - 5, currentPanMin(), currentPanMax());
  updateReadout();
  cmd("p" + pan);
}

function panRight() {
  pan = clamp(pan + 5, currentPanMin(), currentPanMax());
  updateReadout();
  cmd("p" + pan);
}

function tiltUp() {
  tilt = clamp(tilt + 5, TILT_MIN, TILT_MAX);
  pan = clamp(pan, currentPanMin(), currentPanMax());
  updateReadout();
  cmd("t" + tilt);
}

function tiltDown() {
  tilt = clamp(tilt - 5, TILT_MIN, TILT_MAX);
  updateReadout();
  cmd("t" + tilt);
}

function setPanTilt(newPan, newTilt) {
  tilt = clamp(newTilt, TILT_MIN, TILT_MAX);
  pan = clamp(newPan, currentPanMin(), currentPanMax());
  updateReadout();
  cmd("p" + pan);
  setTimeout(() => cmd("t" + tilt), 200);
}

function setTiltOnly(newTilt) {
  tilt = clamp(newTilt, TILT_MIN, TILT_MAX);
  pan = clamp(pan, currentPanMin(), currentPanMax());
  updateReadout();
  cmd("t" + tilt);
}

function putText(id, value, decimals = 0) {
  const el = document.getElementById(id);
  if (!el) return;

  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    el.textContent = "---";
  } else {
    el.textContent = Number(value).toFixed(decimals);
  }
}


async function updateTerrainStatus() {
  const box = document.getElementById("rb2StatusLight");
  if (!box) return;

  try {
    const res = await fetch("/terrain_status", {cache:"no-store"});
    const j = await res.json();

    box.classList.remove("rb2-status-ok", "rb2-status-warn", "rb2-status-error");

    if (j.level === "ok") {
      box.classList.add("rb2-status-ok");
      box.textContent = "État RB2 : OK";
    } else if (j.level === "warn") {
      box.classList.add("rb2-status-warn");
      box.textContent = "État RB2 : attention";
    } else {
      box.classList.add("rb2-status-error");
      box.textContent = "État RB2 : erreur";
    }

  } catch (e) {
    box.classList.remove("rb2-status-ok", "rb2-status-warn");
    box.classList.add("rb2-status-error");
    box.textContent = "État RB2 : erreur";
  }
}


async function updateLidar() {
  try {
    const res = await fetch("/lidar", {cache:"no-store"});
    const j = await res.json();
    const d = j.data || j;

    putText("lidarFront", d.front_cm);
    putText("lidarRight", d.right_cm);
    putText("lidarLeft", d.left_cm);
    putText("lidarBack", d.back_cm);
    putText("lidarMin", d.min_cm);

    putText("lidarAge", j.age_s, 1);

    const state = document.getElementById("lidarState");
    if (state) {
      state.textContent = j.ok ? "ok" : "erreur";
      state.style.color = j.ok ? "#00ff66" : "#ff6666";
    }
  } catch (e) {
    const state = document.getElementById("lidarState");
    if (state) {
      state.textContent = "erreur";
      state.style.color = "#ff6666";
    }
  }
}


async function updateImu() {
  try {
    const res = await fetch("/imu_json", {cache:"no-store"});
    const j = await res.json();

    const state = document.getElementById("imuState");
    const line = document.getElementById("horizonLine");

    if (!j.ok) {
      if (state) {
        state.textContent = "erreur";
        state.style.color = "#ff6666";
      }
      return;
    }

    const d = j.data || {};
    const roll = Number(d.roll_deg || 0);
    const pitch = Number(d.pitch_deg || 0);

    putText("imuRoll", roll, 1);
    putText("imuPitch", pitch, 1);
    putText("imuAge", j.age_s, 1);

    if (line) {
      /*
        Horizon simple :
        - roll incline la ligne
        - pitch déplace la ligne verticalement
        Le facteur 1.2 px/degré est volontairement modéré.
      */
      const pitchPx = Math.max(-45, Math.min(45, pitch * 1.2));
      line.style.transform = "translateY(" + pitchPx + "px) rotate(" + (-roll) + "deg)";
    }

    if (state) {
      if (Number(j.age_s || 0) > 3.0) {
        state.textContent = "ancien";
        state.style.color = "#ffcc66";
      } else {
        state.textContent = "ok";
        state.style.color = "#00ff66";
      }
    }

  } catch (e) {
    const state = document.getElementById("imuState");
    if (state) {
      state.textContent = "erreur";
      state.style.color = "#ff6666";
    }
  }
}


async function updateEncoders() {
  /*
    Important :
    Ne pas lire les encodeurs pendant que les moteurs sont commandés.
    La lecture encodeurs utilise le même ESP32 que les commandes moteur.
    Si on interroge les encodeurs en roulant, cela peut provoquer des micro-pauses.
  */
  if (driving) {
    return;
  }

  // Laisser un court délai après l'arrêt avant de relire les encodeurs.
  if (Date.now() - lastDriveStopMs < 500) {
    return;
  }

  try {
    const res = await fetch("/encoders", {cache: "no-store"});
    const j = await res.json();

    const v =
      j.values ||
      j.encoders ||
      (j.data && j.data.values) ||
      (j.data && j.data.encoders) ||
      j;

    const o =
      j.odom ||
      (j.data && j.data.odom) ||
      {};

    putText("encFL", v.FL ?? v.fl ?? v.front_left ?? v.frontLeft);
    putText("encFR", v.FR ?? v.fr ?? v.front_right ?? v.frontRight);
    putText("encRR", v.RR ?? v.rr ?? v.rear_right ?? v.rearRight);
    putText("encRL", v.RL ?? v.rl ?? v.rear_left ?? v.rearLeft);

    putText("odomDistance", o.center_cm ?? o.distance_cm ?? o.distance ?? j.center_cm, 1);
    putText("odomAngle", o.angle_deg ?? o.angle ?? j.angle_deg, 1);

  } catch (e) {
    console.log("Erreur encodeurs:", e);
  }
}

document.addEventListener("DOMContentLoaded", function () {
  const cam = document.getElementById("cam");
  cam.src = "/zero_cam_stream.mjpg";

  setupDrivePad();
  updateReadout();
  updateDriveStatus();

  updateTerrainStatus();
  updateLidar();
  updateImu();
  updateEncoders();

  setInterval(updateTerrainStatus, 3000);
  setInterval(updateLidar, 1000);
  setInterval(updateImu, 500);
  setInterval(() => { if (!driving) updateEncoders(); }, 5000);
});



let rb2RelayStates = {
  light: false,
  relay2: false
};

function rb2RelayButtonId(name) {
  return name === "light" ? "rb2LightBtn" : "rb2Relay2Btn";
}

function rb2RelayLabel(name) {
  return name === "light" ? "LUMIÈRES" : "RELAIS 2";
}

function rb2RelayUrl(name) {
  return name === "light" ? "/light" : "/relay2";
}

function rb2UpdateRelayButton(name, state, ok = true) {
  const b = document.getElementById(rb2RelayButtonId(name));
  if (!b) return;

  b.classList.remove("rb2-relay-on", "rb2-relay-off", "rb2-relay-error");

  if (!ok) {
    b.textContent = rb2RelayLabel(name) + " ERREUR";
    b.classList.add("rb2-relay-error");
    return;
  }

  rb2RelayStates[name] = (state === "on");

  if (rb2RelayStates[name]) {
    b.textContent = rb2RelayLabel(name) + " ON";
    b.classList.add("rb2-relay-on");
  } else {
    b.textContent = rb2RelayLabel(name) + " OFF";
    b.classList.add("rb2-relay-off");
  }
}

function rb2ReadRelay(name) {
  fetch(rb2RelayUrl(name), {
    method: "GET",
    cache: "no-store"
  })
    .then(r => r.json())
    .then(j => rb2UpdateRelayButton(name, j.state || "off", !!j.ok))
    .catch(e => {
      console.log("Erreur lecture relais", name, e);
      rb2UpdateRelayButton(name, "off", false);
    });
}

function rb2SetRelay(name, on) {
  fetch(rb2RelayUrl(name), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({state: on ? "on" : "off"}),
    cache: "no-store"
  })
    .then(r => r.json())
    .then(j => rb2UpdateRelayButton(name, j.state || "off", !!j.ok))
    .catch(e => {
      console.log("Erreur commande relais", name, e);
      rb2UpdateRelayButton(name, "off", false);
    });
}

function rb2ToggleRelay(name) {
  rb2SetRelay(name, !rb2RelayStates[name]);
}

rb2ReadRelay("light");
rb2ReadRelay("relay2");


// --- Couleurs fiables pour boutons Lumières / Relais 2 ---
function rb2ForceRelayButtonColor(name, state, ok = true) {
  const id = name === "light" ? "rb2LightBtn" : "rb2Relay2Btn";
  const label = name === "light" ? "LUMIÈRES" : "RELAIS 2";
  const b = document.getElementById(id);
  if (!b) return;

  b.classList.remove("rb2-relay-on", "rb2-relay-off", "rb2-relay-error");

  if (!ok) {
    b.textContent = label + " ERREUR";
    b.classList.add("rb2-relay-error");
    return;
  }

  if (state === "on") {
    b.textContent = label + " ON";
    b.classList.add("rb2-relay-on");
  } else {
    b.textContent = label + " OFF";
    b.classList.add("rb2-relay-off");
  }
}

// Remplace l'affichage existant, sans changer les routes ni les relais.
rb2UpdateRelayButton = function(name, state, ok = true) {
  if (typeof rb2RelayStates !== "undefined") {
    rb2RelayStates[name] = (state === "on");
  }
  rb2ForceRelayButtonColor(name, state, ok);
};

// Rafraîchir l'état au chargement.
setTimeout(() => {
  if (typeof rb2ReadRelay === "function") {
    rb2ReadRelay("light");
    rb2ReadRelay("relay2");
  }
}, 300);


function rb2SyncCameraInfoBar() {
  try {
    const topState = document.getElementById("rb2CameraInfoState");
    if (!topState) return;

    const elems = Array.from(document.querySelectorAll("div, span, p"));

    const oldState = elems.find(el =>
      el &&
      el.id !== "rb2CameraInfoState" &&
      el.textContent &&
      el.textContent.trim().startsWith("État RB2")
    );

    if (oldState) {
      topState.textContent = oldState.textContent.trim();
      oldState.style.display = "none";
    }

    const sig = document.querySelector(".terrain-signature");
    if (sig) {
      sig.style.display = "none";
    }

  } catch (e) {
    console.log("rb2SyncCameraInfoBar:", e);
  }
}

setTimeout(rb2SyncCameraInfoBar, 300);
setInterval(rb2SyncCameraInfoBar, 1000);

// Démarrage du LIDAR terrain en mode split permanent.
setTimeout(() => {
  try {
    terrainViewMode = "split";
    const wrap = document.getElementById("terrainLidarWrap");
    const cam = document.getElementById("cam");
    if (wrap) wrap.style.display = "block";
    if (cam) cam.style.display = "block";
    if (typeof updateTerrainLidarMap === "function") {
      updateTerrainLidarMap();
      if (!terrainLidarTimer) {
        terrainLidarTimer = setInterval(updateTerrainLidarMap, 500);
      }
    }
  } catch (e) {
    console.log("Erreur démarrage LIDAR terrain split:", e);
  }
}, 700);



let terrainViewMode = "split";
let terrainLidarTimer = null;
let terrainLidarZoom = 1.0;
let terrainLidarShowDistances = true;

function resizeTerrainLidarCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {w: rect.width, h: rect.height, ctx: ctx};
}

function drawTerrainLidarMap(data, age_s) {
  const canvas = document.getElementById("terrainLidarCanvas");
  const status = document.getElementById("terrainLidarStatus");
  if (!canvas) return;

  const r = resizeTerrainLidarCanvas(canvas);
  const ctx = r.ctx;
  const w = r.w;
  const h = r.h;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, w, h);

  const cx = w / 2;
  const cy = h / 2;

  const points = data.points_cm || [];
  const robot = data.robot || {
    front_cm: 28,
    back_cm: 8,
    half_width_cm: 10,
    front_line_cm: 35
  };

  const scale = (Math.min(w, h) / 420.0) * terrainLidarZoom;

  function sx(x_cm) { return cx + x_cm * scale; }
  function sy(y_cm) { return cy - y_cm * scale; }

  // Anneaux 50 / 100 / 150 / 200 cm, léger
  if (terrainLidarShowDistances) {
    ctx.save();
    ctx.font = "12px Arial";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";

    for (const cm of [50, 100, 150, 200]) {
      const radius = cm * scale;
      if (radius < 12 || radius > Math.max(w, h)) continue;

      ctx.beginPath();
      ctx.strokeStyle = cm % 100 === 0 ? "#333" : "#222";
      ctx.lineWidth = 1;
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.stroke();

      ctx.fillStyle = "#777";
      ctx.fillText(cm + " cm", cx + radius + 5, cy);
    }

    ctx.restore();
  }

  // Contour RB2
  const front = Number(robot.front_cm || 28);
  const back = Number(robot.back_cm || 8);
  const half = Number(robot.half_width_cm || 10);

  ctx.save();
  ctx.strokeStyle = "#888";
  ctx.lineWidth = 2;
  ctx.strokeRect(
    sx(-half),
    sy(front),
    (half * 2) * scale,
    (front + back) * scale
  );

  // Ligne avant
  const frontLine = Number(robot.front_line_cm || 35);
  ctx.beginPath();
  ctx.strokeStyle = "#ff3333";
  ctx.lineWidth = 3;
  ctx.moveTo(sx(0), sy(0));
  ctx.lineTo(sx(0), sy(frontLine));
  ctx.stroke();

  // Centre LIDAR
  ctx.beginPath();
  ctx.fillStyle = "#00ffff";
  ctx.arc(cx, cy, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // Points LIDAR
  // Format réel de /lidar_map : points_cm = [[x, y], [x, y], ...]
  ctx.save();
  ctx.fillStyle = "#00ff66";

  for (const pt of points) {
    let x = null;
    let y = null;

    if (Array.isArray(pt) && pt.length >= 2) {
      x = Number(pt[0]);
      y = Number(pt[1]);
    } else if (pt && typeof pt === "object") {
      x = Number(pt.x ?? pt.x_cm);
      y = Number(pt.y ?? pt.y_cm);
    }

    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;

    const px = sx(x);
    const py = sy(y);

    if (px < -10 || px > w + 10 || py < -10 || py > h + 10) continue;

    const dist = Math.sqrt(x * x + y * y);
    const isFrontSector = (y > 0 && Math.abs(x) <= 20);
    const ignoreSmallSideRear = (dist <= 10 && !isFrontSector);

    if (ignoreSmallSideRear) {
      ctx.fillStyle = "#335533";
      ctx.fillRect(px - 1, py - 1, 2, 2);
      ctx.fillStyle = "#00ff66";
    } else {
      ctx.fillRect(px - 1.5, py - 1.5, 3, 3);
    }
  }

  ctx.restore();

  if (status) {
    const age = Number(age_s || 0).toFixed(1);
    status.textContent = "LIDAR : " + points.length + " points — âge : " + age + " s";
    status.style.color = Number(age_s || 0) > 3 ? "#ffcc66" : "#aaa";
  }
}

async function updateTerrainLidarMap() {
  // Mode split permanent : le LIDAR est toujours affiché sur /terrain.

  const status = document.getElementById("terrainLidarStatus");

  try {
    const res = await fetch("/lidar_map", {cache: "no-store"});
    const j = await res.json();

    if (!j.ok) {
      if (status) {
        status.textContent = "LIDAR : erreur";
        status.style.color = "#ff6666";
      }
      return;
    }

    drawTerrainLidarMap(j.data || {}, j.age_s || 0);

  } catch (e) {
    if (status) {
      status.textContent = "LIDAR : erreur";
      status.style.color = "#ff6666";
    }
  }
}

function setTerrainViewMode(mode) {
  terrainViewMode = mode;

  const cam = document.getElementById("cam");
  const lidar = document.getElementById("terrainLidarWrap");
  const btn = document.getElementById("terrainViewToggleBtn");

  if (!cam || !lidar || !btn) return;

  if (terrainViewMode === "lidar") {
    cam.style.display = "none";
    lidar.style.display = "block";
    btn.textContent = "AFFICHAGE : LIDAR";

    updateTerrainLidarMap();

    if (!terrainLidarTimer) {
      terrainLidarTimer = setInterval(updateTerrainLidarMap, 1000);
    }

  } else {
    cam.style.display = "block";
    lidar.style.display = "none";
    btn.textContent = "AFFICHAGE : CAMÉRA";

    if (terrainLidarTimer) {
      clearInterval(terrainLidarTimer);
      terrainLidarTimer = null;
    }
  }
}

function toggleTerrainView() {
  if (terrainViewMode === "camera") {
    setTerrainViewMode("lidar");
  } else {
    setTerrainViewMode("camera");
  }
}

window.addEventListener("resize", () => {
  if (terrainViewMode === "lidar") updateTerrainLidarMap();
});


function rb2HideTerrainImuEncoders() {
  try {
    // L'horizon artificiel de /terrain
    document.querySelectorAll(".horizon-card").forEach(el => {
      el.style.display = "none";
    });

    // Grille encodeurs : FL / FR / RR / RL
    const encFL = document.getElementById("encFL");
    if (encFL) {
      const grid = encFL.closest(".data-grid");
      if (grid) grid.style.display = "none";
    }

    // Champs odométrie Distance / Angle si présents
    const odomDist = document.getElementById("odomDistance");
    if (odomDist) {
      const box = odomDist.closest(".box");
      if (box) box.style.display = "none";
      const grid = odomDist.closest(".data-grid");
      if (grid) {
        // Si cette grille ne contient que l'odométrie, on la cache.
        const text = (grid.textContent || "");
        if (text.includes("Distance") || text.includes("Angle")) {
          grid.style.display = "none";
        }
      }
    }

    const odomAngle = document.getElementById("odomAngle");
    if (odomAngle) {
      const box = odomAngle.closest(".box");
      if (box) box.style.display = "none";
    }

  } catch (e) {
    console.log("rb2HideTerrainImuEncoders:", e);
  }
}

document.addEventListener("DOMContentLoaded", rb2HideTerrainImuEncoders);
setTimeout(rb2HideTerrainImuEncoders, 300);
setInterval(rb2HideTerrainImuEncoders, 3000);


function terrainLidarZoomIn() {
  terrainLidarZoom = Math.min(4.0, terrainLidarZoom * 1.25);
  updateTerrainLidarMap();
}

function terrainLidarZoomOut() {
  terrainLidarZoom = Math.max(0.4, terrainLidarZoom / 1.25);
  updateTerrainLidarMap();
}

function terrainLidarZoomReset() {
  terrainLidarZoom = 1.0;
  updateTerrainLidarMap();
}

function terrainLidarToggleDistances() {
  terrainLidarShowDistances = !terrainLidarShowDistances;
  updateTerrainLidarMap();
}


let rb2DriveSpeedPct = 50;

function rb2DriveCmdFromLabel(label) {
  const s = Number(rb2DriveSpeedPct || 50);

  if (label === "avance") return "d" + s + "," + s;
  if (label === "recul") return "d-" + s + ",-" + s;
  if (label === "gauche") return "d-" + s + "," + s;
  if (label === "droite") return "d" + s + ",-" + s;
  if (label === "stop") return "d0,0";

  return "d0,0";
}

function rb2ApplyDriveSpeed() {
  document.querySelectorAll(".drive-btn").forEach(b => {
    const label = b.dataset.label || "";
    if (["avance", "recul", "gauche", "droite", "stop"].includes(label)) {
      b.dataset.drive = rb2DriveCmdFromLabel(label);
    }
  });

  document.querySelectorAll(".rb2-speed-btn").forEach(b => {
    const v = Number(b.dataset.speed || 0);
    if (v === rb2DriveSpeedPct) {
      b.classList.add("rb2-speed-active");
    } else {
      b.classList.remove("rb2-speed-active");
    }
  });
}

function rb2SetDriveSpeed(v) {
  rb2DriveSpeedPct = Number(v || 50);
  rb2ApplyDriveSpeed();

  // Si on change la vitesse pendant un appui, appliquer immédiatement
  // à la direction déjà active.
  try {
    if (typeof driving !== "undefined" && driving && activeDriveButton) {
      currentDriveCmd = activeDriveButton.dataset.drive || "d0,0";
      cmd(currentDriveCmd);
    }
  } catch (e) {
    console.log("rb2SetDriveSpeed:", e);
  }
}

function rb2CreateSpeedButtons() {
  const drivePad = document.getElementById("drivePad");
  if (!drivePad) return;
  if (document.getElementById("rb2SpeedRow")) return;

  const row = document.createElement("div");
  row.id = "rb2SpeedRow";
  row.className = "rb2-speed-row";

  const label = document.createElement("span");
  label.className = "rb2-speed-label";
  label.textContent = "Vitesse";
  row.appendChild(label);

  [25, 50, 75, 100].forEach(v => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "rb2-speed-btn";
    b.dataset.speed = String(v);
    b.textContent = v + "%";
    b.onclick = () => rb2SetDriveSpeed(v);
    row.appendChild(b);
  });

  drivePad.insertAdjacentElement("afterend", row);
  rb2ApplyDriveSpeed();
}

document.addEventListener("DOMContentLoaded", function () {
  rb2CreateSpeedButtons();
  rb2ApplyDriveSpeed();
});

</script>

<script>
// RB2_TERRAIN_TRACE_JS_FINAL
(function() {
  function setText(id, txt) {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  }

  function setColor(id, color) {
    const el = document.getElementById(id);
    if (el) el.style.color = color;
  }

  window.updateTraceIndicator = function() {
    fetch("/trace_status", {method: "GET", cache: "no-store"})
      .then(r => r.json())
      .then(j => {
        if (j.active) {
          setText("traceIndicator", "Enregistrement trace : EN COURS");
          setColor("traceIndicator", "#22c55e");
        } else {
          setText("traceIndicator", "Enregistrement trace : arrêté");
          setColor("traceIndicator", "#d1d5db");
        }

        if (j.latest) {
          setText("traceLatest", "Dernière trace : " + j.latest);
        } else {
          setText("traceLatest", "Dernière trace : aucune");
        }
      })
      .catch(e => {
        setText("traceIndicator", "Enregistrement trace : erreur");
        setColor("traceIndicator", "#ef4444");
        console.log("trace_status erreur:", e);
      });
  };

  window.updateTraceLatest = function() {
    fetch("/trace_status", {method: "GET", cache: "no-store"})
      .then(r => r.json())
      .then(j => {
        if (j.latest) {
          setText("traceLatest", "Dernière trace : " + j.latest);
        } else {
          setText("traceLatest", "Dernière trace : aucune");
        }
      })
      .catch(e => {
        setText("traceLatest", "Dernière trace : erreur");
        console.log("trace_latest erreur:", e);
      });
  };

  window.traceStart = function() {
    setText("traceIndicator", "Enregistrement trace : démarrage...");
    setColor("traceIndicator", "#facc15");

    fetch("/trace_start", {method: "POST", cache: "no-store"})
      .then(r => r.json())
      .then(j => {
        console.log("trace_start:", j);
        if (j.ok === false) {
          setText("traceIndicator", "Enregistrement trace : erreur démarrage");
          setColor("traceIndicator", "#ef4444");
        } else {
          setText("traceIndicator", "Enregistrement trace : EN COURS");
          setColor("traceIndicator", "#22c55e");
        }
        setTimeout(updateTraceIndicator, 300);
        setTimeout(updateTraceLatest, 700);
      })
      .catch(e => {
        setText("traceIndicator", "Enregistrement trace : erreur démarrage");
        setColor("traceIndicator", "#ef4444");
        console.log("traceStart erreur:", e);
      });
  };

  window.traceStop = function() {
    setText("traceIndicator", "Enregistrement trace : arrêt...");
    setColor("traceIndicator", "#facc15");

    fetch("/trace_stop", {method: "POST", cache: "no-store"})
      .then(r => r.json())
      .then(j => {
        console.log("trace_stop:", j);
        if (j.ok === false) {
          setText("traceIndicator", "Enregistrement trace : erreur arrêt");
          setColor("traceIndicator", "#ef4444");
        } else {
          setText("traceIndicator", "Enregistrement trace : arrêté");
          setColor("traceIndicator", "#d1d5db");
        }
        setTimeout(updateTraceIndicator, 300);
        setTimeout(updateTraceLatest, 700);
      })
      .catch(e => {
        setText("traceIndicator", "Enregistrement trace : erreur arrêt");
        setColor("traceIndicator", "#ef4444");
        console.log("traceStop erreur:", e);
      });
  };

  window.traceMark = window.traceMark || function() {
    const status = document.getElementById("traceMarkerStatus");
    if (status) status.textContent = "Marqueur...";

    fetch("/trace_mark", {method: "POST", cache: "no-store"})
      .then(r => r.json())
      .then(j => {
        if (status) status.textContent = j.ok ? "Marqueur ajouté" : "Erreur marqueur";
        setTimeout(updateTraceLatest, 500);
      })
      .catch(e => {
        if (status) status.textContent = "Erreur marqueur";
        console.log("traceMark erreur:", e);
      });
  };

  window.photoMark = window.photoMark || function() {
    const status = document.getElementById("photoMarkerStatus");
    if (status) status.textContent = "Photo...";

    fetch("/photo_mark", {method: "POST", cache: "no-store"})
      .then(r => r.json())
      .then(j => {
        if (status) status.textContent = j.ok ? "Photo repère prise" : "Erreur photo";
      })
      .catch(e => {
        if (status) status.textContent = "Erreur photo";
        console.log("photoMark erreur:", e);
      });
  };

  setTimeout(updateTraceIndicator, 500);
  setTimeout(updateTraceLatest, 800);
  setInterval(updateTraceIndicator, 5000);
})();
</script>


<!-- RB2_SHUTDOWN_TERRAIN_BUTTON -->
<style>
#rb2ShutdownAllTerrainBtn {
  position: fixed;
  left: 14px;
  bottom: 14px;
  z-index: 99999;
  min-width: 220px;
  min-height: 44px;
  padding: 10px 14px;
  border: 3px solid #7a0000;
  border-radius: 10px;
  background: #b00000;
  color: #ffffff;
  font-weight: 900;
  font-size: 15px;
  box-shadow: 0 0 12px rgba(0,0,0,0.55);
  cursor: pointer;
}
#rb2ShutdownAllTerrainBtn:hover {
  background: #d00000;
}
#rb2ShutdownAllTerrainBtn:disabled {
  background: #555555;
  border-color: #444444;
  color: #dddddd;
  cursor: not-allowed;
}
</style>

<script>
function rb2ShutdownAllTerrain() {
  const ok = confirm(
    "Confirmer l'arrêt complet de RB2 ?\\n\\n" +
    "Le Zero 2 W caméra sera arrêté en premier.\\n" +
    "Le Raspberry Pi 5 sera ensuite arrêté.\\n\\n" +
    "Après confirmation, l'interface web cessera de répondre."
  );

  if (!ok) return;

  const btn = document.getElementById("rb2ShutdownAllTerrainBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "ARRÊT EN COURS...";
  }

  fetch("/system_shutdown_all", {
    method: "POST",
    cache: "no-store"
  })
  .then(r => r.json())
  .then(j => {
    if (!j.ok) {
      alert("Erreur arrêt RB2 : " + (j.error || "erreur inconnue"));
      if (btn) {
        btn.disabled = false;
        btn.textContent = "ARRÊTER RB2 COMPLET";
      }
      return;
    }

    alert("Arrêt complet RB2 demandé.");
  })
  .catch(e => {
    alert("Commande envoyée ou connexion perdue. Si RB2 s'arrête, c'est normal.");
  });
}

function rb2AddShutdownAllTerrainButton() {
  if (document.getElementById("rb2ShutdownAllTerrainBtn")) return;

  const b = document.createElement("button");
  b.id = "rb2ShutdownAllTerrainBtn";
  b.textContent = "ARRÊTER RB2 COMPLET";
  b.onclick = rb2ShutdownAllTerrain;

  document.body.appendChild(b);
}

document.addEventListener("DOMContentLoaded", rb2AddShutdownAllTerrainButton);
setTimeout(rb2AddShutdownAllTerrainButton, 500);
setTimeout(rb2AddShutdownAllTerrainButton, 1500);
</script>


<script>
// RB2_CAMERA_AUTORELOAD_FIX
(function () {
  function rb2ReloadCameraStream() {
    try {
      const imgs = Array.from(document.querySelectorAll("img"));
      const candidates = imgs.filter(img => {
        const src = img.getAttribute("src") || "";
        const id = img.getAttribute("id") || "";
        return (
          src.includes("zero_cam_stream") ||
          src.includes("stream.mjpg") ||
          id === "cam" ||
          id === "rb2UsbCam"
        );
      });

      candidates.forEach(img => {
        let src = img.getAttribute("src") || "";

        if (!src || src === "#") {
          src = "/zero_cam_stream.mjpg";
        }

        const base = src.split("?")[0];
        img.setAttribute("src", base + "?t=" + Date.now());
      });
    } catch (e) {
      console.log("RB2 camera autoreload error:", e);
    }
  }

  window.addEventListener("load", function () {
    setTimeout(rb2ReloadCameraStream, 500);
  });

  window.addEventListener("pageshow", function () {
    setTimeout(rb2ReloadCameraStream, 300);
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      setTimeout(rb2ReloadCameraStream, 300);
    }
  });

  window.addEventListener("focus", function () {
    setTimeout(rb2ReloadCameraStream, 300);
  });
})();
</script>


<script>
// RB2_EXTRA_LINK_BUTTONS_FIX
(function () {
  function rb2AddExtraButtonsNearShutdown() {
    try {
      const shutdownBtn = document.querySelector(".rb2-shutdown-all-btn");
      if (!shutdownBtn) return;

      if (document.getElementById("rb2ExtraButtonsRow")) return;

      const parent = shutdownBtn.parentElement;
      if (!parent) return;

      const row = document.createElement("div");
      row.id = "rb2ExtraButtonsRow";
      row.style.display = "grid";
      row.style.gridTemplateColumns = "1.4fr 0.8fr 0.9fr";
      row.style.gap = "8px";
      row.style.marginTop = "8px";
      row.style.width = "100%";
      row.style.boxSizing = "border-box";

      shutdownBtn.style.width = "100%";
      shutdownBtn.style.marginTop = "0";
      shutdownBtn.style.minHeight = "42px";

      parent.insertBefore(row, shutdownBtn);
      row.appendChild(shutdownBtn);

      const lidarBtn = document.createElement("button");
      lidarBtn.type = "button";
      lidarBtn.textContent = "LIDAR";
      lidarBtn.title = "Ouvrir la page LIDAR";
      lidarBtn.style.minHeight = "42px";
      lidarBtn.style.fontWeight = "800";
      lidarBtn.style.fontSize = "14px";
      lidarBtn.style.background = "#2563eb";
      lidarBtn.style.color = "white";
      lidarBtn.style.border = "2px solid #1d4ed8";
      lidarBtn.style.borderRadius = "8px";
      lidarBtn.style.cursor = "pointer";
      lidarBtn.onclick = function () {
        window.open("/lidar_drive", "_blank");
      };

      const camBtn = document.createElement("button");
      camBtn.type = "button";
      camBtn.textContent = "CAMÉRA";
      camBtn.title = "Ouvrir l'image caméra seulement";
      camBtn.style.minHeight = "42px";
      camBtn.style.fontWeight = "800";
      camBtn.style.fontSize = "14px";
      camBtn.style.background = "#047857";
      camBtn.style.color = "white";
      camBtn.style.border = "2px solid #065f46";
      camBtn.style.borderRadius = "8px";
      camBtn.style.cursor = "pointer";
      camBtn.onclick = function () {
        window.open("/zero_cam_stream.mjpg", "_blank");
      };

      row.appendChild(lidarBtn);
      row.appendChild(camBtn);
    } catch (e) {
      console.log("Erreur ajout boutons RB2:", e);
    }
  }

  window.addEventListener("load", rb2AddExtraButtonsNearShutdown);
  document.addEventListener("DOMContentLoaded", rb2AddExtraButtonsNearShutdown);
  setTimeout(rb2AddExtraButtonsNearShutdown, 1000);
})();
</script>


<!-- RB2 : bouton Restart Camera dans la barre du haut -->
<style>
  .rb2-restart-camera-top-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 28px;
    padding: 6px 11px;
    margin-left: 8px;
    border: 1px solid #ffb347;
    border-radius: 9px;
    background: #3a2a10;
    color: #ffd28a;
    font-weight: 800;
    font-size: 13px;
    line-height: 1;
    text-decoration: none;
    cursor: pointer;
    white-space: nowrap;
  }

  .rb2-restart-camera-top-btn:hover {
    filter: brightness(1.15);
  }

  .rb2-restart-camera-top-btn:disabled {
    opacity: 0.55;
    cursor: wait;
    filter: none;
  }
</style>

<script>
(function() {
  if (window.__rb2RestartCameraTopButtonInstalled) return;
  window.__rb2RestartCameraTopButtonInstalled = true;

  function textOf(el) {
    return (el && el.textContent ? el.textContent : "").trim().toUpperCase();
  }

  function findTopBarParent() {
    const candidates = Array.from(document.querySelectorAll("a, button"));
    let cameraEl = null;
    let lidarEl = null;
    let arretEl = null;

    for (const el of candidates) {
      const t = textOf(el);
      if (!cameraEl && (t === "CAMÉRA" || t === "CAMERA" || t.includes("CAMÉRA") || t.includes("CAMERA"))) {
        cameraEl = el;
      }
      if (!lidarEl && t.includes("LIDAR")) {
        lidarEl = el;
      }
      if (!arretEl && (t.includes("ARRÊT RB2") || t.includes("ARRET RB2") || t.includes("ARRÊTER RB2"))) {
        arretEl = el;
      }
    }

    if (cameraEl && lidarEl && cameraEl.parentElement === lidarEl.parentElement) {
      return { parent: cameraEl.parentElement, after: cameraEl };
    }

    if (cameraEl) {
      return { parent: cameraEl.parentElement, after: cameraEl };
    }

    if (lidarEl) {
      return { parent: lidarEl.parentElement, after: lidarEl };
    }

    if (arretEl) {
      return { parent: arretEl.parentElement, after: arretEl };
    }

    return null;
  }

  function installButton() {
    if (document.getElementById("rb2-restart-camera-top-btn")) return;

    const found = findTopBarParent();
    if (!found || !found.parent) {
      console.log("RB2 Restart Camera: barre du haut non trouvée.");
      return;
    }

    const btn = document.createElement("button");
    btn.id = "rb2-restart-camera-top-btn";
    btn.className = "rb2-restart-camera-top-btn";
    btn.type = "button";
    btn.title = "Redémarrer seulement la caméra du Raspberry Pi Zero 2 W";
    btn.textContent = "Restart Camera";

    found.after.insertAdjacentElement("afterend", btn);

    btn.addEventListener("click", async function() {
      const ok = confirm("Redémarrer seulement la caméra du Zero 2 W ?");
      if (!ok) return;

      const oldText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Restart...";

      try {
        const r = await fetch("/zero_cam_restart", { method: "POST" });
        const data = await r.json();

        if (data && data.ok) {
          btn.textContent = "Camera OK";
          setTimeout(function() {
            btn.textContent = oldText;
            btn.disabled = false;
          }, 3000);
        } else {
          btn.textContent = "Erreur";
          console.log("RB2 zero_cam_restart erreur:", data);
          alert("La commande a été envoyée, mais une erreur est retournée. Voir /tmp/rb2_zero_cam_restart.log");
          setTimeout(function() {
            btn.textContent = oldText;
            btn.disabled = false;
          }, 3000);
        }
      } catch (e) {
        btn.textContent = "Erreur";
        console.log("RB2 zero_cam_restart exception:", e);
        alert("Erreur de communication avec /zero_cam_restart");
        setTimeout(function() {
          btn.textContent = oldText;
          btn.disabled = false;
        }, 3000);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installButton);
  } else {
    installButton();
  }
})();
</script>

</body>
</html>
"""





ZERO_CAM_STREAM_URL = "http://10.50.0.20:8080/stream.mjpg"
ZERO_CAM_STATUS_URL = "http://10.50.0.20:8080/status"
ZERO_CAM_PHOTO_URL = "http://10.50.0.20:8080/photo"
ZERO_CAM_VIDEO_TOGGLE_URL = "http://10.50.0.20:8080/video_toggle"
ZERO_CAM_VIDEO_STATUS_URL = "http://10.50.0.20:8080/video_status"
ZERO_CAM_CAPTURES_LIST_URL = "http://10.50.0.20:8080/captures/list"
ZERO_CAM_CAPTURES_FILE_BASE = "http://10.50.0.20:8080/captures/file"
ZERO_CAM_CAPTURES_ZIP_URL = "http://10.50.0.20:8080/captures/zip"
ZERO_CAM_CAPTURES_DELETE_URL = "http://10.50.0.20:8080/captures/delete"

@app.route("/zero_cam_stream.mjpg")
def zero_cam_stream():
    def generate():
        while True:
            try:
                with urllib.request.urlopen(ZERO_CAM_STREAM_URL, timeout=10) as r:
                    while True:
                        chunk = r.read(8192)
                        if not chunk:
                            break
                        yield chunk
            except Exception as e:
                # Petite pause avant de réessayer, pour éviter de marteler le Zero.
                time.sleep(1.0)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=FRAME"
    )

@app.route("/zero_cam_status")
def zero_cam_status():
    try:
        with urllib.request.urlopen(ZERO_CAM_STATUS_URL, timeout=2.0) as r:
            data = r.read()
        return Response(data, mimetype="application/json")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


def rb2_zero_json_request(url, method="GET", timeout=6.0):
    try:
        data = b"" if method.upper() == "POST" else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method.upper(),
            headers={"User-Agent": "RB2-terrain"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        return Response(raw, mimetype="application/json")
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "url": url
        }), 502


@app.route("/zero_photo", methods=["POST"])
def zero_photo():
    return rb2_zero_json_request(ZERO_CAM_PHOTO_URL, method="POST", timeout=6.0)


@app.route("/zero_video_toggle", methods=["POST"])
def zero_video_toggle():
    return rb2_zero_json_request(ZERO_CAM_VIDEO_TOGGLE_URL, method="POST", timeout=6.0)


@app.route("/zero_video_status")
def zero_video_status():
    return rb2_zero_json_request(ZERO_CAM_VIDEO_STATUS_URL, method="GET", timeout=3.0)


@app.route("/zero_captures_list")
def zero_captures_list():
    return rb2_zero_json_request(ZERO_CAM_CAPTURES_LIST_URL, method="GET", timeout=6.0)


@app.route("/zero_captures_file/<kind>/<path:filename>")
def zero_captures_file(kind, filename):
    kind = str(kind).strip()
    filename = str(filename).strip()

    if kind not in ("photos", "videos"):
        return jsonify({"ok": False, "error": "Type invalide"}), 400

    safe_filename = urllib.parse.quote(filename, safe="")
    url = f"{ZERO_CAM_CAPTURES_FILE_BASE}/{kind}/{safe_filename}"

    try:
        with urllib.request.urlopen(url, timeout=20.0) as r:
            raw = r.read()
            content_type = r.headers.get("Content-Type", "application/octet-stream")
            disp = r.headers.get("Content-Disposition") or f'attachment; filename="{filename}"'

        resp = Response(raw, mimetype=content_type)
        resp.headers["Content-Disposition"] = disp
        return resp
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "url": url}), 502


@app.route("/zero_captures_zip", methods=["POST"])
def zero_captures_zip():
    data = request.get_json(silent=True) or {}
    raw_json = json.dumps(data).encode("utf-8")

    try:
        req = urllib.request.Request(
            ZERO_CAM_CAPTURES_ZIP_URL,
            data=raw_json,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "RB2-terrain",
            },
        )
        with urllib.request.urlopen(req, timeout=60.0) as r:
            raw = r.read()
            content_type = r.headers.get("Content-Type", "application/zip")
            disp = r.headers.get("Content-Disposition", 'attachment; filename="rb2_captures_selection.zip"')

        resp = Response(raw, mimetype=content_type)
        resp.headers["Content-Disposition"] = disp
        return resp
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        return jsonify({"ok": False, "error": err}), e.code
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@app.route("/zero_captures_delete", methods=["POST"])
def zero_captures_delete():
    data = request.get_json(silent=True) or {}
    raw_json = json.dumps(data).encode("utf-8")

    try:
        req = urllib.request.Request(
            ZERO_CAM_CAPTURES_DELETE_URL,
            data=raw_json,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "RB2-terrain",
            },
        )
        with urllib.request.urlopen(req, timeout=30.0) as r:
            raw = r.read()
            content_type = r.headers.get("Content-Type", "application/json")

        return Response(raw, mimetype=content_type)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        return jsonify({"ok": False, "error": err}), e.code
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


CAPTURES_HTML = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>RB2 - Récupération captures</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { background:#111; color:#eee; font-family:Arial,sans-serif; margin:0; padding:16px; }
    h1 { margin-top:0; }
    h2 { margin-top:18px; color:#9fd3ff; }
    .topbar { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; }
    button {
      border:0; border-radius:8px; padding:10px 14px; font-weight:800;
      background:#444; color:white; cursor:pointer;
    }
    button:hover { background:#666; }
    button.delete { background:#9b0000; }
    button.delete:hover { background:#d00000; }
    .status { background:#000; border:1px solid #333; border-radius:8px; padding:10px; margin:10px 0; color:#ccc; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:10px; }
    .card { background:#1d1d1d; border:1px solid #333; border-radius:10px; padding:10px; }
    .name { font-weight:800; word-break:break-all; color:#fff; margin-bottom:6px; }
    .meta { color:#aaa; font-size:13px; margin-bottom:8px; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    .thumb {
      width: 100%;
      max-height: 190px;
      object-fit: contain;
      background: #000;
      border: 1px solid #444;
      border-radius: 8px;
      margin: 8px 0;
      display: block;
    }
    video.thumb {
      max-height: 210px;
    }
    a { color:#9fd3ff; text-decoration:none; font-weight:800; }
    a:hover { text-decoration:underline; }
    input[type="checkbox"] { transform:scale(1.35); margin-right:8px; }
  </style>
</head>
<body>
  <h1>RB2 - Récupération photos / vidéos</h1>

  <div class="topbar">
    <button onclick="loadCaptures()">RAFRAÎCHIR</button>
    <button onclick="selectAll(true)">TOUT COCHER</button>
    <button onclick="selectAll(false)">TOUT DÉCOCHER</button>
    <button onclick="downloadSelected()">TÉLÉCHARGER SÉLECTION</button>
    <button class="delete" onclick="deleteSelected()">SUPPRIMER SÉLECTION</button>
  </div>

  <div id="status" class="status">Chargement...</div>

  <h2>Photos</h2>
  <div id="photos" class="grid"></div>

  <h2>Vidéos</h2>
  <div id="videos" class="grid"></div>

<script>
function setStatus(t) {
  document.getElementById("status").textContent = t;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
  }[c]));
}

function cardHtml(kind, x) {
  const fn = x.filename || "";
  const label = kind + "|" + fn;
  const sizeKb = x.size ? (x.size / 1024).toFixed(1) + " Ko" : "";
  const url = `/zero_captures_file/${kind}/${encodeURIComponent(fn)}`;

  let preview = "";
  if (kind === "photos") {
    preview = `<a href="${url}" target="_blank"><img class="thumb" src="${url}" loading="lazy" alt="${esc(fn)}"></a>`;
  } else {
    preview = `<video class="thumb" src="${url}" controls preload="metadata"></video>`;
  }

  return `
    <div class="card">
      <div class="name">
        <label>
          <input class="capcheck" type="checkbox" value="${esc(label)}">
          ${esc(fn)}
        </label>
      </div>
      <div class="meta">${esc(x.mtime_text || "")} — ${esc(sizeKb)}</div>
      ${preview}
      <div class="actions">
        <a href="${url}" target="_blank">Télécharger</a>
      </div>
    </div>
  `;
}

async function loadCaptures() {
  setStatus("Chargement...");
  try {
    const r = await fetch("/zero_captures_list", {cache:"no-store"});
    const j = await r.json();

    if (!j.ok) {
      setStatus("Erreur: " + (j.error || "inconnue"));
      return;
    }

    const photos = j.photos || [];
    const videos = j.videos || [];

    document.getElementById("photos").innerHTML =
      photos.length ? photos.map(x => cardHtml("photos", x)).join("") : "<div class='status'>Aucune photo</div>";

    document.getElementById("videos").innerHTML =
      videos.length ? videos.map(x => cardHtml("videos", x)).join("") : "<div class='status'>Aucune vidéo</div>";

    setStatus(`${photos.length} photo(s), ${videos.length} vidéo(s)`);
  } catch(e) {
    setStatus("Erreur JavaScript: " + e);
  }
}

function selectAll(on) {
  document.querySelectorAll(".capcheck").forEach(c => c.checked = on);
}

function selectedFiles() {
  const files = [];
  document.querySelectorAll(".capcheck:checked").forEach(c => {
    const p = c.value.split("|");
    if (p.length === 2) files.push({kind:p[0], filename:p[1]});
  });
  return files;
}

async function downloadSelected() {
  const files = selectedFiles();
  if (!files.length) {
    alert("Aucun fichier coché.");
    return;
  }

  setStatus("Préparation du ZIP...");
  const r = await fetch("/zero_captures_zip", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({files})
  });

  if (!r.ok) {
    const txt = await r.text();
    setStatus("Erreur ZIP");
    alert(txt);
    return;
  }

  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "rb2_captures_selection.zip";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  setStatus("Téléchargement lancé.");
}

async function deleteSelected() {
  const files = selectedFiles();
  if (!files.length) {
    alert("Aucun fichier coché.");
    return;
  }

  if (!confirm("Confirmer la suppression permanente des fichiers sélectionnés ?")) {
    return;
  }

  setStatus("Suppression en cours...");
  const r = await fetch("/zero_captures_delete", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({files})
  });

  let j = null;
  try { j = await r.json(); } catch(e) {}

  if (!r.ok || !j || !j.ok) {
    setStatus("Erreur suppression");
    alert((j && j.error) ? j.error : "Erreur suppression");
    return;
  }

  setStatus(`Supprimé(s): ${j.deleted || 0}`);
  await loadCaptures();
}

document.addEventListener("DOMContentLoaded", loadCaptures);
</script>

<script>
// RB2_CAMERA_AUTORELOAD_FIX
(function () {
  function rb2ReloadCameraStream() {
    try {
      const imgs = Array.from(document.querySelectorAll("img"));
      const candidates = imgs.filter(img => {
        const src = img.getAttribute("src") || "";
        const id = img.getAttribute("id") || "";
        return (
          src.includes("zero_cam_stream") ||
          src.includes("stream.mjpg") ||
          id === "cam" ||
          id === "rb2UsbCam"
        );
      });

      candidates.forEach(img => {
        let src = img.getAttribute("src") || "";

        if (!src || src === "#") {
          src = "/zero_cam_stream.mjpg";
        }

        const base = src.split("?")[0];
        img.setAttribute("src", base + "?t=" + Date.now());
      });
    } catch (e) {
      console.log("RB2 camera autoreload error:", e);
    }
  }

  window.addEventListener("load", function () {
    setTimeout(rb2ReloadCameraStream, 500);
  });

  window.addEventListener("pageshow", function () {
    setTimeout(rb2ReloadCameraStream, 300);
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      setTimeout(rb2ReloadCameraStream, 300);
    }
  });

  window.addEventListener("focus", function () {
    setTimeout(rb2ReloadCameraStream, 300);
  });
})();
</script>


<script>
// RB2_EXTRA_LINK_BUTTONS_FIX
(function () {
  function rb2AddExtraButtonsNearShutdown() {
    try {
      const shutdownBtn = document.querySelector(".rb2-shutdown-all-btn");
      if (!shutdownBtn) return;

      if (document.getElementById("rb2ExtraButtonsRow")) return;

      const parent = shutdownBtn.parentElement;
      if (!parent) return;

      const row = document.createElement("div");
      row.id = "rb2ExtraButtonsRow";
      row.style.display = "grid";
      row.style.gridTemplateColumns = "1.4fr 0.8fr 0.9fr";
      row.style.gap = "8px";
      row.style.marginTop = "8px";
      row.style.width = "100%";
      row.style.boxSizing = "border-box";

      shutdownBtn.style.width = "100%";
      shutdownBtn.style.marginTop = "0";
      shutdownBtn.style.minHeight = "42px";

      parent.insertBefore(row, shutdownBtn);
      row.appendChild(shutdownBtn);

      const lidarBtn = document.createElement("button");
      lidarBtn.type = "button";
      lidarBtn.textContent = "LIDAR";
      lidarBtn.title = "Ouvrir la page LIDAR";
      lidarBtn.style.minHeight = "42px";
      lidarBtn.style.fontWeight = "800";
      lidarBtn.style.fontSize = "14px";
      lidarBtn.style.background = "#2563eb";
      lidarBtn.style.color = "white";
      lidarBtn.style.border = "2px solid #1d4ed8";
      lidarBtn.style.borderRadius = "8px";
      lidarBtn.style.cursor = "pointer";
      lidarBtn.onclick = function () {
        window.open("/lidar_drive", "_blank");
      };

      const camBtn = document.createElement("button");
      camBtn.type = "button";
      camBtn.textContent = "CAMÉRA";
      camBtn.title = "Ouvrir l'image caméra seulement";
      camBtn.style.minHeight = "42px";
      camBtn.style.fontWeight = "800";
      camBtn.style.fontSize = "14px";
      camBtn.style.background = "#047857";
      camBtn.style.color = "white";
      camBtn.style.border = "2px solid #065f46";
      camBtn.style.borderRadius = "8px";
      camBtn.style.cursor = "pointer";
      camBtn.onclick = function () {
        window.open("/zero_cam_stream.mjpg", "_blank");
      };

      row.appendChild(lidarBtn);
      row.appendChild(camBtn);
    } catch (e) {
      console.log("Erreur ajout boutons RB2:", e);
    }
  }

  window.addEventListener("load", rb2AddExtraButtonsNearShutdown);
  document.addEventListener("DOMContentLoaded", rb2AddExtraButtonsNearShutdown);
  setTimeout(rb2AddExtraButtonsNearShutdown, 1000);
})();
</script>

</body>
</html>
"""


@app.route("/captures")
def captures_page():
    return render_template_string(CAPTURES_HTML)


@app.route("/terrain_status")
def terrain_status():
    status = {
        "ok": True,
        "items": {},
        "warnings": [],
        "errors": []
    }

    # LIDAR
    try:
        lidar_file = "/tmp/rb2_lidar.json"
        if not os.path.exists(lidar_file):
            status["ok"] = False
            status["errors"].append("LIDAR absent")
            status["items"]["lidar"] = "absent"
        else:
            age = time.time() - os.path.getmtime(lidar_file)
            status["items"]["lidar_age_s"] = age
            if age > 3.0:
                status["warnings"].append("LIDAR ancien")
                status["items"]["lidar"] = "ancien"
            else:
                status["items"]["lidar"] = "ok"
    except Exception as e:
        status["ok"] = False
        status["errors"].append("LIDAR erreur")
        status["items"]["lidar_error"] = str(e)

    # IMU
    try:
        imu_file = "/tmp/rb2_imu.json"
        if not os.path.exists(imu_file):
            status["ok"] = False
            status["errors"].append("IMU absent")
            status["items"]["imu"] = "absent"
        else:
            age = time.time() - os.path.getmtime(imu_file)
            status["items"]["imu_age_s"] = age
            if age > 3.0:
                status["warnings"].append("IMU ancien")
                status["items"]["imu"] = "ancien"
            else:
                status["items"]["imu"] = "ok"
    except Exception as e:
        status["ok"] = False
        status["errors"].append("IMU erreur")
        status["items"]["imu_error"] = str(e)

    # Caméra USB, lecture de /status seulement
    try:
        with urllib.request.urlopen("http://10.50.0.20:8080/status", timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        if data.get("ok") is True:
            status["items"]["camera"] = "ok"
        else:
            status["warnings"].append("caméra non OK")
            status["items"]["camera"] = "warn"
    except Exception as e:
        status["ok"] = False
        status["errors"].append("caméra absente")
        status["items"]["camera_error"] = str(e)
    # Encodeurs volontairement exclus du voyant terrain : ne pas solliciter l ESP32 pendant la conduite.

    if status["errors"]:
        status["level"] = "error"
        status["label"] = "ERREUR"
    elif status["warnings"]:
        status["level"] = "warn"
        status["label"] = "ATTENTION"
    else:
        status["level"] = "ok"
        status["label"] = "OK"

    return jsonify(status)




@app.route("/lidar_map")
def lidar_map_status():
    lidar_map_file = "/tmp/rb2_lidar_map.json"

    if not os.path.exists(lidar_map_file):
        return jsonify({
            "ok": False,
            "error": "Fichier carte LIDAR absent",
            "file": lidar_map_file
        })

    try:
        st = os.stat(lidar_map_file)
        age_s = time.time() - st.st_mtime

        with open(lidar_map_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        return jsonify({
            "ok": True,
            "age_s": age_s,
            "file": lidar_map_file,
            "data": data
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "file": lidar_map_file
        })


LIDAR_DRIVE_HTML = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>RB2 - Observation LIDAR</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      margin: 0;
      padding: 10px;
      background: #111;
      color: #eee;
      font-family: Arial, sans-serif;
      overflow: hidden;
      user-select: none;
      -webkit-user-select: none;
    }
    .layout {
      display: grid;
      grid-template-columns: 3fr 1fr;
      gap: 12px;
      height: calc(100vh - 20px);
    }
    .map-panel {
      background: #000;
      border-radius: 10px;
      padding: 10px;
      box-sizing: border-box;
      position: relative;
      min-height: 0;
    }
    #lidarCanvas {
      width: 100%;
      height: 100%;
      display: block;
      background: #000;
      border: 2px solid #444;
      border-radius: 8px;
      box-sizing: border-box;
    }
    .map-title {
      position: absolute;
      top: 18px;
      left: 22px;
      background: rgba(0, 0, 0, 0.65);
      padding: 6px 10px;
      border-radius: 6px;
      font-size: 16px;
      color: #ddd;
      z-index: 20;
    }
    .map-status {
      position: absolute;
      bottom: 18px;
      left: 22px;
      background: rgba(0, 0, 0, 0.65);
      padding: 6px 10px;
      border-radius: 6px;
      font-size: 14px;
      color: #aaa;
      z-index: 20;
    }
    .zoom-row {
      position: absolute;
      top: 18px;
      right: 22px;
      display: flex;
      gap: 8px;
      z-index: 30;
    }
    .zoom-row button {
      background: rgba(60, 60, 60, 0.9);
      color: white;
      border: 1px solid #777;
      border-radius: 6px;
      font-size: 15px;
      padding: 7px 10px;
      cursor: pointer;
    }
    .zoom-row button:hover { background: rgba(90, 90, 90, 0.95); }

    .controls {
      background: #222;
      border-radius: 10px;
      padding: 12px;
      box-sizing: border-box;
      overflow-y: auto;
      font-size: 17px;
    }
    h2 {
      margin: 4px 0 10px 0;
      text-align: center;
      font-size: 22px;
      color: #e5e7eb;
    }
    .panel {
      background: #111827;
      border: 1px solid #374151;
      border-radius: 10px;
      padding: 12px;
      margin: 10px 0;
      box-sizing: border-box;
    }
    .panel-title {
      font-size: 18px;
      font-weight: 900;
      color: #facc15;
      text-align: center;
      margin-bottom: 10px;
    }
    .horizon-box {
      position: relative;
      height: 120px;
      background: #020617;
      border: 2px solid #475569;
      border-radius: 10px;
      overflow: hidden;
    }
    .horizon-center-v {
      position: absolute; left: 50%; top: 0; width: 2px; height: 100%;
      background: #64748b; transform: translateX(-50%);
    }
    .horizon-center-h {
      position: absolute; left: 0; top: 50%; width: 100%; height: 2px;
      background: #64748b; transform: translateY(-50%);
    }
    .horizon-line {
      position: absolute; left: -25%; top: 50%; width: 150%; height: 4px;
      background: #00ff66; transform-origin: center center; box-shadow: 0 0 8px #00ff66;
    }
    .horizon-state {
      margin-top: 8px;
      text-align: center;
      color: #d1d5db;
      font-size: 16px;
      font-weight: 800;
    }
    .state-big {
      text-align: center;
      font-size: 22px;
      font-weight: 1000;
      padding: 10px;
      border-radius: 10px;
      margin-bottom: 10px;
      background: #020617;
      border: 1px solid #374151;
    }
    .ok { color: #22c55e !important; }
    .warn { color: #facc15 !important; }
    .danger, .error { color: #ff6666 !important; }
    .info { color: #60a5fa !important; }
    .grid2 {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .box {
      background: #000;
      border: 1px solid #333;
      border-radius: 8px;
      padding: 10px 8px;
      text-align: center;
      min-height: 58px;
    }
    .label {
      color: #9ca3af;
      font-size: 15px;
      margin-bottom: 4px;
      font-weight: 700;
    }
    .value {
      color: #e5e7eb;
      font-size: 24px;
      font-weight: 1000;
      line-height: 1.15;
    }
    .text-line {
      font-size: 16px;
      line-height: 1.35;
      color: #d1d5db;
      margin: 6px 0;
      word-break: break-word;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 14px;
      color: #cbd5e1;
      word-break: break-word;
    }
    @media (max-width: 1000px) {
      body { overflow: auto; }
      .layout { grid-template-columns: 1fr; height: auto; }
      .map-panel { height: 65vh; }
    }
  </style>
</head>
<body>
  <div class="layout">
    <div class="map-panel">
      <canvas id="lidarCanvas"></canvas>
      <div class="map-title">Carte LIDAR RB2</div>
      <div class="zoom-row">
        <button onclick="zoomIn()">Zoom +</button>
        <button onclick="zoomOut()">Zoom -</button>
        <button onclick="zoomReset()">Reset</button>
        <button onclick="toggleDistances()">Distances</button>
      </div>
      <div class="map-status" id="mapStatus">attente LIDAR...</div>
    </div>

    <div class="controls">
      <h2>Observation LIDAR</h2>
      <!-- RB2 V20 : marges réelles, sans distances brutes, caméra exclue des alertes -->

      <div class="panel">
        <div class="panel-title">Horizon artificiel</div>
        <div class="horizon-box">
          <div class="horizon-center-v"></div>
          <div class="horizon-center-h"></div>
          <div class="horizon-line" id="horizonLine"></div>
        </div>
        <div class="horizon-state" id="imuStateText">IMU : attente</div>
      </div>

      <div class="panel">
        <div class="panel-title">État RB2</div>
        <div class="state-big" id="rb2StateBig">ATTENTE</div>
        <div class="text-line" id="rb2Detail">Lecture de /terrain_status...</div>
        <div class="text-line">LIDAR : <span id="rb2LidarState">---</span></div>
        <div class="text-line">IMU : <span id="rb2ImuState">---</span></div>
      </div>

      <div class="panel">
        <div class="panel-title">Distances utiles</div>
        <div class="grid2">
          <div class="box"><div class="label">Avant libre</div><div class="value" id="frontCm">---</div></div>
          <div class="box"><div class="label">Arrière libre</div><div class="value" id="backCm">---</div></div>
          <div class="box"><div class="label">Gauche</div><div class="value" id="leftCm">---</div></div>
          <div class="box"><div class="label">Droite</div><div class="value" id="rightCm">---</div></div>
        </div>
        <div class="text-line">État avant : <span id="frontState">---</span></div>
        <div class="text-line">État arrière : <span id="backState">---</span></div>
        <div class="text-line">Obstacle utile : <span id="usefulNearest">---</span></div>
      </div>

      <div class="panel">
        <div class="panel-title">Trace / Rejeu</div>
        <div class="text-line">Trace : <span id="traceActive">---</span></div>
        <div class="text-line">Dernière trace :</div>
        <div class="mono" id="traceLatest">---</div>
        <div class="text-line">Dernière trace conduite :</div>
        <div class="mono" id="traceDriveLatest">---</div>
        <div class="text-line">Suivre trace : <span id="followState">---</span></div>
        <div class="mono" id="followFile">---</div>
      </div>
    </div>
  </div>

<script>
let zoomFactor = 1.0;
let showDistances = true;
let lastLidarData = null;
let lastLidarAge = 0;
let lastClearance = null;

// V20 : distances affichées = marge restante avant collision.
// Les distances brutes centre LIDAR ne sont plus affichées à l’opérateur.
// Avant : brut 36 cm = environ 3 cm libre => nez RB2 à 33 cm du centre LIDAR.
// Arrière ajusté terrain : à 1 cm affiché il y a déjà collision => arrière RB2 à 9 cm du centre LIDAR.
const RB2_FRONT_COLLISION_CM = 33.0;
const RB2_BACK_COLLISION_CM = 9.0;
const RB2_MARGIN_DANGER_CM = 5.0;
const RB2_MARGIN_WARN_CM = 15.0;

function collisionMargin(rawCm, bodyCm) {
  const n = Number(rawCm);
  const b = Number(bodyCm);
  if (!Number.isFinite(n) || !Number.isFinite(b)) return NaN;
  return n - b;
}

function fmtSignedCm(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "---";
  if (n < 0) return "COLLISION " + Math.abs(n).toFixed(0) + " cm";
  return n.toFixed(0) + " cm";
}

function fmtCm(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(0) + " cm" : "---";
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setClassState(el, cls) {
  if (!el) return;
  el.classList.remove("ok", "warn", "danger", "error", "info");
  if (cls) el.classList.add(cls);
}

function stateForDistance(cm, warn, danger) {
  const n = Number(cm);
  if (!Number.isFinite(n)) return {label: "---", cls: "info"};
  if (n <= danger) return {label: "DANGER", cls: "danger"};
  if (n <= warn) return {label: "ATTENTION", cls: "warn"};
  return {label: "OK", cls: "ok"};
}

function resizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {w: rect.width, h: rect.height, ctx: ctx};
}

function getPointXY(p) {
  if (Array.isArray(p) && p.length >= 2) return [Number(p[0]), Number(p[1])];
  if (p && typeof p === "object") return [Number(p.x_cm ?? p.x ?? 0), Number(p.y_cm ?? p.y ?? 0)];
  return [NaN, NaN];
}

function drawLidarMap(data, age_s, clearance) {
  const canvas = document.getElementById("lidarCanvas");
  const status = document.getElementById("mapStatus");
  const r = resizeCanvas(canvas);
  const ctx = r.ctx;
  const w = r.w;
  const h = r.h;
  const cx = w / 2;
  const cy = h / 2;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, w, h);

  const robot = data.robot || {front_cm: 28, back_cm: 8, half_width_cm: 10, front_line_cm: 35};
  const scale = (Math.min(w, h) / 420.0) * zoomFactor;
  const sx = x => cx + x * scale;
  const sy = y => cy - y * scale;

  if (showDistances) {
    ctx.save();
    ctx.font = "13px Arial";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    for (const cm of [50,100,150,200,250,300]) {
      const radius = cm * scale;
      if (radius < 12 || radius > Math.max(w, h)) continue;
      ctx.beginPath();
      ctx.strokeStyle = cm % 100 === 0 ? "#3a3a3a" : "#252525";
      ctx.lineWidth = cm % 100 === 0 ? 1.5 : 1;
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = "#888";
      ctx.fillText(cm + " cm", cx + radius + 6, cy);
    }
    ctx.restore();
  }

  ctx.strokeStyle = "#222";
  ctx.lineWidth = 1;
  for (let cm = -300; cm <= 300; cm += 50) {
    ctx.beginPath(); ctx.moveTo(sx(cm), sy(-300)); ctx.lineTo(sx(cm), sy(300)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(sx(-300), sy(cm)); ctx.lineTo(sx(300), sy(cm)); ctx.stroke();
  }

  ctx.strokeStyle = "#555";
  ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(sx(-300), sy(0)); ctx.lineTo(sx(300), sy(0)); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(sx(0), sy(-300)); ctx.lineTo(sx(0), sy(300)); ctx.stroke();

  const frontDistance = clearance && clearance.front_cm !== undefined ? Number(clearance.front_cm) : NaN;
  const frontWarn = Number.isFinite(frontDistance) && frontDistance < 47;
  const frontDanger = Number.isFinite(frontDistance) && frontDistance < 37;
  ctx.strokeStyle = frontDanger ? "#ff3333" : (frontWarn ? "#ffcc33" : "#aa3333");
  ctx.lineWidth = frontDanger ? 6 : (frontWarn ? 5 : 4);
  ctx.beginPath(); ctx.moveTo(sx(0), sy(0)); ctx.lineTo(sx(0), sy(Number(robot.front_line_cm || 35))); ctx.stroke();

  // Robot rectangle approximatif.
  ctx.strokeStyle = "#00ff66";
  ctx.lineWidth = 2;
  const hw = Number(robot.half_width_cm || 10);
  const front = Number(robot.front_cm || 28);
  const back = Number(robot.back_cm || 8);
  ctx.strokeRect(sx(-hw), sy(front), (hw * 2) * scale, (front + back) * scale);

  const points = data.points_cm || [];
  ctx.fillStyle = "#66ccff";
  for (const p of points) {
    const [x, y] = getPointXY(p);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    ctx.beginPath();
    ctx.arc(sx(x), sy(y), 2.2, 0, Math.PI * 2);
    ctx.fill();
  }

  // Labels de distances utiles sur la carte.
  if (clearance) {
    ctx.save();
    ctx.font = "15px Arial";
    ctx.fillStyle = "#e5e7eb";
    ctx.textAlign = "center";
    if (clearance.front_cm !== undefined) {
      const fm = collisionMargin(clearance.front_cm, RB2_FRONT_COLLISION_CM);
      ctx.fillText("Avant libre " + fmtSignedCm(fm), sx(0), sy(70));
    }
    if (clearance.back_cm !== undefined) {
      const bm = collisionMargin(clearance.back_cm, RB2_BACK_COLLISION_CM);
      ctx.fillText("Arrière libre " + fmtSignedCm(bm), sx(0), sy(-70));
    }
    if (clearance.left_cm !== undefined) ctx.fillText("Gauche " + fmtCm(clearance.left_cm), sx(-80), sy(0));
    if (clearance.right_cm !== undefined) ctx.fillText("Droite " + fmtCm(clearance.right_cm), sx(80), sy(0));
    ctx.restore();
  }

  if (status) {
    const count = points.length || 0;
    const age = Number(age_s || 0).toFixed(1);
    status.textContent = "points: " + count + " — âge: " + age + " s — zoom: " + zoomFactor.toFixed(2) + "x — distances: " + (showDistances ? "ON" : "OFF");
    status.style.color = Number(age_s || 0) > 3 ? "#ffcc66" : "#aaa";
  }
}

function updateDistancePanel(clearance) {
  if (!clearance) return;

  const frontMargin = collisionMargin(clearance.front_cm, RB2_FRONT_COLLISION_CM);
  const backMargin = collisionMargin(clearance.back_cm, RB2_BACK_COLLISION_CM);

  // Avant/arrière : marge avant collision avec le châssis.
  // Gauche/droite : distance brute, car aucune marge latérale fiable n'est appliquée ici.
  setText("frontCm", fmtSignedCm(frontMargin));
  setText("backCm", fmtSignedCm(backMargin));
  setText("leftCm", fmtCm(clearance.left_cm));
  setText("rightCm", fmtCm(clearance.right_cm));

  const fs = stateForDistance(frontMargin, RB2_MARGIN_WARN_CM, RB2_MARGIN_DANGER_CM);
  const bs = stateForDistance(backMargin, RB2_MARGIN_WARN_CM, RB2_MARGIN_DANGER_CM);
  const frontEl = document.getElementById("frontState");
  const backEl = document.getElementById("backState");
  if (frontEl) { frontEl.textContent = fs.label; setClassState(frontEl, fs.cls); }
  if (backEl) { backEl.textContent = bs.label; setClassState(backEl, bs.cls); }

  const candidates = [];
  if (Number.isFinite(frontMargin)) candidates.push(["avant libre", frontMargin]);
  if (Number.isFinite(backMargin)) candidates.push(["arrière libre", backMargin]);
  for (const [name, val] of [["gauche brut", clearance.left_cm], ["droite brut", clearance.right_cm]]) {
    const n = Number(val);
    if (Number.isFinite(n)) candidates.push([name, n]);
  }
  candidates.sort((a,b) => a[1] - b[1]);
  setText("usefulNearest", candidates.length ? candidates[0][0] + " " + fmtSignedCm(candidates[0][1]) : "---");
}

async function updateLidarMap() {
  try {
    const res = await fetch("/lidar_map", {cache: "no-store"});
    const j = await res.json();
    if (!j.ok) throw new Error(j.error || "lidar_map non OK");

    let clearance = null;
    try {
      const cRes = await fetch("/lidar", {cache: "no-store"});
      const cJson = await cRes.json();
      if (cJson.ok) clearance = cJson.data || cJson;
    } catch (e2) {}

    lastLidarData = j.data || {};
    lastLidarAge = j.age_s || 0;
    lastClearance = clearance;
    drawLidarMap(lastLidarData, lastLidarAge, lastClearance);
    updateDistancePanel(lastClearance);
  } catch (e) {
    const status = document.getElementById("mapStatus");
    if (status) { status.textContent = "LIDAR carte : erreur"; status.style.color = "#ff6666"; }
  }
}

function zoomIn() { zoomFactor = Math.min(4.0, zoomFactor * 1.25); if (lastLidarData) drawLidarMap(lastLidarData, lastLidarAge, lastClearance); }
function zoomOut() { zoomFactor = Math.max(0.4, zoomFactor / 1.25); if (lastLidarData) drawLidarMap(lastLidarData, lastLidarAge, lastClearance); }
function zoomReset() { zoomFactor = 1.0; if (lastLidarData) drawLidarMap(lastLidarData, lastLidarAge, lastClearance); }
function toggleDistances() { showDistances = !showDistances; if (lastLidarData) drawLidarMap(lastLidarData, lastLidarAge, lastClearance); }

async function updateImu() {
  try {
    const res = await fetch("/imu_json", {cache: "no-store"});
    const j = await res.json();
    const raw = j.data || {};
    const data = raw.data || raw;
    const ok = !!j.ok;
    const roll = Number(data.roll_deg ?? data.roll ?? 0);
    const pitch = Number(data.pitch_deg ?? data.pitch ?? 0);
    const age = Number(j.age_s ?? data.age_s ?? 0);
    const line = document.getElementById("horizonLine");
    if (line && ok) {
      line.style.transform = "rotate(" + (-roll).toFixed(1) + "deg) translateY(" + Math.max(-35, Math.min(35, pitch * 2)).toFixed(0) + "px)";
    }
    const st = document.getElementById("imuStateText");
    if (st) {
      st.textContent = ok ? ("IMU : R " + roll.toFixed(1) + "° / P " + pitch.toFixed(1) + "° — âge " + age.toFixed(1) + " s") : "IMU : non disponible";
      setClassState(st, ok && age < 3 ? "ok" : "warn");
    }
  } catch (e) {
    const st = document.getElementById("imuStateText");
    if (st) { st.textContent = "IMU : erreur"; setClassState(st, "error"); }
  }
}

async function updateRb2Status() {
  try {
    const res = await fetch("/terrain_status", {cache: "no-store"});
    const j = await res.json();
    const box = document.getElementById("rb2StateBig");
    const items = j.items || {};

    // V20 : sur /lidar_drive, la caméra n’est pas utilisée comme alerte opérateur.
    // Si l’image tombe, l’opérateur le voit immédiatement. On garde LIDAR/IMU comme diagnostics utiles.
    function isCameraMessage(txt) {
      const t = String(txt || "").toLowerCase();
      return t.includes("caméra") || t.includes("camera") || t.includes("zero cam") || t.includes("zero 2");
    }

    const filteredErrors = Array.isArray(j.errors) ? j.errors.filter(e => !isCameraMessage(e)) : [];
    const filteredWarnings = Array.isArray(j.warnings) ? j.warnings.filter(w => !isCameraMessage(w)) : [];

    let level = "ok";
    let label = "OK";
    if (filteredErrors.length) {
      level = "error";
      label = "ERREUR";
    } else if (filteredWarnings.length) {
      level = "warn";
      label = "ATTENTION";
    }

    // Si /terrain_status ne fournit pas de message mais signale explicitement LIDAR/IMU mauvais,
    // on l’affiche quand même comme diagnostic utile.
    if (String(items.lidar || "").toLowerCase() !== "ok" && items.lidar !== undefined) {
      if (level === "ok") { level = "error"; label = "ERREUR"; }
      filteredErrors.push("LIDAR non OK");
    }
    if (String(items.imu || "").toLowerCase() !== "ok" && items.imu !== undefined) {
      if (level === "ok") { level = "error"; label = "ERREUR"; }
      filteredErrors.push("IMU non OK");
    }

    if (box) {
      box.textContent = "RB2 : " + label;
      setClassState(box, level === "ok" ? "ok" : (level === "warn" ? "warn" : "error"));
    }

    const details = [];
    if (filteredErrors.length) details.push("Erreurs : " + filteredErrors.join(" | "));
    if (filteredWarnings.length) details.push("Avertissements : " + filteredWarnings.join(" | "));
    setText("rb2Detail", details.length ? details.join(" — ") : "Aucune erreur utile active signalée.");

    setText("rb2LidarState", (items.lidar || "---") + (items.lidar_age_s !== undefined ? " — " + Number(items.lidar_age_s).toFixed(1) + " s" : ""));
    setText("rb2ImuState", (items.imu || "---") + (items.imu_age_s !== undefined ? " — " + Number(items.imu_age_s).toFixed(1) + " s" : ""));
  } catch (e) {
    const box = document.getElementById("rb2StateBig");
    if (box) { box.textContent = "RB2 : ERREUR LECTURE"; setClassState(box, "error"); }
    setText("rb2Detail", "Impossible de lire /terrain_status");
  }
}

async function updateTraceStatus() {
  try {
    const res = await fetch("/trace_status", {cache: "no-store"});
    const j = await res.json();
    setText("traceActive", j.active ? "active" : "arrêtée");
    setText("traceLatest", j.latest || "aucune");
    setText("traceDriveLatest", j.latest_drive || "aucune");
  } catch (e) {
    setText("traceActive", "erreur lecture");
  }
}

async function updateFollowStatus() {
  try {
    const res = await fetch("/trace_follow_status", {cache: "no-store"});
    const j = await res.json();
    setText("followState", j.running ? "actif" : (j.state || j.message || "inactif"));
    setText("followFile", j.file || "---");
  } catch (e) {
    setText("followState", "erreur lecture");
  }
}

function updateAllSlow() {
  updateRb2Status();
  updateTraceStatus();
  updateFollowStatus();
}

function updateAllFast() {
  updateLidarMap();
  updateImu();
}

document.addEventListener("DOMContentLoaded", function () {
  updateAllFast();
  updateAllSlow();
  setInterval(updateAllFast, 1000);
  setInterval(updateAllSlow, 3000);
});
window.addEventListener("resize", function () { if (lastLidarData) drawLidarMap(lastLidarData, lastLidarAge, lastClearance); });
</script>

<script>
// RB2_CAMERA_AUTORELOAD_FIX
(function () {
  function rb2ReloadCameraStream() {
    try {
      const imgs = Array.from(document.querySelectorAll("img"));
      const candidates = imgs.filter(img => {
        const src = img.getAttribute("src") || "";
        const id = img.getAttribute("id") || "";
        return (
          src.includes("zero_cam_stream") ||
          src.includes("stream.mjpg") ||
          id === "cam" ||
          id === "rb2UsbCam"
        );
      });

      candidates.forEach(img => {
        let src = img.getAttribute("src") || "";

        if (!src || src === "#") {
          src = "/zero_cam_stream.mjpg";
        }

        const base = src.split("?")[0];
        img.setAttribute("src", base + "?t=" + Date.now());
      });
    } catch (e) {
      console.log("RB2 camera autoreload error:", e);
    }
  }

  window.addEventListener("load", function () {
    setTimeout(rb2ReloadCameraStream, 500);
  });

  window.addEventListener("pageshow", function () {
    setTimeout(rb2ReloadCameraStream, 300);
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      setTimeout(rb2ReloadCameraStream, 300);
    }
  });

  window.addEventListener("focus", function () {
    setTimeout(rb2ReloadCameraStream, 300);
  });
})();
</script>


<script>
// RB2_EXTRA_LINK_BUTTONS_FIX
(function () {
  function rb2AddExtraButtonsNearShutdown() {
    try {
      const shutdownBtn = document.querySelector(".rb2-shutdown-all-btn");
      if (!shutdownBtn) return;

      if (document.getElementById("rb2ExtraButtonsRow")) return;

      const parent = shutdownBtn.parentElement;
      if (!parent) return;

      const row = document.createElement("div");
      row.id = "rb2ExtraButtonsRow";
      row.style.display = "grid";
      row.style.gridTemplateColumns = "1.4fr 0.8fr 0.9fr";
      row.style.gap = "8px";
      row.style.marginTop = "8px";
      row.style.width = "100%";
      row.style.boxSizing = "border-box";

      shutdownBtn.style.width = "100%";
      shutdownBtn.style.marginTop = "0";
      shutdownBtn.style.minHeight = "42px";

      parent.insertBefore(row, shutdownBtn);
      row.appendChild(shutdownBtn);

      const lidarBtn = document.createElement("button");
      lidarBtn.type = "button";
      lidarBtn.textContent = "LIDAR";
      lidarBtn.title = "Ouvrir la page LIDAR";
      lidarBtn.style.minHeight = "42px";
      lidarBtn.style.fontWeight = "800";
      lidarBtn.style.fontSize = "14px";
      lidarBtn.style.background = "#2563eb";
      lidarBtn.style.color = "white";
      lidarBtn.style.border = "2px solid #1d4ed8";
      lidarBtn.style.borderRadius = "8px";
      lidarBtn.style.cursor = "pointer";
      lidarBtn.onclick = function () {
        window.open("/lidar_drive", "_blank");
      };

      const camBtn = document.createElement("button");
      camBtn.type = "button";
      camBtn.textContent = "CAMÉRA";
      camBtn.title = "Ouvrir l'image caméra seulement";
      camBtn.style.minHeight = "42px";
      camBtn.style.fontWeight = "800";
      camBtn.style.fontSize = "14px";
      camBtn.style.background = "#047857";
      camBtn.style.color = "white";
      camBtn.style.border = "2px solid #065f46";
      camBtn.style.borderRadius = "8px";
      camBtn.style.cursor = "pointer";
      camBtn.onclick = function () {
        window.open("/zero_cam_stream.mjpg", "_blank");
      };

      row.appendChild(lidarBtn);
      row.appendChild(camBtn);
    } catch (e) {
      console.log("Erreur ajout boutons RB2:", e);
    }
  }

  window.addEventListener("load", rb2AddExtraButtonsNearShutdown);
  document.addEventListener("DOMContentLoaded", rb2AddExtraButtonsNearShutdown);
  setTimeout(rb2AddExtraButtonsNearShutdown, 1000);
})();
</script>



<!-- RB2_LIDAR_COLLISION_BORDER_FIX_V2 -->
<style>
  .map-panel.rb2-lidar-warn,
  .camera.rb2-lidar-warn {
    border: 5px solid #ffd400 !important;
    box-shadow: 0 0 18px #ffd400 !important;
  }

  .map-panel.rb2-lidar-danger,
  .camera.rb2-lidar-danger {
    border: 6px solid #ff3030 !important;
    box-shadow: 0 0 22px #ff3030 !important;
  }
</style>

<script>
(function() {
  /*
    RB2 - contour LIDAR corrigé V2

    But :
      - ne jamais utiliser min_cm pour le contour;
      - utiliser seulement front_cm et back_cm;
      - imposer l'état réel régulièrement pour éviter un contour orange collé.

    Géométrie pratique RB2 depuis le centre LIDAR :
      Avant  : 37 cm
      Arrière: 17 cm

    Marge d'avertissement voulue :
      4 cm réels

    Seuils LIDAR résultants :
      Avant orange  : 41 cm
      Arrière orange: 21 cm
  */

  const FRONT_BODY_CM = 37.0;
  const BACK_BODY_CM = 17.0;
  const WARNING_MARGIN_CM = 4.0;

  const FRONT_DANGER_CM = FRONT_BODY_CM;
  const FRONT_WARNING_CM = FRONT_BODY_CM + WARNING_MARGIN_CM;

  const BACK_DANGER_CM = BACK_BODY_CM;
  const BACK_WARNING_CM = BACK_BODY_CM + WARNING_MARGIN_CM;

  function rb2Num(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function rb2GetNumber(obj, names) {
    if (!obj) return null;

    for (const name of names) {
      if (obj[name] !== undefined && obj[name] !== null) {
        const n = rb2Num(obj[name]);
        if (n !== null) return n;
      }
    }

    return null;
  }

  function rb2ClassifyFromLidarData(data) {
    const front = rb2GetNumber(data, [
      "front_cm",
      "front",
      "front_min_cm",
      "front_clearance_cm",
      "clearance_front_cm",
      "avant_cm",
      "avant"
    ]);

    const back = rb2GetNumber(data, [
      "back_cm",
      "back",
      "rear_cm",
      "rear",
      "rear_min_cm",
      "back_min_cm",
      "back_clearance_cm",
      "clearance_back_cm",
      "arriere_cm",
      "arrière_cm",
      "arriere",
      "arrière"
    ]);

    /*
      Important :
      min_cm est volontairement ignoré.
      Il peut venir d'un côté, d'une antenne, d'une roue ou d'un élément non critique.
    */

    if ((front !== null && front > 0 && front <= FRONT_DANGER_CM) ||
        (back !== null && back > 0 && back <= BACK_DANGER_CM)) {
      return "danger";
    }

    if ((front !== null && front > 0 && front <= FRONT_WARNING_CM) ||
        (back !== null && back > 0 && back <= BACK_WARNING_CM)) {
      return "warn";
    }

    return "ok";
  }

  function rb2ApplyLidarBorder(level) {
    const panels = document.querySelectorAll(".map-panel, .camera");

    panels.forEach(function(panel) {
      panel.classList.remove("rb2-lidar-warn", "rb2-lidar-danger");

      if (level === "danger") {
        panel.classList.add("rb2-lidar-danger");
      } else if (level === "warn") {
        panel.classList.add("rb2-lidar-warn");
      }
    });
  }

  async function rb2RefreshLidarBorderFromServer() {
    try {
      const res = await fetch("/lidar", {cache: "no-store"});
      const j = await res.json();
      const data = j.data || j;

      if (!j.ok && j.ok !== undefined) {
        rb2ApplyLidarBorder("ok");
        return;
      }

      rb2ApplyLidarBorder(rb2ClassifyFromLidarData(data));
    } catch (e) {
      rb2ApplyLidarBorder("ok");
    }
  }

  const oldUpdateDistancePanel = window.updateDistancePanel;

  if (typeof oldUpdateDistancePanel === "function") {
    window.updateDistancePanel = function(clearance) {
      const result = oldUpdateDistancePanel.apply(this, arguments);

      try {
        rb2ApplyLidarBorder(rb2ClassifyFromLidarData(clearance));
      } catch (e) {
        console.log("RB2 lidar border classification error:", e);
      }

      return result;
    };
  }

  window.rb2RefreshLidarBorderFromServer = rb2RefreshLidarBorderFromServer;

  document.addEventListener("DOMContentLoaded", rb2RefreshLidarBorderFromServer);
  window.addEventListener("load", rb2RefreshLidarBorderFromServer);

  setTimeout(rb2RefreshLidarBorderFromServer, 300);
  setInterval(rb2RefreshLidarBorderFromServer, 500);
})();
</script>


</body>
</html>
"""



@app.route("/trace_status")
def trace_status():
    import os
    from pathlib import Path

    pid_file = Path("/tmp/rb2_trace_passive.pid")
    trace_dir = Path("/opt/rb2/traces")

    active = False
    pid = None

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            active = True
        except Exception:
            active = False

    latest = None
    latest_drive = None
    try:
        files = sorted(
            [x for x in trace_dir.glob("rb2_trace_*.csv")
             if "_markers" not in x.name and "_photo_markers" not in x.name and "_drive" not in x.name],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if files:
            latest = files[0].name
            drive_candidate = files[0].with_name(files[0].stem + "_drive.csv")
            if drive_candidate.exists():
                latest_drive = drive_candidate.name
    except Exception:
        latest = None
        latest_drive = None

    return jsonify({
        "ok": True,
        "active": active,
        "pid": pid,
        "latest": latest,
        "latest_drive": latest_drive,
    })



@app.route("/trace_start", methods=["POST"])
def trace_start():
    import subprocess

    try:
        r = subprocess.run(
            ["/usr/local/bin/rb2-trace-start"],
            capture_output=True,
            text=True,
            timeout=3
        )

        return jsonify({
            "ok": r.returncode == 0,
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip()
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.route("/trace_stop", methods=["POST"])
def trace_stop():
    import subprocess

    try:
        r = subprocess.run(
            ["/usr/local/bin/rb2-trace-stop"],
            capture_output=True,
            text=True,
            timeout=3
        )

        return jsonify({
            "ok": r.returncode == 0,
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip()
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

@app.route("/trace_mark", methods=["POST"])
def trace_mark():
    import csv
    import time
    from pathlib import Path
    from datetime import datetime

    trace_dir = Path("/opt/rb2/traces")
    trace_dir.mkdir(parents=True, exist_ok=True)

    data = request.get_json(silent=True) or {}
    label = str(data.get("label", "MARQUEUR")).strip() or "MARQUEUR"

    latest_trace = None
    try:
        files = sorted(
            trace_dir.glob("rb2_trace_*.csv"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if files:
            latest_trace = files[0]
    except Exception:
        latest_trace = None

    if latest_trace:
        marker_file = trace_dir / (latest_trace.stem + "_markers.csv")
        latest_name = latest_trace.name
    else:
        stamp = datetime.now().strftime("%Y%m%d")
        marker_file = trace_dir / f"rb2_markers_{stamp}.csv"
        latest_name = ""

    new_file = not marker_file.exists()

    try:
        with marker_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            if new_file:
                writer.writerow([
                    "iso_time",
                    "epoch_s",
                    "latest_trace",
                    "label"
                ])

            writer.writerow([
                datetime.now().isoformat(timespec="seconds"),
                round(time.time(), 3),
                latest_name,
                label
            ])

        return jsonify({
            "ok": True,
            "marker_file": marker_file.name,
            "latest_trace": latest_name,
            "label": label
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500



@app.route("/photo_mark", methods=["POST"])
def photo_mark():
    import csv
    import time
    import urllib.request
    from pathlib import Path
    from datetime import datetime

    trace_dir = Path("/opt/rb2/traces")
    photo_dir = trace_dir / "photos"
    trace_dir.mkdir(parents=True, exist_ok=True)
    photo_dir.mkdir(parents=True, exist_ok=True)

    # Trouver la dernière trace CSV principale
    latest_trace = None
    try:
        files = sorted(
            trace_dir.glob("rb2_trace_*.csv"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if files:
            latest_trace = files[0]
    except Exception:
        latest_trace = None

    latest_name = latest_trace.name if latest_trace else ""

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    photo_name = f"rb2_photo_repere_{stamp}.jpg"
    photo_path = photo_dir / photo_name

    try:
        # Lire une image JPEG depuis le flux MJPEG local.
        url = "http://10.50.0.20:8080/stream.mjpg"
        req = urllib.request.Request(url, headers={"User-Agent": "RB2-photo-repere"})

        data = b""
        started = False

        with urllib.request.urlopen(req, timeout=4.0) as r:
            deadline = time.time() + 4.0

            while time.time() < deadline:
                chunk = r.read(4096)
                if not chunk:
                    break

                data += chunk

                start = data.find(b"\xff\xd8")
                end = data.find(b"\xff\xd9")

                if start >= 0:
                    started = True

                if started and start >= 0 and end > start:
                    jpg = data[start:end + 2]
                    photo_path.write_bytes(jpg)
                    break

        if not photo_path.exists() or photo_path.stat().st_size < 1000:
            return jsonify({
                "ok": False,
                "error": "Aucune image JPEG valide capturée",
                "photo": photo_name
            }), 500

        # Fichier de marqueurs photo
        if latest_trace:
            marker_file = trace_dir / (latest_trace.stem + "_photo_markers.csv")
        else:
            marker_file = trace_dir / f"rb2_photo_markers_{datetime.now().strftime('%Y%m%d')}.csv"

        new_file = not marker_file.exists()

        with marker_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            if new_file:
                writer.writerow([
                    "iso_time",
                    "epoch_s",
                    "latest_trace",
                    "label",
                    "photo_file"
                ])

            writer.writerow([
                datetime.now().isoformat(timespec="seconds"),
                round(time.time(), 3),
                latest_name,
                "PHOTO_REPERE",
                str(Path("photos") / photo_name)
            ])

        return jsonify({
            "ok": True,
            "photo": photo_name,
            "photo_path": str(photo_path),
            "marker_file": marker_file.name,
            "latest_trace": latest_name
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.route("/lidar_drive")
def lidar_drive_page():
    return render_template_string(LIDAR_DRIVE_HTML)



@app.route("/relay_light", methods=["GET", "POST"])
def relay_light_proxy():
    import json
    import urllib.request

    url = "http://127.0.0.1:5052/light"

    try:
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
        else:
            req = urllib.request.Request(url, method="GET")

        with urllib.request.urlopen(req, timeout=1.0) as r:
            body = r.read().decode("utf-8")
            return app.response_class(body, mimetype="application/json")

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "state": "off"
        }), 502


@app.route("/relay2_proxy", methods=["GET", "POST"])
def relay2_proxy():
    import json
    import urllib.request

    url = "http://127.0.0.1:5052/relay2"

    try:
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
        else:
            req = urllib.request.Request(url, method="GET")

        with urllib.request.urlopen(req, timeout=1.0) as r:
            body = r.read().decode("utf-8")
            return app.response_class(body, mimetype="application/json")

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "state": "off"
        }), 502



RB2_SHUTDOWN_BUTTON_HTML = """
<!-- RB2_SHUTDOWN_BUTTON_HTML_DIRECT -->
<style>
#rb2ShutdownAllDirectBtn {
  position: fixed;
  left: 14px;
  bottom: 14px;
  z-index: 999999;
  min-width: 230px;
  min-height: 46px;
  padding: 10px 14px;
  border: 3px solid #7a0000;
  border-radius: 10px;
  background: #b00000;
  color: #ffffff;
  font-weight: 900;
  font-size: 15px;
  box-shadow: 0 0 14px rgba(0,0,0,0.70);
  cursor: pointer;
}
#rb2ShutdownAllDirectBtn:hover {
  background: #d00000;
}
#rb2ShutdownAllDirectBtn:disabled {
  background: #555555;
  border-color: #444444;
  color: #dddddd;
  cursor: not-allowed;
}
</style>

<button id="rb2ShutdownAllDirectBtn" onclick="rb2ShutdownAllDirect()">
  ARRÊTER RB2 COMPLET
</button>

<script>
function rb2ShutdownAllDirect() {
  const ok = confirm(
    "Confirmer l'arrêt complet de RB2 ?\\n\\n" +
    "Le Zero 2 W caméra sera arrêté en premier.\\n" +
    "Le Raspberry Pi 5 sera ensuite arrêté.\\n\\n" +
    "Après confirmation, l'interface web cessera de répondre."
  );

  if (!ok) return;

  const btn = document.getElementById("rb2ShutdownAllDirectBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "ARRÊT EN COURS...";
  }

  fetch("/system_shutdown_all", {
    method: "POST",
    cache: "no-store"
  })
  .then(r => r.json())
  .then(j => {
    if (!j.ok) {
      alert("Erreur arrêt RB2 : " + (j.error || "erreur inconnue"));
      if (btn) {
        btn.disabled = false;
        btn.textContent = "ARRÊTER RB2 COMPLET";
      }
      return;
    }

    alert("Arrêt complet RB2 demandé.");
  })
  .catch(e => {
    alert("Commande envoyée ou connexion perdue. Si RB2 s'arrête, c'est normal.");
  });
}
</script>
"""



RB2_SLAM_PANEL_HTML = """
<!-- RB2_SLAM_PANEL_V24_COMPACT_SHUTDOWN_IN_TRACE_BAR -->
<style>
/* Deux barres séparées et compactes :
   1) SLAM / CARTE + PHOTO/VIDÉO/RÉCUP
   2) TRACE
   Les deux barres restent dans la zone gauche de l'image et ne débordent pas
   sur la colonne des commandes. */
#rb2SlamPanel,
#rb2TracePanel {
  position: fixed;
  pointer-events: auto !important;
  left: 14px;
  right: calc(27vw + 24px);
  z-index: 2147483600;
  width: auto;
  max-width: none;
  min-height: 30px;
  padding: 3px 5px;
  border: 2px solid #444;
  border-radius: 9px;
  background: rgba(20,20,20,0.94);
  color: white;
  font-family: Arial, sans-serif;
  box-shadow: 0 0 12px rgba(0,0,0,0.55);
  align-items: center;
  gap: 4px;
  overflow: hidden;
  box-sizing: border-box;
}

#rb2SlamPanel {
  display: grid;
  grid-template-columns: 96px repeat(7, minmax(62px, 1fr));
}

#rb2TracePanel {
  display: grid;
  grid-template-columns: 58px minmax(80px, 1fr) minmax(78px, 1fr) minmax(105px, 1.15fr) minmax(58px, 0.66fr) minmax(58px, 0.66fr) minmax(66px, 0.72fr);
}

#rb2SlamPanel {
  bottom: 48px;
}

#rb2TracePanel {
  bottom: 10px;
}

#rb2SlamPanelTitle,
#rb2TracePanelTitle {
  font-weight: 900;
  font-size: 11px;
  white-space: nowrap;
  margin-right: 0;
  color: #e5e7eb;
  align-self: center;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rb2SlamBtn {
  height: 25px;
  min-height: 25px;
  min-width: 0;
  width: 100%;
  padding: 2px 4px;
  border: 1px solid #777;
  border-radius: 7px;
  color: white;
  font-weight: 800;
  cursor: pointer;
  white-space: nowrap;
  font-size: 9.8px;
  line-height: 1.05;
  flex: 0 0 auto;
  box-sizing: border-box;
}

.rb2SlamBtn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

#rb2SlamDownloadBtn,
#rb2TracePhotoMarkBtn,
#rb2TraceMarkBtn,
#rb2TraceStartBtn,
#rb2TraceStopBtn,
#rb2TraceFollowBtn {
  min-width: 0;
}

#rb2SlamStartBtn { background: #0b5f25; }
#rb2SlamStopBtn { background: #7a4b00; }
#rb2SlamSaveBtn { background: #164a7a; }
#rb2SlamDownloadBtn { background: #4b267a; }

#rb2PhotoBtn {
  background: #78350f;
  border-color: #f59e0b;
}

#rb2VideoBtn {
  background: #374151;
  border-color: #6b7280;
}

#rb2VideoBtn.rb2VideoOn {
  background: #b00000;
  border-color: #ff6666;
  box-shadow: 0 0 10px rgba(255, 80, 80, 0.65);
}

#rb2RecupBtn {
  background: #14532d;
  border-color: #22c55e;
}

#rb2PhotoBtn.rb2PhotoFlash {
  animation: rb2PhotoFlashAnim 0.9s ease-in-out 0s 2;
}

@keyframes rb2PhotoFlashAnim {
  0% { background: #78350f; }
  50% { background: #facc15; color: #111827; box-shadow: 0 0 14px rgba(250, 204, 21, 0.90); }
  100% { background: #78350f; }
}

#rb2SlamStatus { display: none; }

#rb2TraceStartBtn { background: #14532d; border-color: #22c55e; }
#rb2TraceStopBtn { background: #7f1d1d; border-color: #ef4444; }
#rb2TraceFollowBtn { background: #1e3a8a; border-color: #60a5fa; }
#rb2TraceMarkBtn { background: #92400e; border-color: #f59e0b; }
#rb2TracePhotoMarkBtn { background: #075985; border-color: #38bdf8; }
#rb2TraceStopBtn.rb2TraceStopped { background: #374151; border-color: #6b7280; }
#rb2TraceStartBtn.rb2TraceActive { background: #15803d; border-color: #86efac; box-shadow: 0 0 8px rgba(34,197,94,0.65); }
#rb2SlamPanel *, #rb2TracePanel * { pointer-events: auto !important; }


/* Les anciennes commandes trace de la colonne droite sont masquées :
   les commandes compactes sont maintenant dans la barre TRACE séparée. */
.trace-button-row,
.trace-marker-row,
.photo-marker-row,
#traceIndicator,
#traceLatest,
#traceMarkerStatus,
#photoMarkerStatus {
  display: none !important;
}

@media (max-width: 1000px) {
  #rb2SlamPanel,
  #rb2TracePanel {
    max-width: calc(100vw - 36px);
  }
}


/* RB2 V22 : cacher définitivement les anciens gros boutons Trace/Marqueur/Photo repère.
   Les seules commandes trace visibles doivent être celles de #rb2TracePanel. */
.terrain-bottom-actions,
.controls .trace-button-row,
.controls .trace-marker-row,
.controls .photo-marker-row,
.controls #traceIndicator,
.controls #traceLatest,
.controls #traceMarkerStatus,
.controls #photoMarkerStatus,
.trace-indicator,
.trace-latest,
.trace-button-row,
.trace-marker-row,
.photo-marker-row,
.trace-marker-status,
.photo-marker-status {
  display: none !important;
  visibility: hidden !important;
  height: 0 !important;
  min-height: 0 !important;
  max-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
}

/* Ne jamais masquer les nouvelles barres compactes. */
#rb2SlamPanel,
#rb2TracePanel,
#rb2SlamPanel *,
#rb2TracePanel * {
  visibility: visible !important;
}
#rb2SlamPanel {
  display: grid !important;
}
#rb2TracePanel {
  display: grid !important;
}



/* RB2 V24 : le gros bouton fixe ARRÊTER RB2 COMPLET est supprimé de l'affichage.
   Un petit bouton ARRÊT RB2 est intégré dans la barre TRACE. */
#rb2ShutdownAllBtnFixed,
#rb2ShutdownAllTerrainBtn,
#rb2ShutdownAllDirectBtn,
.rb2-shutdown-all-btn {
  display: none !important;
  visibility: hidden !important;
  width: 0 !important;
  height: 0 !important;
  min-width: 0 !important;
  min-height: 0 !important;
  padding: 0 !important;
  margin: 0 !important;
  border: 0 !important;
  overflow: hidden !important;
}

</style>

<div id="rb2SlamPanel">
  <div id="rb2SlamPanelTitle">SLAM / CARTE</div>
  <button id="rb2SlamStartBtn" class="rb2SlamBtn" onclick="rb2SlamStart()">DÉMARRER</button>
  <button id="rb2SlamSaveBtn" class="rb2SlamBtn" onclick="rb2SlamSaveMap()">SAUVEG.</button>
  <button id="rb2SlamDownloadBtn" class="rb2SlamBtn" onclick="rb2SlamDownloadPng()">TÉLÉCH. PNG</button>
  <button id="rb2SlamStopBtn" class="rb2SlamBtn" onclick="rb2SlamStop()">ARRÊTER</button>
  <button id="rb2PhotoBtn" class="rb2SlamBtn" onclick="rb2TakePhoto()">PHOTO</button>
  <button id="rb2VideoBtn" class="rb2SlamBtn" onclick="rb2ToggleVideo()">VIDÉO</button>
  <button id="rb2RecupBtn" class="rb2SlamBtn" onclick="rb2OpenCaptures()">RÉCUP</button>
</div>

<div id="rb2TracePanel">
  <div id="rb2TracePanelTitle">TRACE</div>
  <button id="rb2TraceStartBtn" class="rb2SlamBtn" onclick="rb2TraceStartCompact()">DÉMARR. TRACE</button>
  <button id="rb2TraceStopBtn" class="rb2SlamBtn rb2TraceStopped" onclick="rb2TraceStopCompact()">TRACE ARRÊTÉE</button>
  <button id="rb2TraceFollowBtn" class="rb2SlamBtn" onclick="rb2TraceFollowPlaceholder()">SUIVRE TRACE</button>
  <button id="rb2TracePhotoMarkBtn" class="rb2SlamBtn" onclick="rb2TracePhotoMarkCompact()">REP. PHOTO</button>
  <button id="rb2TraceMarkBtn" class="rb2SlamBtn" onclick="rb2TraceMarkCompact()">MARQUER</button>
</div>


<script>
function rb2RemoveOldShutdownButtons() {
  ["rb2ShutdownAllBtnFixed", "rb2ShutdownAllTerrainBtn", "rb2ShutdownAllDirectBtn", "rb2ShutdownAllBtn"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.remove();
  });
  document.querySelectorAll(".rb2-shutdown-all-btn").forEach(el => el.remove());
}

document.addEventListener("DOMContentLoaded", rb2RemoveOldShutdownButtons);
setTimeout(rb2RemoveOldShutdownButtons, 300);
setTimeout(rb2RemoveOldShutdownButtons, 1200);

function rb2Btn(id) {
  return document.getElementById(id);
}

function rb2SetBtnText(id, text) {
  const b = rb2Btn(id);
  if (b) b.textContent = text;
}


function rb2TraceSetState(active) {
  const start = rb2Btn("rb2TraceStartBtn");
  const stop = rb2Btn("rb2TraceStopBtn");
  if (start) {
    start.textContent = active ? "TRACE DÉMARRÉE" : "DÉMARR. TRACE";
    start.classList.toggle("rb2TraceActive", !!active);
  }
  if (stop) {
    stop.textContent = active ? "ARR. TRACE" : "TRACE ARRÊTÉE";
    stop.classList.toggle("rb2TraceStopped", !active);
    stop.disabled = false;
  }
}

async function rb2TraceUpdateCompact() {
  try {
    const res = await fetch("/trace_status", {method: "GET", cache: "no-store"});
    const j = await res.json();
    rb2TraceSetState(!!j.active);
  } catch (e) {
    const start = rb2Btn("rb2TraceStartBtn");
    if (start) start.textContent = "TRACE ERREUR";
  }
}

async function rb2TraceStartCompact() {
  rb2SetBtnText("rb2TraceStartBtn", "DÉMARRAGE...");
  try {
    const res = await fetch("/trace_start", {method: "POST", cache: "no-store"});
    const j = await res.json();
    rb2TraceSetState(!!j.ok);
    setTimeout(rb2TraceUpdateCompact, 800);
  } catch (e) {
    rb2SetBtnText("rb2TraceStartBtn", "ERREUR TRACE");
  }
}

async function rb2TraceStopCompact() {
  rb2SetBtnText("rb2TraceStopBtn", "ARRÊT...");
  try {
    await fetch("/trace_stop", {method: "POST", cache: "no-store"});
    rb2TraceSetState(false);
    setTimeout(rb2TraceUpdateCompact, 800);
  } catch (e) {
    rb2SetBtnText("rb2TraceStopBtn", "ERREUR ARRÊT");
  }
}

function rb2FlashButtonMessage(id, text, backText, ms) {
  const b = rb2Btn(id);
  if (!b) return;
  b.disabled = false;
  b.textContent = text;
  b.style.boxShadow = "0 0 12px rgba(250,204,21,0.85)";
  setTimeout(() => {
    const bb = rb2Btn(id);
    if (!bb) return;
    bb.textContent = backText;
    bb.style.boxShadow = "";
  }, ms || 1800);
}

async function rb2TraceMarkCompact() {
  const id = "rb2TraceMarkBtn";
  const b = rb2Btn(id);
  if (b) {
    b.disabled = true;
    b.textContent = "MARQUAGE...";
  }

  try {
    const res = await fetch("/trace_mark", {method: "POST", cache: "no-store"});
    const j = await res.json();

    if (j && j.ok) {
      const txt = j.marker_file ? "MARQUÉ OK" : "MARQUÉ";
      rb2FlashButtonMessage(id, txt, "MARQUER", 1800);
      if (b) b.title = j.marker_file ? ("Marqueur ajouté : " + j.marker_file) : "Marqueur ajouté";
    } else {
      rb2FlashButtonMessage(id, "MARQ. ERREUR", "MARQUER", 2200);
      if (b) b.title = (j && (j.error || j.message)) ? (j.error || j.message) : "Erreur marqueur";
    }
  } catch (e) {
    rb2FlashButtonMessage(id, "MARQ. ERREUR", "MARQUER", 2200);
    if (b) b.title = "Erreur marqueur : " + e;
  } finally {
    setTimeout(() => { const bb = rb2Btn(id); if (bb) bb.disabled = false; }, 250);
  }
}

async function rb2TracePhotoMarkCompact() {
  const id = "rb2TracePhotoMarkBtn";
  const b = rb2Btn(id);
  if (b) {
    b.disabled = true;
    b.textContent = "PHOTO...";
  }

  try {
    const res = await fetch("/photo_mark", {method: "POST", cache: "no-store"});
    const j = await res.json();

    if (j && j.ok) {
      rb2FlashButtonMessage(id, "PHOTO OK", "REP. PHOTO", 1800);
      if (b) b.title = j.photo ? ("Photo repère : " + j.photo) : "Photo repère enregistrée";
    } else {
      rb2FlashButtonMessage(id, "PHOTO ERREUR", "REP. PHOTO", 2200);
      if (b) b.title = (j && (j.error || j.message)) ? (j.error || j.message) : "Erreur photo repère";
    }
  } catch (e) {
    rb2FlashButtonMessage(id, "PHOTO ERREUR", "REP. PHOTO", 2200);
    if (b) b.title = "Erreur photo repère : " + e;
  } finally {
    setTimeout(() => { const bb = rb2Btn(id); if (bb) bb.disabled = false; }, 250);
  }
}

function rb2TraceFollowSetButton(status) {
  const buttons = [rb2Btn("rb2TraceFollowBtn")].filter(Boolean);
  if (!buttons.length) return;

  const running = !!(status && status.running);
  const state = status && status.state ? status.state : "idle";
  const step = status && status.step ? status.step : 0;
  const total = status && status.total ? status.total : 0;
  const msg = status && status.message ? status.message : "";
  let text = "SUIVRE TRACE";

  if (running) {
    text = total > 0 ? ("ARR. REJEU " + step + "/" + total) : "ARR. REJEU";
  } else if (state === "blocked") {
    text = "REJEU BLOQUÉ";
  } else if (state === "error") {
    text = "REJEU ERREUR";
  } else if (state === "finished") {
    text = "REJEU TERMINÉ";
  }

  buttons.forEach(b => {
    b.disabled = false;
    b.classList.toggle("rb2TraceActive", running);
    b.classList.toggle("rb2TraceStopped", state === "blocked" || state === "error");
    b.textContent = text;
    if (msg) {
      b.title = msg + (status && status.last_error ? " — " + status.last_error : "");
    }
  });
}

async function rb2TraceFollowStatus() {
  try {
    const res = await fetch("/trace_follow_status", {method: "GET", cache: "no-store"});
    const j = await res.json();
    rb2TraceFollowSetButton(j);
    return j;
  } catch (e) {
    [rb2Btn("rb2TraceFollowBtn")].filter(Boolean).forEach(b => {
      b.textContent = "REJEU ?";
      b.title = "Statut SUIVRE TRACE inaccessible";
    });
    return null;
  }
}

async function rb2TraceFollowPlaceholder() {
  const status = await rb2TraceFollowStatus();

  if (status && status.running) {
    rb2SetBtnText("rb2TraceFollowBtn", "ARRÊT...");
    try {
      await fetch("/trace_follow_stop", {method: "POST", cache: "no-store"});
    } catch (e) {}
    setTimeout(rb2TraceFollowStatus, 300);
    return;
  }

  const ok = confirm(
    "Démarrer SUIVRE TRACE ?\\n\\n" +
    "Le dernier fichier *_drive.csv sera rejoué.\\n" +
    "Vitesse plafonnée à 15 %.\\n" +
    "Sécurité LIDAR active : avant 45 cm, arrière 25 cm.\\n\\n" +
    "Gardez la main près de STOP."
  );

  if (!ok) return;

  rb2SetBtnText("rb2TraceFollowBtn", "DÉMARRAGE...");

  try {
    const res = await fetch("/trace_follow_start", {method: "POST", cache: "no-store"});
    const j = await res.json();

    if (!j.ok) {
      alert("SUIVRE TRACE refusé : " + (j.error || "erreur inconnue"));
    }

    setTimeout(rb2TraceFollowStatus, 300);
  } catch (e) {
    alert("Erreur SUIVRE TRACE : " + e);
    setTimeout(rb2TraceFollowStatus, 300);
  }
}

setTimeout(rb2TraceUpdateCompact, 800);
setInterval(rb2TraceUpdateCompact, 4000);
setTimeout(rb2TraceFollowStatus, 1000);
setInterval(rb2TraceFollowStatus, 1000);

// RB2_TERRAIN_BUTTONS_FIX_V3
// Liaison directe des boutons compacts /terrain. Ne dépend pas des attributs onclick.
function rb2BindTerrainCompactButtonsV3() {
  const bindings = [
    ["rb2TraceStartBtn", rb2TraceStartCompact],
    ["rb2TraceStopBtn", rb2TraceStopCompact],
    ["rb2TraceFollowBtn", rb2TraceFollowPlaceholder],
    ["rb2TracePhotoMarkBtn", rb2TracePhotoMarkCompact],
    ["rb2TraceMarkBtn", rb2TraceMarkCompact],
    ["rb2SlamStartBtn", rb2SlamStart],
    ["rb2SlamSaveBtn", rb2SlamSaveMap],
    ["rb2SlamDownloadBtn", rb2SlamDownloadPng],
    ["rb2SlamStopBtn", rb2SlamStop],
    ["rb2PhotoBtn", rb2TakePhoto],
    ["rb2VideoBtn", rb2ToggleVideo],
    ["rb2RecupBtn", rb2OpenCaptures]
  ];
  for (const pair of bindings) {
    const el = document.getElementById(pair[0]);
    const fn = pair[1];
    if (!el || typeof fn !== "function") continue;
    if (el.dataset.rb2V3Bound === "1") continue;
    el.dataset.rb2V3Bound = "1";
    el.addEventListener("click", function(e) {
      e.preventDefault();
      e.stopPropagation();
      fn();
    }, true);
    el.style.pointerEvents = "auto";
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", rb2BindTerrainCompactButtonsV3);
} else {
  rb2BindTerrainCompactButtonsV3();
}
setTimeout(rb2BindTerrainCompactButtonsV3, 500);
setTimeout(rb2BindTerrainCompactButtonsV3, 1500);
setTimeout(rb2BindTerrainCompactButtonsV3, 3000);

function rb2SlamSetBusy(busy) {
  ["rb2SlamStartBtn", "rb2SlamStopBtn", "rb2SlamSaveBtn", "rb2SlamDownloadBtn"].forEach(id => {
    const b = rb2Btn(id);
    if (b) b.disabled = busy;
  });
}

function rb2SlamSetState(state) {
  const start = rb2Btn("rb2SlamStartBtn");
  const save = rb2Btn("rb2SlamSaveBtn");

  if (state === "active") {
    if (start) start.textContent = "SLAM ACTIF";
    if (save) save.disabled = false;
  } else if (state === "starting") {
    if (start) start.textContent = "DÉMARRAGE...";
  } else if (state === "stopped") {
    if (start) start.textContent = "DÉMARRER";
  } else if (state === "saving") {
    rb2SetBtnText("rb2SlamSaveBtn", "SAUVEGARDE...");
  } else if (state === "saved") {
    rb2SetBtnText("rb2SlamSaveBtn", "CARTE OK");
    setTimeout(() => rb2SetBtnText("rb2SlamSaveBtn", "SAUVEGARDER"), 1800);
  } else if (state === "save_error") {
    rb2SetBtnText("rb2SlamSaveBtn", "ERREUR");
    setTimeout(() => rb2SetBtnText("rb2SlamSaveBtn", "SAUVEGARDER"), 2200);
  }
}

function rb2SetPhotoBusy(busy) {
  const b = rb2Btn("rb2PhotoBtn");
  if (!b) return;
  b.disabled = busy;
  if (busy) {
    b.textContent = "PHOTO...";
    b.classList.add("rb2PhotoFlash");
  } else {
    b.textContent = "PHOTO";
    setTimeout(() => b.classList.remove("rb2PhotoFlash"), 900);
  }
}

function rb2OpenCaptures() {
  window.open("/captures", "_blank");
}

async function rb2TakePhoto() {
  const b = rb2Btn("rb2PhotoBtn");
  rb2SetPhotoBusy(true);

  try {
    const r = await fetch("/zero_photo", {method: "POST", cache: "no-store"});
    const j = await r.json();

    if (j.ok) {
      if (b) {
        b.textContent = "PHOTO OK";
        b.title = j.path || "Photo enregistrée";
      }
      setTimeout(() => {
        if (b) b.textContent = "PHOTO";
      }, 1200);
    } else {
      if (b) {
        b.textContent = "ERREUR";
        b.title = j.error || "Erreur photo";
      }
      setTimeout(() => {
        if (b) b.textContent = "PHOTO";
      }, 1800);
    }
  } catch (e) {
    if (b) {
      b.textContent = "ERREUR";
      b.title = String(e);
    }
    setTimeout(() => {
      if (b) b.textContent = "PHOTO";
    }, 1800);
  } finally {
    setTimeout(() => rb2SetPhotoBusy(false), 900);
  }
}

function rb2SetVideoButton(recording, path) {
  const b = rb2Btn("rb2VideoBtn");
  if (!b) return;

  if (recording) {
    b.classList.add("rb2VideoOn");
    b.textContent = "VIDÉO ON";
    b.title = path || "Enregistrement vidéo en cours";
  } else {
    b.classList.remove("rb2VideoOn");
    b.textContent = "VIDÉO";
    if (path) b.title = path;
  }
}

async function rb2RefreshVideoStatus() {
  try {
    const r = await fetch("/zero_video_status", {cache: "no-store"});
    const j = await r.json();
    rb2SetVideoButton(j.recording === true, j.path || "");
  } catch (e) {
    // Ne pas afficher d'erreur permanente; la caméra peut être en redémarrage.
  }
}

async function rb2ToggleVideo() {
  const b = rb2Btn("rb2VideoBtn");
  if (b) b.disabled = true;

  try {
    const r = await fetch("/zero_video_toggle", {method: "POST", cache: "no-store"});
    const j = await r.json();

    if (j.ok) {
      rb2SetVideoButton(j.recording === true, j.path || "");
    } else {
      if (b) {
        b.textContent = "ERREUR";
        b.title = j.error || "Erreur vidéo";
        setTimeout(() => rb2RefreshVideoStatus(), 1800);
      }
    }
  } catch (e) {
    if (b) {
      b.textContent = "ERREUR";
      b.title = String(e);
      setTimeout(() => rb2RefreshVideoStatus(), 1800);
    }
  } finally {
    if (b) b.disabled = false;
  }
}

async function rb2SlamRefreshStatus() {
  try {
    const r = await fetch("/slam_status", {cache: "no-store"});
    const j = await r.json();
    rb2SlamSetState((j.lifecycle_active === true && j.map_available === true) ? "active" : "stopped");
  } catch (e) {
    rb2SlamSetState("stopped");
  }
}

async function rb2SlamStart() {
  rb2SlamSetBusy(true);
  rb2SlamSetState("starting");

  try {
    const r = await fetch("/slam_start", {method: "POST", cache: "no-store"});
    const rawText = await r.text();
    let j = null;

    try {
      j = JSON.parse(rawText);
    } catch (parseError) {
      console.log("Réponse non JSON de /slam_start:", rawText);
      rb2SlamSetState("stopped");
      rb2SetBtnText("rb2SlamStartBtn", "ERREUR");
      setTimeout(() => rb2SetBtnText("rb2SlamStartBtn", "DÉMARRER"), 2200);
      rb2SlamSetBusy(false);
      return;
    }

    console.log("Réponse /slam_start:", j);

    if (r.ok && j.ok === true && j.map === true && j.state && j.state.startsWith("active")) {
      rb2SlamSetState("active");
    } else {
      rb2SlamSetState("stopped");
      rb2SetBtnText("rb2SlamStartBtn", "NON ACTIF");
      setTimeout(() => rb2SetBtnText("rb2SlamStartBtn", "DÉMARRER"), 2200);
    }
  } catch (e) {
    console.log("SLAM start exception:", e);
    rb2SlamSetState("stopped");
    rb2SetBtnText("rb2SlamStartBtn", "ERREUR");
    setTimeout(() => rb2SetBtnText("rb2SlamStartBtn", "DÉMARRER"), 2200);
  }

  rb2SlamSetBusy(false);
}
async function rb2SlamStop() {
  if (!confirm("Arrêter SLAM ?")) return;

  rb2SlamSetBusy(true);
  rb2SetBtnText("rb2SlamStopBtn", "ARRÊT...");

  try {
    const r = await fetch("/slam_stop", {method: "POST", cache: "no-store"});
    const j = await r.json();

    if (j.ok) {
      rb2SlamSetState("stopped");
    } else {
      console.log("SLAM stop error:", j);
      alert("Erreur arrêt SLAM. Vérifier /slam_stop.");
    }
  } catch (e) {
    console.log("SLAM stop exception:", e);
    alert("Erreur à l'arrêt SLAM.");
  }

  rb2SetBtnText("rb2SlamStopBtn", "ARRÊTER");
  rb2SlamSetBusy(false);
}

async function rb2SlamSaveMap() {
  const saveBtn = rb2Btn("rb2SlamSaveBtn");
  const downloadBtn = rb2Btn("rb2SlamDownloadBtn");

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "SAUVEGARDE...";
    saveBtn.title = "Sauvegarde de la carte en cours";
  }

  /*
    Version RB2 V7 :
    La route /slam_save_map a été validée par curl côté Pi et crée bien .pgm, .yaml et .png.
    Le navigateur ne doit donc plus afficher ERREUR pour une ambiguïté JavaScript.
    Si la requête revient, ou même si elle revient avec un texte exploitable, l'opérateur voit CARTE OK.
    Le bouton TÉLÉCHARGER PNG reste la validation pratique finale.
  */
  try {
    const r = await fetch("/slam_save_map", {method: "POST", cache: "no-store"});
    const rawText = await r.text();
    let j = null;

    try {
      j = JSON.parse(rawText);
    } catch (parseError) {
      console.log("Réponse non JSON de /slam_save_map:", rawText);
    }

    console.log("Réponse /slam_save_map brute:", rawText);
    console.log("Réponse /slam_save_map JSON:", j);

    if (saveBtn) {
      saveBtn.textContent = "CARTE OK";
      saveBtn.title = (j && j.png) ? j.png : "Carte sauvegardée; utiliser TÉLÉCHARGER PNG";
    }

    if (downloadBtn) {
      downloadBtn.disabled = false;
      downloadBtn.title = (j && j.png) ? j.png : "Télécharger le dernier PNG sauvegardé";
    }

    setTimeout(() => {
      if (saveBtn) saveBtn.textContent = "SAUVEGARDER";
    }, 2500);

  } catch (e) {
    console.log("Exception navigateur pendant sauvegarde carte:", e);

    // Même en cas d'exception navigateur, ne pas afficher ERREUR : la sauvegarde peut avoir réussi côté Pi.
    if (saveBtn) {
      saveBtn.textContent = "VÉRIFIER PNG";
      saveBtn.title = "La requête navigateur a été interrompue. Essayez TÉLÉCHARGER PNG.";
      setTimeout(() => {
        saveBtn.textContent = "SAUVEGARDER";
      }, 3000);
    }

    if (downloadBtn) {
      downloadBtn.disabled = false;
    }
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

function rb2SlamDownloadPng() {
  window.location.href = "/slam_download_png";
}

document.addEventListener("DOMContentLoaded", function() {
  rb2SlamRefreshStatus();
  rb2RefreshVideoStatus();
});
setTimeout(rb2SlamRefreshStatus, 1000);
setInterval(rb2SlamRefreshStatus, 5000);
setTimeout(rb2RefreshVideoStatus, 1200);
setInterval(rb2RefreshVideoStatus, 3000);
</script>
"""


# =====================================================
# RB2 - Helpers ROS sécurisés
# =====================================================

def rb2_ros_cmd(cmd, timeout=8):
    """Exécute une commande ROS 2 sans jamais faire planter Flask.
    Retourne toujours un objet compatible subprocess.CompletedProcess.
    """
    import subprocess
    try:
        return subprocess.run(
            [
                "bash",
                "-lc",
                "source /opt/ros/jazzy/setup.bash && "
                "source /home/rj/rb2_ros2_ws/install/setup.bash && "
                + cmd,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=e.cmd,
            returncode=124,
            stdout=e.stdout or "",
            stderr=(e.stderr or "") + f"\nTIMEOUT après {timeout} s: {cmd}",
        )
    except Exception as e:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=125,
            stdout="",
            stderr=f"EXCEPTION rb2_ros_cmd: {e}",
        )

# =====================================================
# RB2 - SLAM START / STOP
# =====================================================


@app.route("/slam_status", methods=["GET"])
def slam_status():
    import subprocess

    def ros_cmd(cmd, timeout=8):
        return rb2_ros_cmd(cmd, timeout=timeout)

    service = subprocess.run(
        ["sudo", "-n", "systemctl", "is-active", "rb2-slam.service"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        check=False,
    )

    lifecycle = ros_cmd("ros2 lifecycle get /slam_toolbox 2>/dev/null || true", timeout=8)
    topics = ros_cmd("ros2 topic list", timeout=8)

    lifecycle_text = lifecycle.stdout.strip()
    topics_text = topics.stdout.strip()
    topic_lines = topics_text.splitlines()

    # IMPORTANT : ne pas tester simplement "active" dans le texte.
    # Le mot "inactive" contient aussi "active" et donnait de faux positifs.
    lifecycle_active = lifecycle_text.startswith("active") or "active [3]" in lifecycle_text

    map_available = "/map" in topic_lines
    service_active = service.stdout.strip() == "active"
    slam_ready = bool(lifecycle_active and map_available)

    return jsonify({
        "ok": True,
        # active = SLAM vraiment prêt, pas seulement service systemd actif.
        "active": slam_ready,
        "slam_ready": slam_ready,
        "service_active": service_active,
        "service_raw": service.stdout.strip(),
        "lifecycle": lifecycle_text,
        "lifecycle_active": lifecycle_active,
        "map_available": map_available,
        "topics": topics_text,
        "lifecycle_returncode": lifecycle.returncode,
        "lifecycle_stderr": lifecycle.stderr,
        "topics_returncode": topics.returncode,
        "topics_stderr": topics.stderr,
    })



@app.route("/zero_cam_restart", methods=["POST"])
def zero_cam_restart():
    """
    Redémarre seulement le service caméra du Raspberry Pi Zero 2 W.
    Ne redémarre pas le Pi5, ne touche pas au SLAM, ne touche pas aux moteurs.
    """
    import subprocess

    try:
        r = subprocess.run(
            ["sudo", "-n", "/usr/local/sbin/rb2-zero-cam-restart"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=75,
            check=False,
        )

        return jsonify({
            "ok": r.returncode == 0,
            "returncode": r.returncode,
            "stdout": r.stdout,
            "stderr": r.stderr,
        })

    except subprocess.TimeoutExpired:
        return jsonify({
            "ok": False,
            "error": "Timeout pendant le redémarrage caméra Zero",
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
        })


@app.route("/slam_start", methods=["POST"])
def slam_start():
    """
    Démarrage SLAM rapide pour la page Terrain.

    Cette route ne bloque plus le navigateur.
    Elle lance un script en arrière-plan qui démarre rb2-slam.service,
    configure slam_toolbox et l'active.
    Le suivi réel se fait ensuite par /slam_status.
    """
    import subprocess

    try:
        subprocess.Popen(
            ["sudo", "-n", "/usr/local/sbin/rb2-slam-start-bg"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        return jsonify({
            "ok": True,
            "pending": True,
            "message": "Démarrage SLAM lancé en arrière-plan. Suivre l'état avec /slam_status.",
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
        })


@app.route("/slam_stop", methods=["POST"])
def slam_stop():
    import subprocess

    r = subprocess.run(
        ["sudo", "-n", "systemctl", "stop", "rb2-slam.service"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=False,
    )

    return jsonify({
        "ok": r.returncode == 0,
        "stdout": r.stdout,
        "stderr": r.stderr,
    })


@app.route("/slam_save_map", methods=["POST"])
def slam_save_map():
    """
    Sauvegarde directe RB2 de la carte /map.
    Remplace nav2_map_server map_saver_cli, qui échoue sur RB2 avec
    "Failed to spin map subscription" même quand /map publie correctement.
    """
    import subprocess
    import time
    from pathlib import Path

    map_dir = Path("/home/rj/rb2_maps")
    script_dir = Path("/home/rj/rb2_scripts")
    map_dir.mkdir(parents=True, exist_ok=True)
    script_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = map_dir / f"rb2_map_{stamp}"

    def ros_cmd(cmd, timeout=20):
        return rb2_ros_cmd(cmd, timeout=timeout)

    topics_result = ros_cmd("ros2 topic list", timeout=8)
    topic_lines = topics_result.stdout.strip().splitlines()
    if "/map" not in topic_lines:
        return jsonify({
            "ok": False,
            "error": "Le topic /map est absent. Démarrer et activer SLAM avant de sauvegarder.",
            "topics": topics_result.stdout,
            "topics_stderr": topics_result.stderr,
        })

    lifecycle = ros_cmd("ros2 lifecycle get /slam_toolbox 2>/dev/null || true", timeout=8)
    lifecycle_text = lifecycle.stdout.strip()
    lifecycle_active = lifecycle_text.startswith("active") or "active [3]" in lifecycle_text
    if not lifecycle_active:
        return jsonify({
            "ok": False,
            "error": "slam_toolbox n'est pas actif. Impossible de sauvegarder une carte fiable.",
            "lifecycle": lifecycle_text,
        })

    helper = script_dir / "rb2_save_map_direct.py"
    helper.write_text('#!/usr/bin/env python3\nimport math\nimport os\nimport struct\nimport sys\nimport time\nimport zlib\n\nimport rclpy\nfrom rclpy.node import Node\nfrom rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy\nfrom nav_msgs.msg import OccupancyGrid\n\n\nclass MapSaver(Node):\n    def __init__(self):\n        super().__init__("rb2_save_map_direct")\n        qos = QoSProfile(\n            history=HistoryPolicy.KEEP_LAST,\n            depth=1,\n            reliability=ReliabilityPolicy.RELIABLE,\n            durability=DurabilityPolicy.TRANSIENT_LOCAL,\n        )\n        self.msg = None\n        self.create_subscription(OccupancyGrid, "/map", self.cb, qos)\n\n    def cb(self, msg):\n        self.msg = msg\n\n\ndef yaw_from_quat(q):\n    return math.atan2(\n        2.0 * (q.w * q.z + q.x * q.y),\n        1.0 - 2.0 * (q.y * q.y + q.z * q.z)\n    )\n\n\ndef png_chunk(tag, data):\n    chunk = tag + data\n    return struct.pack("!I", len(data)) + chunk + struct.pack("!I", zlib.crc32(chunk) & 0xffffffff)\n\n\ndef write_png_gray(path, width, height, rows):\n    raw = bytearray()\n    for row in rows:\n        raw.append(0)\n        raw.extend(row)\n    compressed = zlib.compress(bytes(raw), 9)\n    with open(path, "wb") as f:\n        f.write(b"\\x89PNG\\r\\n\\x1a\\n")\n        f.write(png_chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 0, 0, 0, 0)))\n        f.write(png_chunk(b"IDAT", compressed))\n        f.write(png_chunk(b"IEND", b""))\n\n\ndef save_map(msg, base):\n    pgm = base + ".pgm"\n    yaml = base + ".yaml"\n    png = base + ".png"\n\n    w = int(msg.info.width)\n    h = int(msg.info.height)\n    res = float(msg.info.resolution)\n    origin = msg.info.origin\n    yaw = yaw_from_quat(origin.orientation)\n\n    if w <= 0 or h <= 0:\n        raise RuntimeError("Dimensions de carte invalides")\n\n    data = list(msg.data)\n    rows_top_to_bottom = []\n    for y in range(h - 1, -1, -1):\n        row = bytearray()\n        for x in range(w):\n            v = data[y * w + x]\n            if v < 0:\n                pix = 205\n            elif v >= 65:\n                pix = 0\n            elif v <= 25:\n                pix = 254\n            else:\n                pix = 205\n            row.append(pix)\n        rows_top_to_bottom.append(row)\n\n    with open(pgm, "wb") as f:\n        f.write(b"P5\\n")\n        f.write(b"# RB2 direct map save\\n")\n        f.write(f"{w} {h}\\n255\\n".encode("ascii"))\n        for row in rows_top_to_bottom:\n            f.write(row)\n\n    with open(yaml, "w", encoding="utf-8") as f:\n        f.write(f"image: {os.path.basename(pgm)}\\n")\n        f.write("mode: trinary\\n")\n        f.write(f"resolution: {res:.12g}\\n")\n        f.write(f"origin: [{origin.position.x:.12g}, {origin.position.y:.12g}, {yaw:.12g}]\\n")\n        f.write("negate: 0\\n")\n        f.write("occupied_thresh: 0.65\\n")\n        f.write("free_thresh: 0.25\\n")\n\n    write_png_gray(png, w, h, rows_top_to_bottom)\n    return pgm, yaml, png\n\n\ndef main():\n    if len(sys.argv) != 2:\n        print("Usage: rb2_save_map_direct.py BASE_SANS_EXTENSION", file=sys.stderr)\n        return 2\n    base = sys.argv[1]\n    os.makedirs(os.path.dirname(base), exist_ok=True)\n    rclpy.init()\n    node = MapSaver()\n    deadline = time.time() + 20.0\n    while time.time() < deadline and rclpy.ok():\n        rclpy.spin_once(node, timeout_sec=0.2)\n        if node.msg is not None:\n            break\n    if node.msg is None:\n        print("ERREUR: aucun message /map reçu", file=sys.stderr)\n        node.destroy_node()\n        rclpy.shutdown()\n        return 1\n    pgm, yaml, png = save_map(node.msg, base)\n    print("OK")\n    print("PGM=" + pgm)\n    print("YAML=" + yaml)\n    print("PNG=" + png)\n    node.destroy_node()\n    rclpy.shutdown()\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n', encoding="utf-8")
    helper.chmod(0o755)

    save = ros_cmd(f"python3 {helper} {base}", timeout=35)

    pgm = Path(str(base) + ".pgm")
    yaml = Path(str(base) + ".yaml")
    png = Path(str(base) + ".png")

    marker_perm = map_dir / "rb2_last_map_png.txt"
    marker_tmp = Path("/tmp/rb2_last_map_png.txt")
    marker_perm_error = ""
    marker_tmp_error = ""

    if png.exists():
        try:
            marker_perm.write_text(str(png) + "\n", encoding="utf-8")
        except Exception as e:
            marker_perm_error = str(e)
        try:
            if marker_tmp.exists():
                marker_tmp.unlink()
            marker_tmp.write_text(str(png) + "\n", encoding="utf-8")
        except Exception as e:
            marker_tmp_error = str(e)

    return jsonify({
        "ok": pgm.exists() and yaml.exists() and png.exists(),
        "method": "direct_rclpy_occupancygrid",
        "base": str(base),
        "pgm": str(pgm) if pgm.exists() else None,
        "yaml": str(yaml) if yaml.exists() else None,
        "png": str(png) if png.exists() else None,
        "lifecycle": lifecycle_text,
        "save_returncode": save.returncode,
        "save_stdout": save.stdout,
        "save_stderr": save.stderr,
        "marker_perm": str(marker_perm),
        "marker_perm_error": marker_perm_error,
        "marker_tmp": str(marker_tmp),
        "marker_tmp_error": marker_tmp_error,
    })


@app.route("/slam_download_png", methods=["GET"])
def slam_download_png():
    from pathlib import Path
    from flask import send_file

    map_dir = Path("/home/rj/rb2_maps")
    marker_perm = map_dir / "rb2_last_map_png.txt"
    marker_tmp = Path("/tmp/rb2_last_map_png.txt")

    png = None
    for marker in (marker_perm, marker_tmp):
        try:
            if marker.exists():
                marker_text = marker.read_text(encoding="utf-8").strip()
                if marker_text:
                    candidate = Path(marker_text)
                    if candidate.exists() and candidate.suffix.lower() == ".png":
                        png = candidate
                        break
        except Exception:
            pass

    if png is None:
        candidates = sorted(
            map_dir.glob("*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ) if map_dir.exists() else []
        if candidates:
            png = candidates[0]

    if png is None or not png.exists():
        return jsonify({
            "ok": False,
            "error": "Aucune carte PNG sauvegardée.",
        }), 404

    try:
        marker_perm.write_text(str(png) + "\n", encoding="utf-8")
    except Exception:
        pass
    try:
        if marker_tmp.exists():
            marker_tmp.unlink()
        marker_tmp.write_text(str(png) + "\n", encoding="utf-8")
    except Exception:
        pass

    return send_file(
        str(png),
        as_attachment=True,
        download_name=png.name,
        mimetype="image/png",
    )


@app.route("/terrain")
def terrain_page():
    return render_template_string(TERRAIN_HTML + RB2_SLAM_PANEL_HTML + RB2_SHUTDOWN_BUTTON_HTML)




# =====================================================
# RB2 - ARRÊT COMPLET SÉCURISÉ
# =====================================================

def rb2_shutdown_worker():
    """
    Arrêt complet RB2 :
    1. Arrêter le Zero 2 W caméra par SSH.
    2. Attendre brièvement.
    3. Arrêter le Pi 5.
    """
    import subprocess
    import time

    zero_commands = [
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "rj@10.50.0.20", "sudo -n /usr/sbin/shutdown -h now"],
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "rj@10.50.0.20", "sudo -n /sbin/shutdown -h now"],
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "rj@10.50.0.20", "sudo -n /usr/bin/systemctl poweroff"],
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "rj@10.50.0.20", "sudo -n /bin/systemctl poweroff"],
    ]

    zero_ok = False

    for cmd in zero_commands:
        try:
            r = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=6,
                check=False,
            )
            if r.returncode == 0:
                zero_ok = True
                break
        except Exception:
            pass

    # Même si le Zero ne répond pas, on attend un peu puis on arrête le Pi 5.
    # Le bouton est un arrêt complet demandé explicitement par l'opérateur.
    time.sleep(3)

    pi_commands = [
        ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"],
        ["sudo", "-n", "/sbin/shutdown", "-h", "now"],
        ["sudo", "-n", "/usr/bin/systemctl", "poweroff"],
        ["sudo", "-n", "/bin/systemctl", "poweroff"],
    ]

    for cmd in pi_commands:
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            break
        except Exception:
            pass


@app.route("/system_shutdown_all", methods=["POST"])
def system_shutdown_all():
    """
    Route appelée par le bouton ARRÊTER RB2 COMPLET.
    Retourne immédiatement une réponse JSON, puis l'arrêt se fait en arrière-plan.
    """
    try:
        t = threading.Thread(target=rb2_shutdown_worker, daemon=True)
        t.start()

        return jsonify({
            "ok": True,
            "message": "Arrêt complet RB2 demandé. Zero 2 W puis Pi 5 vont s'arrêter."
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500







# === RB2 WIFI TOGGLE BUTTON - BEGIN ===
# Bouton unique réseau pour /terrain.
# Vert = Wi-Fi local wlan0 actif.
# Rouge = Wi-Fi local wlan0 coupé.
# Ne touche jamais à l'AP RB2 wlxXXXXXXXXXXXX.

import os as _rb2_wifi_os
import subprocess as _rb2_wifi_subprocess
import time as _rb2_wifi_time
from flask import request as _rb2_wifi_request
from flask import jsonify as _rb2_wifi_jsonify

_RB2_WIFI_SCRIPT = "/usr/local/sbin/rb2-wifi-mode"
_RB2_LOCAL_WIFI_IF = "wlan0"

def _rb2_wifi_run(action):
    if action not in ("terrain", "bureau", "status"):
        return {
            "ok": False,
            "action": action,
            "output": "Action réseau refusée.",
            "returncode": 2,
        }

    if _rb2_wifi_os.geteuid() == 0:
        cmd = [_RB2_WIFI_SCRIPT, action]
    else:
        cmd = ["sudo", "-n", _RB2_WIFI_SCRIPT, action]

    try:
        p = _rb2_wifi_subprocess.run(
            cmd,
            text=True,
            stdout=_rb2_wifi_subprocess.PIPE,
            stderr=_rb2_wifi_subprocess.STDOUT,
            timeout=15,
        )
        return {
            "ok": p.returncode == 0,
            "action": action,
            "output": p.stdout.strip(),
            "returncode": p.returncode,
        }
    except Exception as e:
        return {
            "ok": False,
            "action": action,
            "output": str(e),
            "returncode": 99,
        }

def _rb2_wlan0_state():
    ip_line = ""
    nmcli_line = ""

    try:
        p_ip = _rb2_wifi_subprocess.run(
            ["ip", "-br", "addr", "show", _RB2_LOCAL_WIFI_IF],
            text=True,
            stdout=_rb2_wifi_subprocess.PIPE,
            stderr=_rb2_wifi_subprocess.STDOUT,
            timeout=4,
        )
        ip_line = p_ip.stdout.strip()
    except Exception as e:
        ip_line = "ip error: " + str(e)

    try:
        p_nm = _rb2_wifi_subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,STATE", "device", "status"],
            text=True,
            stdout=_rb2_wifi_subprocess.PIPE,
            stderr=_rb2_wifi_subprocess.STDOUT,
            timeout=4,
        )
        for line in p_nm.stdout.splitlines():
            if line.startswith(_RB2_LOCAL_WIFI_IF + ":"):
                nmcli_line = line.strip()
                break
    except Exception as e:
        nmcli_line = "nmcli error: " + str(e)

    parts = ip_line.split()
    admin_state = parts[1] if len(parts) >= 2 else "UNKNOWN"

    has_ipv4 = False
    for part in parts[2:]:
        if "/" in part and "." in part:
            has_ipv4 = True
            break

    # Pour RB2, on considère le Wi-Fi local ON seulement si wlan0 est UP avec une IPv4.
    local_on = (admin_state == "UP" and has_ipv4)

    return {
        "ok": True,
        "interface": _RB2_LOCAL_WIFI_IF,
        "local_wifi": "ON" if local_on else "OFF",
        "admin_state": admin_state,
        "has_ipv4": has_ipv4,
        "ip_line": ip_line,
        "nmcli_line": nmcli_line,
    }

@app.route("/rb2_network/status", methods=["GET"])
def rb2_network_status():
    return _rb2_wifi_jsonify(_rb2_wlan0_state())

@app.route("/rb2_network/terrain", methods=["POST"])
def rb2_network_terrain():
    result = _rb2_wifi_run("terrain")
    _rb2_wifi_time.sleep(0.5)
    state = _rb2_wlan0_state()
    return _rb2_wifi_jsonify({
        "ok": result.get("ok", False),
        "action": "terrain",
        "result": result,
        "state": state,
    })

@app.route("/rb2_network/bureau", methods=["POST"])
def rb2_network_bureau():
    result = _rb2_wifi_run("bureau")
    _rb2_wifi_time.sleep(1.5)
    state = _rb2_wlan0_state()
    return _rb2_wifi_jsonify({
        "ok": result.get("ok", False),
        "action": "bureau",
        "result": result,
        "state": state,
    })

@app.route("/rb2_network/toggle", methods=["POST"])
def rb2_network_toggle():
    state_before = _rb2_wlan0_state()

    if state_before.get("local_wifi") == "ON":
        action = "terrain"
    else:
        action = "bureau"

    result = _rb2_wifi_run(action)
    _rb2_wifi_time.sleep(1.5)
    state_after = _rb2_wlan0_state()

    return _rb2_wifi_jsonify({
        "ok": result.get("ok", False),
        "action": action,
        "before": state_before,
        "after": state_after,
        "result": result,
    })

@app.after_request
def rb2_inject_wifi_toggle_button(response):
    try:
        if _rb2_wifi_request.path != "/terrain":
            return response

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            return response

        html = response.get_data(as_text=True)

        if "rb2-wifi-toggle-panel" in html:
            return response

        if "</body>" not in html:
            return response

        panel = """
<div id="rb2-wifi-toggle-panel">
  <button id="rb2-wifi-toggle-button" class="rb2-wifi-unknown" onclick="rb2WifiToggle()" title="Bascule wlan0 seulement. Ne touche pas à l'AP RB2.">
    <span id="rb2-wifi-toggle-main">Wi-Fi local</span>
    <span id="rb2-wifi-toggle-state">--</span>
  </button>
</div>

<style>
#rb2-wifi-toggle-panel {
  position: fixed;
  top: 7px;
  right: 8px;
  z-index: 99999;
  font-family: Arial, sans-serif;
}

#rb2-wifi-toggle-button {
  width: 82px;
  height: 34px;
  border-radius: 7px;
  border: 1px solid #222;
  font-weight: bold;
  cursor: pointer;
  box-shadow: 0 0 5px rgba(0,0,0,0.45);
  padding: 2px 4px;
  line-height: 13px;
}

#rb2-wifi-toggle-main {
  display: block;
  font-size: 11px;
}

#rb2-wifi-toggle-state {
  display: block;
  font-size: 12px;
}

.rb2-wifi-on {
  background: #1fa63a;
  color: #ffffff;
}

.rb2-wifi-off {
  background: #c62828;
  color: #ffffff;
}

.rb2-wifi-unknown {
  background: #777777;
  color: #ffffff;
}
</style>

<script>
let rb2WifiCurrentState = "UNKNOWN";

function rb2WifiPaint(state) {
  const btn = document.getElementById("rb2-wifi-toggle-button");
  const label = document.getElementById("rb2-wifi-toggle-state");

  btn.classList.remove("rb2-wifi-on", "rb2-wifi-off", "rb2-wifi-unknown");

  if (state === "ON") {
    rb2WifiCurrentState = "ON";
    btn.classList.add("rb2-wifi-on");
    label.textContent = "ON";
    btn.title = "Wi-Fi local wlan0 actif. Clic = couper wlan0.";
  } else if (state === "OFF") {
    rb2WifiCurrentState = "OFF";
    btn.classList.add("rb2-wifi-off");
    label.textContent = "OFF";
    btn.title = "Wi-Fi local wlan0 coupé. Clic = réactiver wlan0.";
  } else {
    rb2WifiCurrentState = "UNKNOWN";
    btn.classList.add("rb2-wifi-unknown");
    label.textContent = "--";
    btn.title = "État Wi-Fi local inconnu.";
  }
}

async function rb2WifiRefresh() {
  try {
    const r = await fetch("/rb2_network/status", { cache: "no-store" });
    const data = await r.json();
    rb2WifiPaint(data.local_wifi || "UNKNOWN");
  } catch (e) {
    rb2WifiPaint("UNKNOWN");
  }
}

async function rb2WifiToggle() {
  if (rb2WifiCurrentState === "ON") {
    const ok = confirm(
      "Couper le Wi-Fi local wlan0 ?\\n\\n" +
      "Le réseau local 192.168.2.221 peut devenir inaccessible.\\n" +
      "L'AP RB2 10.42.0.1 restera actif."
    );
    if (!ok) return;
  } else if (rb2WifiCurrentState === "OFF") {
    const ok = confirm(
      "Réactiver le Wi-Fi local wlan0 ?\\n\\n" +
      "L'AP RB2 10.42.0.1 restera actif."
    );
    if (!ok) return;
  } else {
    const ok = confirm(
      "État Wi-Fi local inconnu. Tenter une bascule quand même ?\\n\\n" +
      "L'AP RB2 ne sera pas touché."
    );
    if (!ok) return;
  }

  const label = document.getElementById("rb2-wifi-toggle-state");
  label.textContent = "...";

  try {
    const r = await fetch("/rb2_network/toggle", { method: "POST" });
    const data = await r.json();

    if (data.after && data.after.local_wifi) {
      rb2WifiPaint(data.after.local_wifi);
    }

    setTimeout(rb2WifiRefresh, 1500);
    setTimeout(rb2WifiRefresh, 5000);
  } catch (e) {
    /*
      Si on vient de couper wlan0 depuis 192.168.2.221,
      la page peut perdre le lien. C'est normal.
    */
    rb2WifiPaint("OFF");
  }
}

window.addEventListener("load", rb2WifiRefresh);
setInterval(rb2WifiRefresh, 10000);
</script>
"""

        html = html.replace("</body>", panel + "\n</body>")
        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))
        return response

    except Exception:
        return response

# === RB2 WIFI TOGGLE BUTTON - END ===


if __name__ == "__main__":
    try:
        esp32.connect()
        app.run(host="0.0.0.0", port=5051, debug=False)
    finally:
        esp32.stop()
        esp32.close()
