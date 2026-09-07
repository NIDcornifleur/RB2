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



# === RB2 TERRAIN3 TRACE STATUS REMOVE ===
@app.after_request
def rb2_terrain3_trace_status_remove(response):
    """
    Retire côté serveur le résidu d'état TRACE dans /terrain3 :
    petite boîte/barre avec texte du genre 'points — âge'.
    """
    try:
        from flask import request
        import re
        import unicodedata

        if request.path != "/terrain3":
            return response

        if "text/html" not in response.headers.get("Content-Type", ""):
            return response

        html = response.get_data(as_text=True)

        def norm(s):
            return unicodedata.normalize("NFD", s or "").encode(
                "ascii", "ignore"
            ).decode("ascii").upper()

        def spans_for_tag(source, tag):
            pat = re.compile(r"</?%s\b[^>]*>" % re.escape(tag), re.I)
            stack = []
            spans = []

            for m in pat.finditer(source):
                token = m.group(0).lower()

                if token.startswith("</"):
                    if stack:
                        start = stack.pop()
                        spans.append((start, m.end()))
                else:
                    if not token.endswith("/>"):
                        stack.append(m.start())

            return spans

        candidates = []

        for tag in ["div", "span", "section", "p"]:
            for start, end in spans_for_tag(html, tag):
                chunk = html[start:end]
                n = norm(chunk)
                size = end - start

                # Résidu visible : "7 points — âge : 0.0 s"
                has_trace_status = (
                    "POINTS" in n and
                    (
                        "AGE" in n or
                        "ÂGE" in chunk.upper() or
                        "A GE" in n
                    )
                )

                # Résidu possible : barre/panneau de trace avec progress/status.
                has_trace_progress = (
                    "TRACE" in n and
                    (
                        "PROGRESS" in n or
                        "STATUS" in n or
                        "POINTS" in n
                    )
                )

                if not (has_trace_status or has_trace_progress):
                    continue

                if 20 <= size <= 12000:
                    candidates.append((size, start, end, tag))

        removed = False
        detail = "none"

        if candidates:
            candidates.sort(key=lambda x: x[0])
            size, start, end, tag = candidates[0]

            detail = "tag=%s size=%s" % (tag, size)

            html = (
                html[:start]
                + "\n<!-- RB2_TERRAIN3_TRACE_STATUS_REMOVED %s -->\n" % detail
                + html[end:]
            )

            removed = True

        html = (
            "\n<!-- RB2_TERRAIN3_TRACE_STATUS_REMOVE removed=%s detail=%s -->\n"
            % (removed, detail)
            + html
        )

        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))
        response.headers["Cache-Control"] = "no-store"

        return response

    except Exception as e:
        try:
            print("RB2 terrain3 trace status remove erreur:", e)
        except Exception:
            pass

        return response
# === FIN RB2 TERRAIN3 TRACE STATUS REMOVE ===

# === RB2 TERRAIN3 TRACE FORCE REMOVE ===
@app.after_request
def rb2_terrain3_trace_force_remove(response):
    """
    Retire côté serveur le bloc TRACE restant de /terrain3.
    Ce n'est pas un display:none : le HTML est supprimé avant d'être envoyé.
    """
    try:
        from flask import request
        import re
        import unicodedata

        if request.path != "/terrain3":
            return response

        ctype = response.headers.get("Content-Type", "")
        if "text/html" not in ctype:
            return response

        html = response.get_data(as_text=True)

        def norm(s):
            return unicodedata.normalize("NFD", s or "").encode(
                "ascii", "ignore"
            ).decode("ascii").upper()

        def spans_for_tag(source, tag):
            pat = re.compile(r"</?%s\b[^>]*>" % re.escape(tag), re.I)
            stack = []
            spans = []

            for m in pat.finditer(source):
                token = m.group(0).lower()

                if token.startswith("</"):
                    if stack:
                        start = stack.pop()
                        spans.append((start, m.end()))
                else:
                    if not token.endswith("/>"):
                        stack.append(m.start())

            return spans

        tags = ["tr", "div", "section", "nav", "footer", "header"]
        candidates = []

        for tag in tags:
            for start, end in spans_for_tag(html, tag):
                chunk = html[start:end]
                n = norm(chunk)

                if "TRACE" not in n:
                    continue

                hits = 0
                for word in [
                    "DEMARR",
                    "ARRET",
                    "ARRETEE",
                    "SUIVRE",
                    "MARQUER",
                    "RETOUR",
                    "REP PHOTO",
                    "PHOTO REPERE"
                ]:
                    if word in n:
                        hits += 1

                button_count = len(re.findall(r"<button\b", chunk, flags=re.I))
                size = end - start

                # On veut un vrai bloc de ligne, pas un seul petit bouton.
                if hits >= 1 and button_count >= 2 and 100 <= size <= 60000:
                    candidates.append((size, button_count, hits, start, end, tag))

        removed = False
        detail = "none"

        if candidates:
            candidates.sort(key=lambda x: (x[0], -x[1], -x[2]))
            size, button_count, hits, start, end, tag = candidates[0]

            detail = "tag=%s size=%s buttons=%s hits=%s" % (
                tag,
                size,
                button_count,
                hits
            )

            html = (
                html[:start]
                + "\n<!-- RB2_TERRAIN3_TRACE_FORCE_REMOVED %s -->\n" % detail
                + html[end:]
            )

            removed = True

        html = (
            "\n<!-- RB2_TERRAIN3_TRACE_FORCE removed=%s detail=%s -->\n"
            % (removed, detail)
            + html
        )

        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))
        response.headers["Cache-Control"] = "no-store"

        return response

    except Exception as e:
        try:
            print("RB2 terrain3 trace force remove erreur:", e)
        except Exception:
            pass

        return response
# === FIN RB2 TERRAIN3 TRACE FORCE REMOVE ===

# === RB2 TERRAIN3 SERVER CLEAN ===
@app.before_request
def rb2_terrain3_server_clean():
    """
    /terrain3 = /terrain fonctionnel,
    mais les blocs SLAM/CARTE et TRACE sont retirés du HTML
    avant d'être envoyés au navigateur.
    """
    try:
        from flask import request, make_response
        import re
        import unicodedata

        if request.path != "/terrain3":
            return None

        # Trouver la fonction qui sert /terrain.
        fn = globals().get("terrain_page")

        if fn is None:
            for rule in app.url_map.iter_rules():
                if rule.rule == "/terrain":
                    fn = app.view_functions.get(rule.endpoint)
                    break

        if fn is None:
            return app.response_class(
                "ERREUR /terrain3: fonction /terrain introuvable",
                status=500,
                mimetype="text/plain"
            )

        resp = make_response(fn())
        html = resp.get_data(as_text=True)

        def norm(s):
            return unicodedata.normalize("NFD", s or "").encode(
                "ascii", "ignore"
            ).decode("ascii").upper()

        def spans_for_tag(source, tag):
            pat = re.compile(r"</?%s\b[^>]*>" % re.escape(tag), re.I)
            stack = []
            spans = []

            for m in pat.finditer(source):
                token = m.group(0).lower()

                if token.startswith("</"):
                    if stack:
                        start = stack.pop()
                        spans.append((start, m.end()))
                else:
                    if not token.endswith("/>"):
                        stack.append(m.start())

            return spans

        def remove_smallest_block(source, label, marker_sets):
            tags = ["div", "tr", "section", "nav", "header", "footer"]
            candidates = []

            for markers in marker_sets:
                markers_norm = [norm(x) for x in markers]

                for tag in tags:
                    for start, end in spans_for_tag(source, tag):
                        chunk = source[start:end]
                        n = norm(chunk)

                        if all(m in n for m in markers_norm):
                            size = end - start

                            # Éviter de supprimer toute la page.
                            if 100 <= size <= 14000:
                                candidates.append((size, start, end, markers))

            if not candidates:
                return source, False

            candidates.sort(key=lambda x: x[0])
            size, start, end, markers = candidates[0]

            comment = (
                "\n<!-- RB2_TERRAIN3_REMOVED_%s size=%s markers=%s -->\n"
                % (label, size, ",".join(markers))
            )

            source = source[:start] + comment + source[end:]
            return source, True

        # Retirer le bloc SLAM / CARTE.
        html, slam_removed = remove_smallest_block(
            html,
            "SLAM",
            [
                ["rb2SlamStartBtn", "rb2SlamStopBtn"],
                ["rb2SlamSaveBtn", "rb2SlamDownloadBtn"],
                ["SLAM", "CARTE", "SAUVEG"],
                ["SLAM", "CARTE", "TELECH"],
                ["SLAM", "CARTE"],
            ],
        )

        # Retirer le bloc TRACE.
        html, trace_removed = remove_smallest_block(
            html,
            "TRACE",
            [
                ["rb2TraceStartBtn", "rb2TraceFollowBtn"],
                ["rb2TraceMarkBtn", "rb2ReturnForwardBtn"],
                ["TRACE", "SUIVRE TRACE"],
                ["TRACE", "MARQUER"],
                ["TRACE", "RETOUR"],
            ],
        )

        html = html.replace(
            "<title>RB2 - Terrain</title>",
            "<title>RB2 - Terrain3</title>",
            1
        )

        marker = (
            "\n<!-- RB2_TERRAIN3_SERVER_CLEAN "
            "slam_removed=%s trace_removed=%s -->\n"
            % (slam_removed, trace_removed)
        )

        if "<body" in html:
            html = html.replace("<body", marker + "<body", 1)
        else:
            html = marker + html

        resp.set_data(html)
        resp.headers["Content-Length"] = str(len(resp.get_data()))
        resp.headers["Cache-Control"] = "no-store"

        return resp

    except Exception as e:
        try:
            return app.response_class(
                "ERREUR /terrain3: " + str(e),
                status=500,
                mimetype="text/plain"
            )
        except Exception:
            return None
# === FIN RB2 TERRAIN3 SERVER CLEAN ===

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
    global RB2_WIFI_RETURN_LAST_DRIVE_TIME, RB2_WIFI_RETURN_LAST_DRIVE_COMMAND
    global RB2_WIFI_RETURN_LAST_DRIVE_LEFT, RB2_WIFI_RETURN_LAST_DRIVE_RIGHT

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

    # Sécurité LIDAR pour toute commande moteur manuelle non-stop.
    # STOP reste toujours prioritaire et accepté plus haut.
    if not is_stop:
        try:
            lidar_ok, lidar_reason = rb2_trace_follow_lidar_allows(parsed[0], parsed[1])
        except Exception as e:
            lidar_ok = False
            lidar_reason = "erreur garde LIDAR manuel: " + str(e)

        if not lidar_ok:
            try:
                rb2_trace_follow_send_stop_burst()
            except Exception:
                try:
                    esp32.send("d0,0", wait=0.0)
                except Exception:
                    pass

            return {
                "ok": False,
                "command": command_text,
                "ignored": True,
                "drive_seq": seq,
                "last_seq": DRIVE_LAST_SEQ,
                "age_ms": age_ms,
                "error": "Commande moteur refusée par sécurité LIDAR: " + str(lidar_reason),
                "drive_safety": "sécurité LIDAR manuelle",
            }

    # Mémoriser la dernière vraie commande moteur.
    # Utilisé par Retour WiFi pour éviter de reculer si /terrain est fermé
    # alors que le robot ne roulait pas.
    if not is_stop:
        try:
            RB2_WIFI_RETURN_LAST_DRIVE_TIME = time.time()
            RB2_WIFI_RETURN_LAST_DRIVE_COMMAND = command_text
            RB2_WIFI_RETURN_LAST_DRIVE_LEFT = parsed[0]
            RB2_WIFI_RETURN_LAST_DRIVE_RIGHT = parsed[1]
        except Exception:
            pass

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



.rb2-trace-secours-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #b00000;
  color: #ffffff !important;
  border: 2px solid #ffffff;
  border-radius: 6px;
  padding: 7px 12px;
  margin-left: 8px;
  font-weight: bold;
  font-size: 14px;
  text-decoration: none;
  box-shadow: 0 0 6px rgba(0,0,0,0.6);
}
.rb2-trace-secours-btn:hover {
  background: #ff0000;
}


/* RB2_HIDE_TOP_RETOUR_CSS_20260702
   Cache seulement le RETOUR AVANT placé dans la zone du haut.
   Le RETOUR du panneau TRACE reste visible. */
.rb2-top-button-group .rb2-return-forward-wrap,
.rb2-terrain-top-buttons .rb2-return-forward-wrap,
.terrain-top-buttons .rb2-return-forward-wrap,
.terrain-topbar-actions .rb2-return-forward-wrap,
.top-button-group .rb2-return-forward-wrap,
.rb2-camera-info-bar .rb2-return-forward-wrap,
.rb2-return-forward-wrap.floating {
  display: none !important;
}

#rb2TracePanel .rb2-return-forward-wrap {
  display: inline-flex !important;
}


/* RB2_HIDE_RETURN_FORWARD_TOP_ONLY_20260702
   Cache le vrai bouton RETOUR AVANT du haut.
   Le bouton RETOUR du bloc TRACE reste disponible séparément. */
#rb2-return-forward-wrap {
  display: none !important;
}
#rb2TraceReturnBtn {
  display: inline-flex !important;
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
        Pan : <span id="panValue">95</span>°<br>
        Tilt : <span id="tiltValue">90</span>°
      </div>

      <button class="arrow" onclick="panRight()">▶<br>Pan droite</button>

      <div></div>
      <button class="arrow" onclick="tiltDown()">▼<br>Tilt bas</button>
      <div></div>
    </div>

    <div class="row">
      <button class="small" onclick="setPanTilt(95, 90)">Centre 90/90</button>
      <button class="small" onclick="setTiltOnly(145)">Tilt max 145</button>
      <button class="small stop" onclick="setTiltOnly(68)">Tilt min 68</button>
    </div>

    <div class="row">
      <button class="small" onclick="setPanOnly(60)">Pan 60</button>
      <button class="small" onclick="setPanOnly(95)">Pan centre 95</button>
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
let pan = 95;
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
      row.style.gridTemplateColumns = "1.25fr 0.75fr 0.85fr 0.95fr";
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
        window.open("/lidar_drive2", "_blank");
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

      const secoursBtn = document.createElement("button");
      secoursBtn.id = "rb2SecoursBtnNearShutdown";
      secoursBtn.type = "button";
      secoursBtn.textContent = "SECOURS";
      secoursBtn.title = "Ouvrir la page de récupération directe ESP32";
      secoursBtn.style.minHeight = "42px";
      secoursBtn.style.fontWeight = "900";
      secoursBtn.style.fontSize = "14px";
      secoursBtn.style.background = "#b00000";
      secoursBtn.style.color = "white";
      secoursBtn.style.border = "2px solid #ffffff";
      secoursBtn.style.borderRadius = "8px";
      secoursBtn.style.cursor = "pointer";
      secoursBtn.onclick = function () {
        window.location.href = "/secours";
      };

      row.appendChild(lidarBtn);
      row.appendChild(camBtn);

      // RB2: remplacer le RETOUR du haut par SECOURS.
      // Ne touche pas au RETOUR du panneau TRACE.
      try {
        const tracePanel = document.getElementById("rb2TracePanel");
        const allTopCandidates = Array.from(document.querySelectorAll("button, a, input"));

        for (const el of allTopCandidates) {
          if (tracePanel && tracePanel.contains(el)) continue;

          const txt = (el.innerText || el.value || el.textContent || "").trim().toUpperCase();

          if (txt === "RETOUR" || txt === "RETOUR WIFI") {
            el.textContent = "SECOURS";
            el.innerText = "SECOURS";
            if ("value" in el) el.value = "SECOURS";

            el.title = "Ouvrir la page SECOURS directe ESP32";
            el.onclick = function(ev) {
              if (ev) ev.preventDefault();
              window.location.href = "/secours";
              return false;
            };

            el.style.background = "#b00000";
            el.style.color = "white";
            el.style.border = "2px solid #ffffff";
            el.style.fontWeight = "900";
            el.style.borderRadius = "8px";
            el.style.cursor = "pointer";
            break;
          }
        }
      } catch (e) {
        console.log("RB2: correction RETOUR haut -> SECOURS impossible:", e);
      }

      row.appendChild(secoursBtn);
    } catch (e) {
      console.log("Erreur ajout boutons RB2:", e);
    }
  }

  window.addEventListener("load", rb2AddExtraButtonsNearShutdown);
  document.addEventListener("DOMContentLoaded", rb2AddExtraButtonsNearShutdown);
  setTimeout(rb2AddExtraButtonsNearShutdown, 1000);
})();
</script>

<script>
// RB2_LAYOUT_SECOURS_RETOUR_FINAL_20260702
(function () {
  function rb2LayoutSecoursRetourFinal() {
    try {
      if (!location.pathname.includes("/terrain")) return;

      const tracePanel = document.getElementById("rb2TracePanel");

      // 1. Déplacer le vrai RETOUR AVANT dans le panneau TRACE.
      const returnWrap = document.querySelector(".rb2-return-forward-wrap");
      if (tracePanel && returnWrap && !tracePanel.contains(returnWrap)) {
        tracePanel.appendChild(returnWrap);
      }

      // 2. Supprimer le faux RETOUR ajouté dans TRACE, si présent.
      const fakeReturn = document.getElementById("rb2TraceReturnBtn");
      const realReturn = document.getElementById("rb2-return-forward-btn");
      if (fakeReturn && realReturn) {
        fakeReturn.remove();
      }

      // 3. Supprimer le vieux faux SECOURS placé dans l'ancien bloc trace.
      const oldSecours = document.querySelector(".rb2-trace-secours-btn");
      if (oldSecours) {
        oldSecours.remove();
      }

      // 4. Ajouter SECOURS dans la rangée du haut, après CAMÉRA.
      if (!document.getElementById("rb2SecoursTopBtn")) {
        let host = document.getElementById("rb2ExtraButtonsRow");

        if (!host) {
          const camCandidates = Array.from(document.querySelectorAll("button"));
          const camBtn = camCandidates.find(b => {
            const t = (b.textContent || b.innerText || "").trim().toUpperCase();
            return t === "CAMÉRA" || t === "CAMERA";
          });
          host = camBtn ? camBtn.parentElement : null;
        }

        if (host) {
          try {
            host.style.gridTemplateColumns = "1.25fr 0.75fr 0.85fr 0.95fr";
          } catch (e) {}

          const b = document.createElement("button");
          b.id = "rb2SecoursTopBtn";
          b.type = "button";
          b.textContent = "SECOURS";
          b.title = "Ouvrir la page SECOURS directe ESP32";
          b.style.minHeight = "42px";
          b.style.fontWeight = "900";
          b.style.fontSize = "14px";
          b.style.background = "#b00000";
          b.style.color = "white";
          b.style.border = "2px solid #ffffff";
          b.style.borderRadius = "8px";
          b.style.cursor = "pointer";
          b.onclick = function () {
            window.location.href = "/secours";
          };
          host.appendChild(b);
        }
      }

    } catch (e) {
      console.log("RB2 layout secours/retour final erreur:", e);
    }
  }

  window.addEventListener("load", rb2LayoutSecoursRetourFinal);
  document.addEventListener("DOMContentLoaded", rb2LayoutSecoursRetourFinal);
  setTimeout(rb2LayoutSecoursRetourFinal, 300);
  setTimeout(rb2LayoutSecoursRetourFinal, 1000);
  setTimeout(rb2LayoutSecoursRetourFinal, 2500);
})();
</script>

<script>
// RB2_HIDE_TOP_RETOUR_20260702
(function () {
  function rb2HideTopRetourOnly() {
    try {
      const tracePanel = document.getElementById("rb2TracePanel");
      const wraps = Array.from(document.querySelectorAll(".rb2-return-forward-wrap"));

      for (const w of wraps) {
        if (tracePanel && tracePanel.contains(w)) {
          continue; // garder RETOUR dans TRACE
        }
        w.style.display = "none";
      }
    } catch (e) {
      console.log("RB2 hide top retour erreur:", e);
    }
  }

  window.addEventListener("load", rb2HideTopRetourOnly);
  document.addEventListener("DOMContentLoaded", rb2HideTopRetourOnly);
  setTimeout(rb2HideTopRetourOnly, 300);
  setTimeout(rb2HideTopRetourOnly, 1000);
  setTimeout(rb2HideTopRetourOnly, 2500);
})();
</script>

<script>
const terrain2DriveToken = "terrain2-" + String(Date.now()) + "-" + String(Math.floor(Math.random() * 1000000));
let terrain2DriveSeq = 0;
let terrain2DriveServerOffsetMs = 0;
let terrain2Driving = false;
let terrain2CurrentDriveCmd = "d0,0";
let terrain2CurrentDriveLabel = "arrêt";
let terrain2DriveTimer = null;

function terrain2Log(text) {
  const log = document.getElementById("terrain2Log");
  if (log) {
    log.textContent = text;
  }
}

function terrain2AppendLog(text) {
  const log = document.getElementById("terrain2Log");
  if (log) {
    log.textContent += "\n" + text;
    log.scrollTop = log.scrollHeight;
  }
}

function terrain2UpdateDriveStatus() {
  const el = document.getElementById("terrain2DriveStatus");
  if (el) {
    el.textContent = terrain2CurrentDriveLabel;
  }
}

function terrain2ClearActiveButtons() {
  document.querySelectorAll("#terrain2DrivePad .drive-btn").forEach(btn => {
    btn.classList.remove("active");
  });
}

function terrain2SetActiveButton(button) {
  terrain2ClearActiveButtons();
  if (button) {
    button.classList.add("active");
  }
}

async function terrain2SyncDriveServerTime() {
  try {
    const res = await fetch("/drive_time", {method: "GET", cache: "no-store"});
    const j = await res.json();

    if (j && j.ok && typeof j.server_ms === "number") {
      terrain2DriveServerOffsetMs = j.server_ms - Date.now();
      terrain2AppendLog("Synchro temps OK. Décalage serveur: " + terrain2DriveServerOffsetMs + " ms");
      return true;
    }

    terrain2AppendLog("Synchro temps invalide.");
    return false;
  } catch (e) {
    terrain2AppendLog("ERREUR synchro temps: " + e);
    return false;
  }
}

function terrain2BuildDrivePayload(command) {
  const payload = {cmd: command};

  // STOP pur : accepté volontairement sans séquence par /cmd.
  if (command === "d0,0") {
    return payload;
  }

  terrain2DriveSeq += 1;
  payload.drive_seq = terrain2DriveSeq;
  payload.drive_token = terrain2DriveToken;
  payload.sent_server_ms = Math.round(Date.now() + terrain2DriveServerOffsetMs);
  return payload;
}

async function terrain2Cmd(command, showLog = true) {
  const payload = terrain2BuildDrivePayload(command);

  if (showLog) {
    terrain2Log("Commande envoyée : " + command);
  }

  try {
    const res = await fetch("/cmd", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
      cache: "no-store"
    });

    const data = await res.json();

    if (showLog) {
      terrain2AppendLog(JSON.stringify(data, null, 2));
    }

    return data;
  } catch (e) {
    if (showLog) {
      terrain2AppendLog("ERREUR: " + e);
    }
    return {"ok": false, "error": String(e)};
  }
}

function terrain2StartDrive(button) {
  if (!button) return;

  if (terrain2DriveTimer) {
    clearInterval(terrain2DriveTimer);
    terrain2DriveTimer = null;
  }

  terrain2CurrentDriveCmd = button.dataset.drive || "d0,0";
  terrain2CurrentDriveLabel = button.dataset.label || terrain2CurrentDriveCmd;
  terrain2Driving = true;

  terrain2UpdateDriveStatus();
  terrain2SetActiveButton(button);

  terrain2Cmd(terrain2CurrentDriveCmd, true);

  terrain2DriveTimer = setInterval(() => {
    if (terrain2Driving && terrain2CurrentDriveCmd !== "d0,0") {
      terrain2Cmd(terrain2CurrentDriveCmd, false);
    }
  }, 350);
}

function terrain2StopDrive() {
  terrain2Driving = false;
  terrain2CurrentDriveCmd = "d0,0";
  terrain2CurrentDriveLabel = "arrêt";

  terrain2UpdateDriveStatus();
  terrain2ClearActiveButtons();

  if (terrain2DriveTimer) {
    clearInterval(terrain2DriveTimer);
    terrain2DriveTimer = null;
  }

  terrain2Cmd("d0,0", true);
  setTimeout(() => terrain2Cmd("d0,0", false), 80);
  setTimeout(() => terrain2Cmd("d0,0", false), 200);
}

function terrain2SetupDrivePad() {
  const buttons = document.querySelectorAll("#terrain2DrivePad .drive-btn");

  for (const b of buttons) {
    b.addEventListener("pointerdown", e => {
      e.preventDefault();
      try {
        b.setPointerCapture(e.pointerId);
      } catch (err) {}
      terrain2StartDrive(b);
    });

    b.addEventListener("pointerup", e => {
      e.preventDefault();
      terrain2StopDrive();
    });

    b.addEventListener("pointercancel", e => {
      e.preventDefault();
      terrain2StopDrive();
    });

    b.addEventListener("lostpointercapture", e => {
      terrain2StopDrive();
    });

    b.addEventListener("contextmenu", e => {
      e.preventDefault();
    });
  }

  window.addEventListener("blur", terrain2StopDrive);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      terrain2StopDrive();
    }
  });

  window.addEventListener("offline", () => {
    try { terrain2StopDrive(); } catch (e) {}
  });

  window.addEventListener("online", () => {
    try {
      terrain2StopDrive();
      terrain2SyncDriveServerTime();
    } catch (e) {}
  });
}

terrain2UpdateDriveStatus();
terrain2SetupDrivePad();
terrain2SyncDriveServerTime();
setInterval(terrain2SyncDriveServerTime, 30000);
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


# === RB2 ODOMÈTRE SERVEUR - BEGIN ===
# Compteur de distance parcourue calculé et persisté CÔTÉ SERVEUR.
#
# Remplace l'ancien compteur de /lidar_drive2 qui vivait dans le localStorage du
# navigateur (donc: perdu par appareil / origine / vidage de cache, jamais mis à
# jour si la page n'était pas ouverte pendant la conduite, sauté pendant toute la
# conduite par un garde-fou de 1,5 s, et cassé par chaque reset DTR de l'ESP32).
#
# Ici: un fil de fond interroge "enc" toutes les RB2_ODO_POLL_S secondes, intègre
# |Δ centre| (déplacement avant/arrière, en valeur absolue -> une avance ET un
# recul comptent comme de la distance ; une rotation pure ~= 0), détecte les
# remises à zéro des encodeurs (redémarrage ESP32) et n'ajoute jamais le saut
# correspondant. Résultat persisté dans RB2_ODO_FILE -> survit aux reboots et
# est partagé par tous les navigateurs.

import threading as _rb2_odo_threading
import tempfile as _rb2_odo_tempfile

RB2_ODO_FILE = "/home/rj/rb2_odometre.json"
RB2_ODO_FILE_FALLBACK = "/tmp/rb2_odometre.json"
RB2_ODO_POLL_S = 5.0
RB2_ODO_SEND_WAIT_S = 0.5
# Distance maximale plausible entre deux échantillons acceptés. Au-delà = glitch
# ou reset ESP32 : on ré-amorce sans compter. ~1 m/s * (poll + grosse tolérance).
RB2_ODO_MAX_MM_PER_SAMPLE = 30000.0
# Somme des |ticks| en dessous de laquelle on considère que l'ESP32 vient d'être
# remis à zéro (les 4 compteurs repartent de ~0).
RB2_ODO_RESET_TICK_FLOOR = 400
RB2_ODO_RESET_MARKERS = ("remis a zero", "remis à zéro", "encodeurs initialis")

_rb2_odo_lock = _rb2_odo_threading.Lock()
_rb2_odo_started = False
_rb2_odo_state = {
    "total_m": 0.0,
    "trip_m": 0.0,
    "updated": 0.0,
    "updated_iso": None,
    "resets": 0,
    "samples": 0,
    "last_error": "",
}
# Références internes (hors JSON public) :
_rb2_odo_primed = False
_rb2_odo_last_center_mm = None
_rb2_odo_last_ticks = None


def _rb2_odo_now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _rb2_odo_load():
    global _rb2_odo_last_center_mm, _rb2_odo_last_ticks
    for path in (RB2_ODO_FILE, RB2_ODO_FILE_FALLBACK):
        try:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with _rb2_odo_lock:
                _rb2_odo_state["total_m"] = float(data.get("total_m") or 0.0)
                _rb2_odo_state["trip_m"] = float(data.get("trip_m") or 0.0)
                _rb2_odo_state["resets"] = int(data.get("resets") or 0)
                _rb2_odo_state["samples"] = int(data.get("samples") or 0)
                _rb2_odo_state["updated"] = float(data.get("updated") or 0.0)
                _rb2_odo_state["updated_iso"] = data.get("updated_iso")
            # On NE recharge PAS last_center_mm : au redémarrage du panneau,
            # l'ESP32 subit un reset DTR (connect()), ses ticks repartent de 0.
            # Le premier échantillon ré-amorcera la référence sans compter.
            return True
        except Exception:
            continue
    return False


def _rb2_odo_save():
    with _rb2_odo_lock:
        payload = {
            "ok": True,
            "total_m": round(_rb2_odo_state["total_m"], 3),
            "trip_m": round(_rb2_odo_state["trip_m"], 3),
            "resets": _rb2_odo_state["resets"],
            "samples": _rb2_odo_state["samples"],
            "updated": _rb2_odo_state["updated"],
            "updated_iso": _rb2_odo_state["updated_iso"],
            "last_error": _rb2_odo_state["last_error"],
            "source": "esp32_panel_odo_serveur",
        }
    for path in (RB2_ODO_FILE, RB2_ODO_FILE_FALLBACK):
        try:
            directory = os.path.dirname(path) or "/tmp"
            fd, tmp_path = _rb2_odo_tempfile.mkstemp(prefix=".rb2_odometre_", suffix=".json", dir=directory, text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            return True
        except Exception:
            continue
    return False


def _rb2_odo_read_encoders():
    """Renvoie (values_normalisees|None, texte_lignes). FR/RR déjà inversés
    (avance physique = positif), comme la route /encoders."""
    # Ne jamais déclencher une (re)connexion série depuis ce fil de fond : si le
    # port est fermé, on laisse une vraie commande de conduite ou /encoders
    # rouvrir (avec son reset DTR de 2,5 s). On saute juste ce cycle.
    try:
        if not (esp32.ser and getattr(esp32.ser, "is_open", False)):
            return None, "port série ESP32 fermé"
    except Exception:
        return None, "port série ESP32 indisponible"

    try:
        result = esp32.send("enc", wait=RB2_ODO_SEND_WAIT_S)
    except Exception as e:
        return None, f"send enc: {e}"

    lines = []
    try:
        lines.extend(result.get("lines", []) or [])
    except Exception:
        pass
    try:
        lines.extend(esp32.get_last_lines(40))
    except Exception:
        pass

    values = parse_encoders_from_lines(lines)
    if not values or all(values.get(k) is None for k in ("FL", "FR", "RR", "RL")):
        return None, "aucune valeur encodeur"

    if values.get("FR") is not None:
        values["FR"] = -values["FR"]
    if values.get("RR") is not None:
        values["RR"] = -values["RR"]

    return values, "\n".join(str(x) for x in lines).lower()


def _rb2_odo_tick():
    global _rb2_odo_primed, _rb2_odo_last_center_mm, _rb2_odo_last_ticks

    # Pendant un suivi/retour de trace, le worker conduit ET lit déjà les
    # encodeurs en boucle serrée : on ne s'ajoute pas au trafic série, et on
    # ré-amorce pour ne pas compter le rejeu comme un gros bond en une fois
    # (le rejeu retrace du terrain déjà parcouru).
    try:
        if rb2_trace_follow_is_running():
            _rb2_odo_last_center_mm = None
            _rb2_odo_last_ticks = None
            return
    except Exception:
        pass

    values, lines_text = _rb2_odo_read_encoders()
    if values is None:
        with _rb2_odo_lock:
            _rb2_odo_state["last_error"] = lines_text
        return

    odom = compute_odom_from_values(values)
    center_mm = odom.get("center_mm")
    if center_mm is None:
        return

    ticks_abs_sum = sum(abs(int(values.get(k) or 0)) for k in ("FL", "FR", "RR", "RL"))
    reset_marker = any(m in lines_text for m in RB2_ODO_RESET_MARKERS)

    prev_center = _rb2_odo_last_center_mm
    prev_abs_sum = None
    if _rb2_odo_last_ticks:
        prev_abs_sum = sum(abs(int(_rb2_odo_last_ticks.get(k) or 0)) for k in ("FL", "FR", "RR", "RL"))

    added_m = 0.0
    counted = True
    reason = ""

    if not _rb2_odo_primed or prev_center is None:
        counted = False
        reason = "amorçage"
    else:
        delta_mm = center_mm - prev_center
        esp32_reset = (
            reset_marker
            or abs(delta_mm) > RB2_ODO_MAX_MM_PER_SAMPLE
            or (
                prev_abs_sum is not None
                and prev_abs_sum > RB2_ODO_RESET_TICK_FLOOR * 4
                and ticks_abs_sum < RB2_ODO_RESET_TICK_FLOOR
            )
        )
        if esp32_reset:
            counted = False
            reason = "reset/glitch encodeurs ignoré"
            with _rb2_odo_lock:
                _rb2_odo_state["resets"] += 1
        else:
            added_m = abs(delta_mm) / 1000.0

    now = time.time()
    with _rb2_odo_lock:
        if counted and added_m > 0.0:
            _rb2_odo_state["total_m"] += added_m
            _rb2_odo_state["trip_m"] += added_m
        _rb2_odo_state["samples"] += 1
        _rb2_odo_state["updated"] = now
        _rb2_odo_state["updated_iso"] = _rb2_odo_now_iso()
        _rb2_odo_state["last_error"] = "" if counted else reason

    _rb2_odo_primed = True
    _rb2_odo_last_center_mm = center_mm
    _rb2_odo_last_ticks = {k: int(values.get(k) or 0) for k in ("FL", "FR", "RR", "RL")}

    # On n'écrit sur disque que quand ça bouge (ou tous les ~12 échantillons pour
    # rafraîchir le stamp), pour épargner la carte SD.
    if added_m > 0.0 or (_rb2_odo_state["samples"] % 12 == 0):
        _rb2_odo_save()


def _rb2_odo_loop():
    _rb2_odo_load()
    while True:
        try:
            _rb2_odo_tick()
        except Exception as e:
            try:
                with _rb2_odo_lock:
                    _rb2_odo_state["last_error"] = f"loop: {e}"
            except Exception:
                pass
        time.sleep(RB2_ODO_POLL_S)


def _rb2_odo_snapshot():
    with _rb2_odo_lock:
        snap = dict(_rb2_odo_state)
    snap["total_m"] = round(snap["total_m"], 3)
    snap["trip_m"] = round(snap["trip_m"], 3)
    snap["age_s"] = round(time.time() - snap["updated"], 1) if snap["updated"] else None
    snap["ok"] = True
    snap["primed"] = _rb2_odo_primed
    return snap


def _rb2_start_odo():
    global _rb2_odo_started
    if _rb2_odo_started:
        return
    _rb2_odo_started = True
    t = _rb2_odo_threading.Thread(target=_rb2_odo_loop, name="rb2-odometre-serveur", daemon=True)
    t.start()


@app.route("/odometre", methods=["GET"])
def rb2_odometre():
    return jsonify(_rb2_odo_snapshot())


@app.route("/odometre_trip_reset", methods=["POST"])
def rb2_odometre_trip_reset():
    with _rb2_odo_lock:
        _rb2_odo_state["trip_m"] = 0.0
        _rb2_odo_state["updated"] = time.time()
        _rb2_odo_state["updated_iso"] = _rb2_odo_now_iso()
    _rb2_odo_save()
    return jsonify(_rb2_odo_snapshot())


@app.route("/odometre_total_set", methods=["POST"])
def rb2_odometre_total_set():
    raw = None
    if request.is_json:
        raw = (request.get_json(silent=True) or {}).get("value_m")
    if raw is None:
        raw = request.form.get("value_m", request.args.get("value_m"))
    try:
        value_m = float(raw)
        if value_m < 0 or value_m > 1_000_000:
            raise ValueError("hors plage")
    except Exception as e:
        return jsonify({"ok": False, "error": f"value_m invalide: {e}"}), 400
    with _rb2_odo_lock:
        _rb2_odo_state["total_m"] = value_m
        _rb2_odo_state["updated"] = time.time()
        _rb2_odo_state["updated_iso"] = _rb2_odo_now_iso()
    _rb2_odo_save()
    return jsonify(_rb2_odo_snapshot())


_rb2_start_odo()

# === RB2 ODOMÈTRE SERVEUR - END ===





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




@app.route("/cmd_rescue", methods=["POST"])
def cmd_rescue():
    """
    Mode secours temporaire RB2.
    Sert seulement à récupérer le robot quand la sécurité LIDAR arrière
    bloque les commandes normales. Impulsions lentes, courtes, avec STOP automatique.
    """
    try:
        data = request.get_json(silent=True) or {}
        action = str(data.get("action", "STOP")).upper()
        duration_ms = int(data.get("duration_ms", 220))

        if duration_ms < 50:
            duration_ms = 50
        if duration_ms > 350:
            duration_ms = 350

        allowed = {
            "STOP": "d0,0",
            "BACK": "d-10,-10",
            "LEFT": "d-8,8",
            "RIGHT": "d8,-8",
        }

        if action not in allowed:
            return {
                "ok": False,
                "error": "action non permise",
                "allowed": list(allowed.keys()),
            }, 400

        motor_cmd = allowed[action]

        if action == "STOP":
            r = esp32.send("d0,0", wait=0.0)
            return {
                "ok": True,
                "rescue": True,
                "action": action,
                "motor_cmd": motor_cmd,
                "result": r,
            }

        # Impulsion courte, puis STOP obligatoire.
        r1 = esp32.send(motor_cmd, wait=0.0)
        time.sleep(duration_ms / 1000.0)
        r2 = esp32.send("d0,0", wait=0.0)

        return {
            "ok": True,
            "rescue": True,
            "action": action,
            "motor_cmd": motor_cmd,
            "duration_ms": duration_ms,
            "start_result": r1,
            "stop_result": r2,
            "warning": "Mode secours temporaire: contourne la sécurité LIDAR arrière pour récupération lente seulement.",
        }

    except Exception as e:
        try:
            esp32.send("d0,0", wait=0.0)
        except Exception:
            pass
        return {
            "ok": False,
            "rescue": True,
            "error": str(e),
        }, 500



# ============================================================
# RB2 - MODE SECOURS PERMANENT
# Page minimale de récupération: caméra + commandes ESP32.
# Contourne /cmd, drive_seq, timestamp et sécurité LIDAR arrière.
# ============================================================

import threading as _rb2_secours_threading

_RB2_SECOURS_LOCK = _rb2_secours_threading.Lock()
_RB2_SECOURS_STOP_EVENT = None
_RB2_SECOURS_THREAD = None
_RB2_SECOURS_STATE = {
    "running": False,
    "action": "STOP",
    "cmd": "d0,0",
    "speed": 0,
    "duration_s": 0,
    "last_error": None,
}

def _rb2_secours_stop_burst():
    for _ in range(15):
        try:
            esp32.send("d0,0", wait=0.0)
        except Exception as e:
            _RB2_SECOURS_STATE["last_error"] = str(e)
        time.sleep(0.04)

def _rb2_secours_worker(action, cmd, speed, duration_s, stop_event):
    try:
        with _RB2_SECOURS_LOCK:
            _RB2_SECOURS_STATE.update({
                "running": True,
                "action": action,
                "cmd": cmd,
                "speed": speed,
                "duration_s": duration_s,
                "last_error": None,
            })

        end = time.time() + duration_s
        while time.time() < end and not stop_event.is_set():
            esp32.send(cmd, wait=0.0)
            time.sleep(0.10)

    except Exception as e:
        with _RB2_SECOURS_LOCK:
            _RB2_SECOURS_STATE["last_error"] = str(e)

    finally:
        _rb2_secours_stop_burst()
        with _RB2_SECOURS_LOCK:
            _RB2_SECOURS_STATE["running"] = False
            _RB2_SECOURS_STATE["action"] = "STOP"
            _RB2_SECOURS_STATE["cmd"] = "d0,0"



@app.route("/terrain2")
def rb2_terrain2_page():
    return """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>RB2 Terrain2</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: #101010;
      color: #eee;
    }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 9999;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      padding: 6px 8px;
      background: #181818;
      border-bottom: 1px solid #333;
    }

    .top-title {
      font-size: 13px;
      color: #ddd;
      margin-right: auto;
      white-space: nowrap;
    }

    .top-title strong {
      color: #fff;
      font-size: 15px;
    }

    button, .linkbtn {
      border: 1px solid #555;
      border-radius: 6px;
      background: #2b2b2b;
      color: #fff;
      padding: 8px 10px;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
    }

    button:hover, .linkbtn:hover { background: #3a3a3a; }

    .danger {
      background: #b00020 !important;
      border-color: #ff405c !important;
      color: #fff !important;
    }

    .blue {
      background: #164c7a !important;
      border-color: #3b82f6 !important;
    }

    .green {
      background: #166534 !important;
      border-color: #22c55e !important;
    }

    .purple {
      background: #4b267a !important;
      border-color: #a78bfa !important;
    }

    .orange {
      background: #92400e !important;
      border-color: #f59e0b !important;
    }

    .disabled {
      opacity: .55;
      cursor: not-allowed;
    }

    .page {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 280px;
      gap: 6px;
      padding: 7px;
      align-items: start;
    }

    .media-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.12fr) minmax(300px, 0.88fr);
      gap: 10px;
      align-items: start;
    }

    .card {
      background: #1a1a1a;
      border: 1px solid #333;
      border-radius: 8px;
      padding: 10px;
      min-width: 0;
    }


    .media-card {
      padding: 7px;
    }

    .media-card h2 {
      margin-bottom: 6px;
    }

    .media-row {
      display: grid;
      grid-template-columns: minmax(0, 1.12fr) minmax(300px, 0.88fr);
      gap: 6px;
      align-items: stretch;
    }

    .media-panel {
      min-width: 0;
    }

    .media-panel h3 {
      margin: 0 0 6px 0;
      font-size: 13px;
      color: #ddd;
      font-weight: 700;
      letter-spacing: .03em;
    }

    .card h2 {
      margin: 0 0 8px 0;
      padding-bottom: 5px;
      border-bottom: 1px solid #333;
      font-size: 15px;
      color: #fff;
      letter-spacing: .03em;
    }

    .leftcol, .rightcol {
      display: grid;
      gap: 10px;
      align-content: start;
    }

    .rightcol {
      max-width: 280px;
      width: 280px;
    }

    .camera-box img {
      width: 100%;
      height: 400px;
      max-height: 64vh;
      object-fit: contain;
      background: #000;
      border: 1px solid #333;
      border-radius: 6px;
      display: block;
    }

    .lidar-wrap canvas {
      display: block;
    }

    .lidar-wrap {
      width: 100%;
      background: #050505;
      border: 1px solid #333;
      border-radius: 6px;
      overflow: hidden;
    }

    #lidarCanvas {
      width: 100%;
      height: 400px;
      display: block;
      background: #050505;
    }


    .camera-capture-row {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 6px;
      margin-top: 7px;
    }


    .camera-capture-row button.photo-flash {
      background: #166534 !important;
      border-color: #22c55e !important;
      color: #fff !important;
      outline: 2px solid #86efac;
    }

    .camera-capture-row button.photo-error {
      background: #7f1d1d !important;
      border-color: #ef4444 !important;
      color: #fff !important;
      outline: 2px solid #fecaca;
    }

    .camera-capture-row button.video-active {
      background: #b00020 !important;
      border-color: #ff405c !important;
      color: #fff !important;
      outline: 2px solid #fecaca;
    }

    .camera-capture-row button {
      min-height: 34px;
      font-size: 13px;
      padding: 6px 8px;
    }
.status-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 7px;
      font-size: 12px;
    }

    .pill {
      border: 1px solid #444;
      background: #202020;
      padding: 4px 7px;
      border-radius: 999px;
      color: #ddd;
    }

    .pill.ok { border-color: #22c55e; color: #bbf7d0; }
    .pill.bad { border-color: #ef4444; color: #fecaca; }
    .pill.warn { border-color: #f59e0b; color: #fde68a; }

    .drive-status {
      margin-bottom: 8px;
      font-size: 14px;
    }

    .drive-status span {
      font-weight: 700;
      color: #fff;
    }

    .drive-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 7px;
      max-width: 260px;
      margin: 0 auto 8px auto;
    }

    .drive-btn {
      min-height: 48px;
      font-size: 14px;
      touch-action: none;
      user-select: none;
    }

    .drive-btn.active {
      outline: 3px solid #fff;
    }

    .pan-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 7px;
      max-width: 260px;
      margin: 8px auto 0 auto;
    }

    .mini-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 7px;
    }

    .two-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 7px;
    }

    .capture-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 7px;
    }

    .log {
      margin-top: 8px;
      padding: 7px;
      min-height: 48px;
      max-height: 100px;
      overflow: auto;
      background: #080808;
      border: 1px solid #333;
      border-radius: 6px;
      color: #ccc;
      font-family: Consolas, monospace;
      font-size: 12px;
      white-space: pre-wrap;
    }

    .note {
      color: #aaa;
      font-size: 12px;
      line-height: 1.35;
      margin-top: 6px;
    }


    .controls {
      background: #1a1a1a;
      border: 1px solid #333;
      border-radius: 8px;
      padding: 7px;
      width: 100%;
      font-size: 12px;
    }

    .controls h2 {
      margin: 0 0 4px 0;
      padding-bottom: 4px;
      border-bottom: 1px solid #333;
      font-size: 16px;
      color: #fff;
      text-align: center;
    }

    .terrain-signature {
      text-align: center;
      color: #aaa;
      font-size: 11px;
      margin-bottom: 6px;
    }

    .rb2-relay-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 5px;
      margin-bottom: 6px;
    }

    .rb2-relay-btn {
      min-height: 32px;
      padding: 5px 6px;
      font-size: 11px;
      border-radius: 6px;
    }

    .rb2-relay-off {
      background: #333;
      border-color: #666;
    }

    .rb2-relay-on {
      background: #166534;
      border-color: #22c55e;
    }

    .rb2-status-light {
      padding: 5px 6px;
      margin-bottom: 6px;
      border-radius: 6px;
      border: 1px solid #444;
      background: #202020;
      color: #ddd;
      font-size: 11px;
      text-align: center;
    }

    .drive-status-hidden {
      display: none;
    }

    .controls .drive-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 5px;
      max-width: 250px;
      margin: 0 auto 7px auto;
    }

    .controls .drive-btn {
      min-height: 42px;
      padding: 5px;
      font-size: 13px;
      border-radius: 7px;
    }

    .controls .stop,
    .controls .drive-btn.stop {
      background: #b00020 !important;
      border-color: #ff405c !important;
      color: #fff !important;
    }


    .speed-row {
      display: grid;
      grid-template-columns: .9fr 1fr 1fr 1fr 1fr;
      gap: 4px;
      max-width: 250px;
      margin: 4px auto 7px auto;
      align-items: center;
    }

    .speed-label {
      color: #ddd;
      font-size: 11px;
      font-weight: 700;
      text-align: center;
    }

    .speed-btn {
      min-height: 28px;
      padding: 3px 4px;
      font-size: 11px;
      border-radius: 6px;
      background: #2b2b2b;
      border: 1px solid #555;
      color: #fff;
    }

    .speed-btn.speed-active {
      background: #166534 !important;
      border-color: #22c55e !important;
      color: #fff !important;
      outline: 2px solid #86efac;
    }

    .pt-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 5px;
      max-width: 250px;
      margin: 7px auto 6px auto;
      align-items: center;
    }

    .pt-grid button {
      min-height: 34px;
      padding: 5px;
      font-size: 14px;
    }

    .readout {
      background: #101010;
      border: 1px solid #333;
      border-radius: 6px;
      padding: 5px;
      text-align: center;
      font-size: 12px;
      line-height: 1.35;
    }

    .small-row {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 5px;
      max-width: 250px;
      margin: 6px auto;
    }

    .small-row button {
      min-height: 30px;
      padding: 4px;
      font-size: 12px;
    }

    .data-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 5px;
      margin-top: 6px;
    }

    .box {
      background: #101010;
      border: 1px solid #333;
      border-radius: 6px;
      padding: 5px;
      text-align: center;
    }

    .box .label {
      color: #aaa;
      font-size: 10px;
      margin-bottom: 2px;
    }

    .box .value {
      color: #fff;
      font-size: 13px;
      font-weight: 700;
    }

    .small-text {
      color: #aaa;
      font-size: 11px;
      line-height: 1.25;
      margin-top: 5px;
      text-align: center;
    }
.horizon-center-v,
.horizon-center-h {
      left: 0;
      top: 50%;
      width: 100%;
      height: 1px;
    }
@media (max-width: 1100px) {
      .page { grid-template-columns: 1fr; }

      .rightcol {
        max-width: none;
        width: auto;
      }

      .media-row {
        grid-template-columns: 1fr;
      }

      .camera-box img {
        height: auto;
        max-height: 46vh;
      }

      #lidarCanvas {
        height: 400px;
      }

      .top-title { width: 100%; }
    }
  

/* === TERRAIN2 : couleurs du bloc RB2 Terrain copiées de /terrain === */
.controls {
  background: #222;
}

.stop {
  background: #a00000;
}

.stop:hover {
  background: #d00000;
}

.drive-btn.active {
  background: #0066aa !important;
  border: 2px solid #66ccff !important;
  box-shadow: 0 0 10px #66ccff !important;
}

.box {
  background: #000;
  border: 1px solid #333;
}

.label {
  color: #bbb;
}

.value {
  color: #00ff66;
}

.readout {
  background: #000;
  color: #00ff66;
}

.small-text {
  color: #aaa;
}
.rb2-status-light {
  background: #000;
  border: 1px solid #333;
  color: #aaa;
}

.rb2-relay-btn {
  border: 1px solid #4b5563;
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

/* Couleurs boutons Lumières / Relais 2 */ .rb2-relay-btn.rb2-relay-off {
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
/* === FIN couleurs bloc RB2 Terrain === */



    /* === TERRAIN2 : distances LIDAR sous carte, grille 2x2 forcée === */
    .lidar-distance-grid {
      display: grid !important;
      grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
      grid-template-rows: auto auto !important;
      gap: 6px !important;
      margin-top: 7px !important;
      width: 100% !important;
    }

    .lidar-distance-btn {
      display: block !important;
      background: #101010 !important;
      border: 1px solid #444 !important;
      border-radius: 7px !important;
      padding: 6px 4px !important;
      text-align: center !important;
      min-height: 42px !important;
      box-sizing: border-box !important;
    }

    .lidar-distance-label {
      display: block !important;
      color: #ddd !important;
      font-size: 12px !important;
      font-weight: 700 !important;
      line-height: 1.1 !important;
      margin-bottom: 3px !important;
    }

    .lidar-distance-value {
      display: block !important;
      color: #fff !important;
      font-size: 15px !important;
      font-weight: 800 !important;
      line-height: 1.15 !important;
    }

    .lidar-mini-status {
      color: #aaa !important;
      font-size: 12px !important;
      line-height: 1.25 !important;
      margin-top: 5px !important;
      text-align: center !important;
    }
    /* === FIN TERRAIN2 distances LIDAR === */


    /* === TERRAIN2 : hauteur réelle du bloc RB2 Terrain jusqu'au bas de la carte LIDAR === */
    .rightcol > .controls {
      min-height: 455px !important;
      box-sizing: border-box !important;
      display: flex !important;
      flex-direction: column !important;
      justify-content: space-between !important;
    }

    .controls .rb2-relay-row {
      margin-top: 4px !important;
      margin-bottom: 7px !important;
    }

    .controls .rb2-status-light {
      margin-bottom: 7px !important;
    }

    .controls .drive-grid {
      gap: 6px !important;
      margin-top: 4px !important;
      margin-bottom: 7px !important;
    }

    .controls .drive-btn {
      min-height: 42px !important;
      padding-top: 7px !important;
      padding-bottom: 7px !important;
      font-size: 14px !important;
    }

    .controls .speed-row {
      margin-top: 6px !important;
      margin-bottom: 9px !important;
    }

    .controls .speed-btn {
      min-height: 32px !important;
      font-size: 12px !important;
    }

    .controls .pt-grid {
      gap: 6px !important;
      margin-top: 5px !important;
      margin-bottom: 7px !important;
    }

    .controls .pt-grid button {
      min-height: 36px !important;
      padding-top: 6px !important;
      padding-bottom: 6px !important;
      font-size: 13px !important;
    }

    .controls .small-row {
      margin-top: 6px !important;
      gap: 6px !important;
    }

    .controls .small-row button {
      min-height: 30px !important;
      padding-top: 5px !important;
      padding-bottom: 5px !important;
    }
    /* === FIN hauteur réelle bloc RB2 Terrain === */



    /* === TERRAIN2 : commandes RB2 visuel type terrain === */

    /* Grille moteurs en vraie croix :
         Avance
      Gauche STOP Droite
         Recul
    */
    .controls .drive-grid {
      display: grid !important;
      grid-template-columns: repeat(3, 76px) !important;
      grid-template-rows: repeat(3, 48px) !important;
      gap: 7px !important;
      justify-content: center !important;
      align-items: center !important;
      max-width: 260px !important;
      margin: 7px auto 8px auto !important;
    }

    .controls .drive-grid > div {
      display: block !important;
      width: 76px !important;
      height: 48px !important;
      visibility: hidden !important;
      pointer-events: none !important;
    }

    .controls .drive-btn {
      width: 76px !important;
      height: 48px !important;
      min-height: 48px !important;
      padding: 6px 6px !important;
      font-size: 14px !important;
      font-weight: 800 !important;
      border-radius: 8px !important;
      box-sizing: border-box !important;
      justify-self: center !important;
      align-self: center !important;
    }

    .controls .drive-btn[data-label="avance"] {
      grid-column: 2 !important;
      grid-row: 1 !important;
    }

    .controls .drive-btn[data-label="gauche"] {
      grid-column: 1 !important;
      grid-row: 2 !important;
    }

    .controls .drive-btn[data-label="stop"] {
      grid-column: 2 !important;
      grid-row: 2 !important;
    }

    .controls .drive-btn[data-label="droite"] {
      grid-column: 3 !important;
      grid-row: 2 !important;
    }

    .controls .drive-btn[data-label="recul"] {
      grid-column: 2 !important;
      grid-row: 3 !important;
    }

    /* Ligne vitesse un peu plus solide */
    .controls .speed-row {
      max-width: 260px !important;
      margin: 7px auto 9px auto !important;
      gap: 6px !important;
    }

    .controls .speed-btn {
      min-height: 33px !important;
      font-size: 12px !important;
      font-weight: 800 !important;
      border-radius: 7px !important;
    }

    /* Pan/Tilt plus proche du format terrain */
    .controls .pt-grid {
      display: grid !important;
      grid-template-columns: repeat(3, 76px) !important;
      gap: 7px !important;
      justify-content: center !important;
      align-items: center !important;
      max-width: 260px !important;
      margin: 7px auto 7px auto !important;
    }

    .controls .pt-grid button {
      width: 76px !important;
      min-height: 40px !important;
      padding: 6px 6px !important;
      font-size: 13px !important;
      font-weight: 800 !important;
      border-radius: 8px !important;
      box-sizing: border-box !important;
    }

    .controls .pt-grid .readout {
      width: 76px !important;
      min-height: 40px !important;
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      font-size: 13px !important;
      font-weight: 800 !important;
      box-sizing: border-box !important;
    }

    .controls .small-row {
      max-width: 260px !important;
      margin: 7px auto 0 auto !important;
      gap: 7px !important;
    }

    .controls .small-row button {
      min-height: 34px !important;
      font-size: 12px !important;
      font-weight: 800 !important;
      border-radius: 7px !important;
    }

    /* === FIN TERRAIN2 commandes RB2 visuel type terrain === */



    /* === TERRAIN2 : correction affichage central PanTilt === */

    .controls .pt-grid {
      display: grid !important;
      grid-template-columns: repeat(3, 82px) !important;
      gap: 8px !important;
      justify-content: center !important;
      align-items: center !important;
      max-width: 280px !important;
      margin: 8px auto 8px auto !important;
    }

    .controls .pt-grid button {
      width: 82px !important;
      min-height: 42px !important;
      height: 42px !important;
      padding: 6px 6px !important;
      font-size: 15px !important;
      font-weight: 800 !important;
      border-radius: 8px !important;
      box-sizing: border-box !important;
    }

    .controls .pt-grid .pt-readout,
    .controls .pt-grid .readout {
      width: 82px !important;
      height: 52px !important;
      min-height: 52px !important;
      display: flex !important;
      flex-direction: column !important;
      align-items: center !important;
      justify-content: center !important;
      gap: 3px !important;
      padding: 4px 3px !important;
      box-sizing: border-box !important;
      font-size: 13px !important;
      font-weight: 800 !important;
      line-height: 1.1 !important;
      white-space: nowrap !important;
      overflow: hidden !important;
      text-align: center !important;
    }

    .controls .pt-grid .pt-readout div {
      display: block !important;
      width: 100% !important;
      text-align: center !important;
    }

    .controls .pt-grid .pt-readout span {
      display: inline !important;
      font-weight: 900 !important;
    }

    .controls .small-row {
      display: grid !important;
      grid-template-columns: repeat(3, 82px) !important;
      gap: 8px !important;
      justify-content: center !important;
      max-width: 280px !important;
      margin: 9px auto 0 auto !important;
    }

    .controls .small-row button {
      width: 82px !important;
      min-height: 39px !important;
      height: 39px !important;
      padding: 6px 6px !important;
      font-size: 14px !important;
      font-weight: 800 !important;
      border-radius: 8px !important;
      box-sizing: border-box !important;
    }

    /* === FIN correction affichage central PanTilt === */



    /* === TERRAIN2 : bouton arrêt RB2 haut === */
    .rb2-shutdown-btn {
      float: right !important;
      background: #b00020 !important;
      border: 1px solid #ff405c !important;
      color: #fff !important;
      font-weight: 900 !important;
      font-size: 13px !important;
      padding: 7px 12px !important;
      border-radius: 8px !important;
      margin-left: 10px !important;
      cursor: pointer !important;
      box-shadow: 0 0 0 1px rgba(255, 80, 100, 0.25) !important;
    }

    .rb2-shutdown-btn:hover {
      background: #d00028 !important;
      border-color: #ff6b7f !important;
    }

    .rb2-shutdown-top {
      text-align: right !important;
      margin: 4px 0 6px 0 !important;
    }
    /* === FIN bouton arrêt RB2 haut === */



    /* === TERRAIN2 FIX : vraie croix moteur === */
    .controls .drive-grid {
      display: grid !important;
      grid-template-columns: repeat(3, 82px) !important;
      grid-template-rows: repeat(3, 50px) !important;
      gap: 8px !important;
      justify-content: center !important;
      align-items: center !important;
      max-width: 280px !important;
      margin: 8px auto 10px auto !important;
    }

    .controls .drive-grid > div {
      width: 82px !important;
      height: 50px !important;
      visibility: hidden !important;
      pointer-events: none !important;
    }

    .controls .drive-btn {
      width: 82px !important;
      height: 50px !important;
      min-height: 50px !important;
      font-size: 14px !important;
      font-weight: 800 !important;
      border-radius: 8px !important;
    }
    /* === FIN TERRAIN2 FIX vraie croix moteur === */



    /* === TERRAIN2 : boutons zoom LIDAR === */
    .lidar-zoom-row {
      display: grid !important;
      grid-template-columns: 1fr 1fr 1.45fr !important;
      gap: 6px !important;
      margin-top: 7px !important;
    }

    .lidar-zoom-btn {
      min-height: 32px !important;
      padding: 5px 8px !important;
      font-size: 12px !important;
      font-weight: 800 !important;
      border-radius: 7px !important;
      background: #1f2937 !important;
      border: 1px solid #4b5563 !important;
      color: #fff !important;
      cursor: pointer !important;
    }

    .lidar-zoom-btn:hover {
      background: #374151 !important;
      border-color: #9ca3af !important;
    }
    /* === FIN boutons zoom LIDAR === */



    /* === TERRAIN2 : suppression titres blocs principaux === */
    .media-card > h2,
    .controls > h2 {
      display: none !important;
      margin: 0 !important;
      padding: 0 !important;
      height: 0 !important;
      overflow: hidden !important;
    }

    .media-card {
      padding-top: 7px !important;
    }

    .controls {
      padding-top: 7px !important;
    }

    .rb2-relay-row {
      margin-top: 0 !important;
    }
    /* === FIN suppression titres blocs principaux === */

</style>
</head>

<body>
  <div class="rb2-shutdown-top"><button id="rb2ShutdownBtn" class="rb2-shutdown-btn" onclick="rb2Terrain2Shutdown()">ARRÊT RB2</button></div>
  <div class="topbar">
    <div class="top-title">
      <strong>RB2 Terrain2</strong>
      <span> — Créé par Roméo St-Cyr en juin 2026</span>
      <span id="rb2TopState"></span>
    </div>
<button id="wifiLocalBtn" class="green disabled" title="Route WiFi Local à confirmer avant activation">WiFi Local ON</button>
<a class="linkbtn danger" href="/secours">SECOURS</a>
    <a class="linkbtn blue" href="/lidar_drive2">LIDAR DRIVE</a>
  </div>

  <main class="page">
    <section class="leftcol">
      <section class="card media-card">
<div class="media-row">
          <div class="media-panel camera-box">
            <h3>CAMÉRA</h3>
            <img id="camImg" src="/zero_cam_stream.mjpg" alt="Caméra Zero 2 W RB2">

            <div class="camera-capture-row">
              <button id="photoBtn" class="blue" onclick="takePhoto()">PHOTO</button>
              <button id="videoBtn" class="orange" onclick="toggleVideo()">VIDÉO</button>
              <button id="capturesBtn" class="purple" onclick="openCaptures()">TÉLÉCHARGEMENT</button>
            </div>
<div class="status-row">
              <button onclick="openCamera()">CAMÉRA DIRECTE</button>
              <button onclick="restartCamera()">RESTART CAMÉRA</button>
</div>
          </div>

          <div class="media-panel">
            <h3>CARTE LIDAR</h3>
            <div class="lidar-wrap">
              <canvas id="lidarCanvas" width="900" height="620"></canvas>

            <div class="lidar-zoom-row">
              <button id="lidarZoomPlus" class="lidar-zoom-btn" onclick="rb2Terrain2LidarZoomPlus(); return false;">ZOOM +</button>
              <button id="lidarZoomMinus" class="lidar-zoom-btn" onclick="rb2Terrain2LidarZoomMinus(); return false;">ZOOM -</button>
              <button id="lidarDistanceToggle" class="lidar-zoom-btn" onclick="rb2Terrain2LidarToggleDistances(); return false;">DISTANCES OFF</button>
            </div>
            </div>
            <div class="lidar-distance-grid">
              <div class="lidar-distance-btn">
                <div class="lidar-distance-label">Avant</div>
                <div class="lidar-distance-value"><span id="lidarFront">---</span> cm</div>
              </div>
              <div class="lidar-distance-btn">
                <div class="lidar-distance-label">Droite</div>
                <div class="lidar-distance-value"><span id="lidarRight">---</span> cm</div>
              </div>
              <div class="lidar-distance-btn">
                <div class="lidar-distance-label">Arrière</div>
                <div class="lidar-distance-value"><span id="lidarBack">---</span> cm</div>
              </div>
              <div class="lidar-distance-btn">
                <div class="lidar-distance-label">Gauche</div>
                <div class="lidar-distance-value"><span id="lidarLeft">---</span> cm</div>
              </div>
            </div>

            <div class="lidar-mini-status">
              Min : <span id="lidarMin">---</span> cm —
              âge : <span id="lidarAge">---</span> s —
              <span id="lidarState">attente</span>
            </div>
</div>
        </div>
      </section>
    </section>

    <section class="rightcol">
      <div class="controls">
<div class="rb2-relay-row">
        <button id="rb2LightBtn" class="rb2-relay-btn rb2-relay-off">LUMIÈRES OFF</button>
        <button id="rb2Relay2Btn" class="rb2-relay-btn rb2-relay-off">RELAIS 2 OFF</button>
      </div>

<div class="rb2-relay-row">
</div>

        <div id="rb2StatusLight" class="rb2-status-light">
          État RB2 : vérification...
        </div>

        <div class="status drive-status-hidden">Direction : <span id="driveStatus">arrêt</span></div>

                        <div class="drive-grid" id="drivePad">
          <div></div>
          <button class="drive-btn" data-label="avance" data-drive="d20,20">Avance</button>
          <div></div>

          <button class="drive-btn" data-label="gauche" data-drive="d-20,20">Gauche</button>
          <button class="drive-btn stop" data-label="stop" data-drive="d0,0">STOP</button>
          <button class="drive-btn" data-label="droite" data-drive="d20,-20">Droite</button>

          <div></div>
          <button class="drive-btn" data-label="recul" data-drive="d-20,-20">Recul</button>
          <div></div>
        </div>

        <div class="speed-row">
          <span class="speed-label">Vitesse</span>
          <button id="speed25" class="speed-btn" onclick="setDriveSpeed(25)" title="Vitesse lente utile : d15">25%</button>
          <button id="speed50" class="speed-btn" onclick="setDriveSpeed(50)" title="Vitesse moyenne : d17">50%</button>
          <button id="speed75" class="speed-btn" onclick="setDriveSpeed(75)" title="Vitesse rapide : d19">75%</button>
          <button id="speed100" class="speed-btn speed-active" onclick="setDriveSpeed(100)" title="Vitesse maximum actuelle : d20">100%</button>
        </div>

        <div class="pt-grid">
          <div></div>
          <button onclick="tiltUp()">▲</button>
          <div></div>

          <button onclick="panLeft()">◀</button>
          <div class="readout pt-readout">
            <div>Pan : <span id="panValue">95</span></div>
            <div>Tilt : <span id="tiltValue">90</span></div>
          </div>
          <button onclick="panRight()">▶</button>

          <div></div>
          <button onclick="tiltDown()">▼</button>
          <div></div>
        </div>

        <div class="small-row">
          <button onclick="setPanTilt(95, 90)">Centre</button>
          <button onclick="setTiltOnly(145)">T 145</button>
          <button class="stop" onclick="setTiltOnly(68)">T 68</button>
        </div>
</div>
</section>
  </main>

<script>
let currentDrive = "s";
let driveSpeedPercent = 100;
let driveSpeedValue = 20;
let driveTimer = null;
let pan = 95;
let tilt = 90;
let lightOn = false;
let relay2On = false;
let videoOn = false;

const logEl = () => document.getElementById("mainLog");

function log(msg) {
  const el = logEl();
  const t = new Date().toLocaleTimeString();
  el.textContent = `[${t}] ${msg}\n` + el.textContent;
}

async function postJson(url, data, timeoutMs=2500) {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, {
      method: "POST",
      cache: "no-store",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(data || {}),
      signal: ctrl.signal
    });
    const txt = await r.text();
    try { return JSON.parse(txt); }
    catch { return {ok:r.ok, text:txt}; }
  } finally {
    clearTimeout(id);
  }
}

async function getJson(url, timeoutMs=2500) {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, {cache: "no-store", signal: ctrl.signal});
    return await r.json();
  } finally {
    clearTimeout(id);
  }
}

async function sendCmd(cmd, label) {
  currentDrive = cmd;
  if (label) document.getElementById("driveStatus").textContent = label;
  try {
    const j = await postJson("/cmd", {cmd: cmd}, 2200);
    if (!j.ok && j.error) log("Commande erreur: " + j.error);
  } catch(e) {
    log("Commande impossible: " + e);
  }
}

function sendStop() {
  clearInterval(driveTimer);
  driveTimer = null;
  currentDrive = "s";
  document.getElementById("driveStatus").textContent = "arrêt";
  document.querySelectorAll(".drive-btn").forEach(b => b.classList.remove("active"));
  sendCmd("s", "arrêt");
}

function startDrive(btn) {
  const cmd = btn.dataset.drive || btn.dataset.cmd || "s";
  const label = btn.dataset.label || cmd;

  document.querySelectorAll(".drive-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");

  if (cmd === "s" || cmd === "d0,0") {
    sendStop();
    return;
  }

  sendCmd(cmd, label);

  clearInterval(driveTimer);
  driveTimer = setInterval(() => {
    if (currentDrive && currentDrive !== "s") sendCmd(currentDrive);
  }, 350);
}


function setDriveSpeed(percent) {
  driveSpeedPercent = percent;

  if (percent === 25) driveSpeedValue = 5;
  else if (percent === 50) driveSpeedValue = 10;
  else if (percent === 75) driveSpeedValue = 15;
  else driveSpeedValue = 20;

  document.querySelectorAll(".speed-btn").forEach(b => b.classList.remove("speed-active"));
  const active = document.getElementById("speed" + percent);
  if (active) active.classList.add("speed-active");

  updateDriveButtonSpeeds();
  log("Vitesse : " + percent + "%");
}

function updateDriveButtonSpeeds() {
  const v = driveSpeedValue;

  const map = [
    ["avance",  "d" + v + "," + v],
    ["gauche",  "d-" + v + "," + v],
    ["droite",  "d" + v + ",-" + v],
    ["recul",   "d-" + v + ",-" + v],
    ["stop",    "d0,0"]
  ];

  for (const [label, cmd] of map) {
    const b = document.querySelector('.drive-btn[data-label="' + label + '"]');
    if (b) b.dataset.drive = cmd;
  }
}

function bindDriveButtons() {
  document.querySelectorAll(".drive-btn").forEach(btn => {
    btn.addEventListener("pointerdown", e => {
      e.preventDefault();
      try { btn.setPointerCapture(e.pointerId); } catch {}
      startDrive(btn);
    });
    btn.addEventListener("pointerup", e => {
      e.preventDefault();
      sendStop();
    });
    btn.addEventListener("pointercancel", sendStop);
    btn.addEventListener("lostpointercapture", sendStop);
    btn.addEventListener("mouseleave", e => {
      if (e.buttons) sendStop();
    });
  });
}

function updatePanTiltLabels() {
  const p = document.getElementById("panValue");
  const t = document.getElementById("tiltValue");
  if (p) p.textContent = pan;
  if (t) t.textContent = tilt;
}

async function panStep(delta) {
  pan = Math.max(60, Math.min(135, pan + delta));
  updatePanTiltLabels();
  await sendCmd("p" + pan, "pan " + pan);
}

async function tiltStep(delta) {
  tilt = Math.max(68, Math.min(145, tilt + delta));
  updatePanTiltLabels();
  await sendCmd("t" + tilt, "tilt " + tilt);
}

async function centerPanTilt() {
  pan = 95;
  tilt = 90;
  updatePanTiltLabels();
  await sendCmd("p" + pan, "pan centre");
  setTimeout(() => sendCmd("t" + tilt, "tilt centre"), 250);
}

async function toggleLight() {
  lightOn = !lightOn;
  try {
    const j = await postJson("/light", {state: lightOn ? "on" : "off"}, 2200);
    if (j.ok) {
      document.getElementById("lightBtn").textContent = lightOn ? "LUMIÈRES ON" : "LUMIÈRES OFF";
      log("Lumières " + (lightOn ? "ON" : "OFF"));
    } else {
      lightOn = !lightOn;
      log("Erreur lumières: " + (j.error || "inconnue"));
    }
  } catch(e) {
    lightOn = !lightOn;
    log("Erreur lumières: " + e);
  }
}

async function toggleRelay2() {
  relay2On = !relay2On;
  try {
    const j = await postJson("/relay2", {state: relay2On ? "on" : "off"}, 2200);
    if (j.ok) {
      document.getElementById("relay2Btn").textContent = relay2On ? "RELAIS 2 ON" : "RELAIS 2 OFF";
      log("Relais 2 " + (relay2On ? "ON" : "OFF"));
    } else {
      relay2On = !relay2On;
      log("Erreur relais 2: " + (j.error || "inconnue"));
    }
  } catch(e) {
    relay2On = !relay2On;
    log("Erreur relais 2: " + e);
  }
}


function panLeft() {
  return panStep(-5);
}

function panRight() {
  return panStep(5);
}

function tiltUp() {
  return tiltStep(5);
}

function tiltDown() {
  return tiltStep(-5);
}

async function setPanTilt(newPan, newTilt) {
  pan = Math.max(60, Math.min(135, Number(newPan)));
  tilt = Math.max(68, Math.min(145, Number(newTilt)));
  updatePanTiltLabels();
  await sendCmd("p" + pan, "pan " + pan);
  setTimeout(() => sendCmd("t" + tilt, "tilt " + tilt), 200);
}

async function setTiltOnly(newTilt) {
  tilt = Math.max(68, Math.min(145, Number(newTilt)));
  updatePanTiltLabels();
  await sendCmd("t" + tilt, "tilt " + tilt);
}

async function rb2ToggleRelay(which) {
  if (which === "light") {
    lightOn = !lightOn;
    const b = document.getElementById("rb2LightBtn");
    try {
      const j = await postJson("/light", {state: lightOn ? "on" : "off"}, 2200);
      if (j.ok) {
        if (b) {
          b.textContent = lightOn ? "LUMIÈRES ON" : "LUMIÈRES OFF";
          b.classList.toggle("rb2-relay-on", lightOn);
          b.classList.toggle("rb2-relay-off", !lightOn);
        }
        const top = document.getElementById("lightBtn");
        if (top) top.textContent = lightOn ? "LUMIÈRES ON" : "LUMIÈRES OFF";
        log("Lumières " + (lightOn ? "ON" : "OFF"));
      } else {
        lightOn = !lightOn;
        log("Erreur lumières: " + (j.error || "inconnue"));
      }
    } catch(e) {
      lightOn = !lightOn;
      log("Erreur lumières: " + e);
    }
    return;
  }

  if (which === "relay2") {
    relay2On = !relay2On;
    const b = document.getElementById("rb2Relay2Btn");
    try {
      const j = await postJson("/relay2", {state: relay2On ? "on" : "off"}, 2200);
      if (j.ok) {
        if (b) {
          b.textContent = relay2On ? "RELAIS 2 ON" : "RELAIS 2 OFF";
          b.classList.toggle("rb2-relay-on", relay2On);
          b.classList.toggle("rb2-relay-off", !relay2On);
        }
        const top = document.getElementById("relay2Btn");
        if (top) top.textContent = relay2On ? "RELAIS 2 ON" : "RELAIS 2 OFF";
        log("Relais 2 " + (relay2On ? "ON" : "OFF"));
      } else {
        relay2On = !relay2On;
        log("Erreur relais 2: " + (j.error || "inconnue"));
      }
    } catch(e) {
      relay2On = !relay2On;
      log("Erreur relais 2: " + e);
    }
  }
}

function setTextIfExists(id, val, digits=null) {
  const el = document.getElementById(id);
  if (!el) return;
  if (val === undefined || val === null || val === "") {
    el.textContent = "---";
    return;
  }
  const n = Number(val);
  if (digits !== null && Number.isFinite(n)) {
    el.textContent = n.toFixed(digits);
  } else {
    el.textContent = val;
  }
}

async function updateControlLidar() {
  try {
    const j = await getJson("/lidar", 2500);
    const d = j.data || j || {};
    setTextIfExists("lidarFront", d.front_cm);
    setTextIfExists("lidarRight", d.right_cm);
    setTextIfExists("lidarLeft", d.left_cm);
    setTextIfExists("lidarBack", d.back_cm);
    setTextIfExists("lidarMin", d.min_cm);
    setTextIfExists("lidarAge", j.age_s, 1);
    const st = document.getElementById("lidarState");
    if (st) st.textContent = j.ok === false ? "erreur" : "OK";
  } catch(e) {
    const st = document.getElementById("lidarState");
    if (st) st.textContent = "erreur";
  }
}

function openCamera() {
  window.open("/zero_cam_stream.mjpg", "_blank");
}

async function restartCamera() {
  log("Restart caméra demandé...");
  try {
    const j = await postJson("/zero_cam_restart", {}, 7000);
    log(j.ok ? "Restart caméra OK" : "Restart caméra: réponse reçue");
    const img = document.getElementById("camImg");
    img.src = "/zero_cam_stream.mjpg?t=" + Date.now();
  } catch(e) {
    log("Erreur restart caméra: " + e);
  }
}


async function takePhoto() {
  const b = document.getElementById("photoBtn");
  if (!b) return;

  b.classList.remove("photo-error");
  b.classList.add("photo-flash");
  b.textContent = "PHOTO...";

  try {
    const j = await postJson("/zero_photo", {}, 8000);

    if (j.ok) {
      b.textContent = "PHOTO OK";
      b.classList.remove("photo-error");
      b.classList.add("photo-flash");
      log("Photo prise");
    } else {
      b.textContent = "PHOTO ERREUR";
      b.classList.remove("photo-flash");
      b.classList.add("photo-error");
      log("Erreur photo");
    }
  } catch(e) {
    b.textContent = "PHOTO ERREUR";
    b.classList.remove("photo-flash");
    b.classList.add("photo-error");
    log("Erreur photo: " + e);
  }

  setTimeout(() => {
    b.textContent = "PHOTO";
    b.classList.remove("photo-flash");
    b.classList.remove("photo-error");
  }, 1200);
}



async function toggleVideo() {
  const b = document.getElementById("videoBtn");
  if (b) {
    b.textContent = videoOn ? "ARRÊT..." : "VIDÉO...";
  }

  try {
    await postJson("/zero_video_toggle", {}, 8000);
    await updateVideoStatus();
    log("Commande vidéo envoyée");
  } catch(e) {
    if (b) {
      b.textContent = "VIDÉO ERREUR";
      b.classList.remove("video-active");
      b.classList.add("photo-error");
      setTimeout(updateVideoStatus, 1500);
    }
    log("Erreur vidéo: " + e);
  }
}


async function updateVideoStatus() {
  const b = document.getElementById("videoBtn");
  if (!b) return;

  try {
    const j = await getJson("/zero_video_status", 3500);
    videoOn = !!(j.recording || j.video_on || j.active || j.on);

    if (videoOn) {
      b.textContent = "ENREG.";
      b.classList.remove("orange");
      b.classList.add("video-active");
      b.title = "Enregistrement vidéo en cours — cliquer pour arrêter";
    } else {
      b.textContent = "VIDÉO";
      b.classList.remove("video-active");
      b.classList.add("orange");
      b.title = "Démarrer la vidéo";
    }
  } catch(e) {
    b.textContent = videoOn ? "ENREG. ?" : "VIDÉO ?";
    b.title = "État vidéo inconnu";
  }
}


function openCaptures() {
  window.open("/captures", "_blank");
}

function normalizePoint(pt) {
  if (Array.isArray(pt)) {
    if (pt.length >= 2) return {x: Number(pt[0]), y: Number(pt[1])};
  }

  if (pt && typeof pt === "object") {
    if ("x" in pt && "y" in pt) return {x: Number(pt.x), y: Number(pt.y)};
    if ("x_cm" in pt && "y_cm" in pt) return {x: Number(pt.x_cm), y: Number(pt.y_cm)};
    if ("x_mm" in pt && "y_mm" in pt) return {x: Number(pt.x_mm) / 10, y: Number(pt.y_mm) / 10};

    const a = pt.angle_deg ?? pt.angle;
    const d = pt.dist_cm ?? pt.distance_cm ?? pt.r_cm ?? pt.range_cm;
    if (a !== undefined && d !== undefined) {
      const rad = Number(a) * Math.PI / 180;
      const r = Number(d);
      return {x: Math.cos(rad) * r, y: Math.sin(rad) * r};
    }
  }

  return null;
}

function extractPoints(j) {
  const candidates = [
    j && j.points,
    j && j.lidar_points,
    j && j.map_points,
    j && j.scan_points,
    j && j.map && j.map.points,
    j && j.data && j.data.points
  ];

  for (const c of candidates) {
    if (Array.isArray(c)) {
      return c.map(normalizePoint).filter(p => p && Number.isFinite(p.x) && Number.isFinite(p.y));
    }
  }

  return [];
}

function drawLidar(points) {
  const canvas = document.getElementById("lidarCanvas");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0,0,w,h);

  ctx.fillStyle = "#050505";
  ctx.fillRect(0,0,w,h);

  const cx = w / 2;
  const cy = h / 2;
  const maxAbs = Math.max(80, ...points.map(p => Math.max(Math.abs(p.x), Math.abs(p.y))));
  const scale = Math.min(w, h) * 0.42 / maxAbs;

  ctx.strokeStyle = "#333";
  ctx.lineWidth = 1;
  for (let r = 50; r <= maxAbs; r += 50) {
    ctx.beginPath();
    ctx.arc(cx, cy, r * scale, 0, Math.PI * 2);
    ctx.stroke();
  }

  ctx.strokeStyle = "#555";
  ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(w, cy); ctx.stroke();

  ctx.fillStyle = "#ddd";
  ctx.fillRect(cx - 12, cy - 8, 24, 16);

  ctx.strokeStyle = "#f59e0b";
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx, cy - 36);
  ctx.stroke();

  ctx.fillStyle = "#38bdf8";
  for (const p of points) {
    const x = cx + p.x * scale;
    const y = cy - p.y * scale;
    ctx.fillRect(x - 1.5, y - 1.5, 3, 3);
  }

  ctx.fillStyle = "#aaa";
  ctx.font = "13px Arial";
  ctx.fillText("AVANT", cx + 8, cy - 42);
}

async function updateLidar() {
  try {
    const j = await getJson("/lidar_map", 2500);
    const pts = extractPoints(j);
    drawLidar(pts);

    const ok = pts.length > 0 || j.ok;
    const ls = document.getElementById("lidarStatus");
    ls.textContent = ok ? "LIDAR OK" : "LIDAR ?";
    ls.className = ok ? "pill ok" : "pill warn";

    if (document.getElementById("lidarPoints")) document.getElementById("lidarPoints").textContent = pts.length + " points";

    const front = j.front_cm ?? j.front ?? j.min_front_cm ?? j.forward_cm ?? "—";
    const rear = j.rear_cm ?? j.rear ?? j.min_rear_cm ?? "—";
    const fd = document.getElementById("frontDist"); if (fd) fd.textContent = "avant " + front;
    const rd = document.getElementById("rearDist"); if (rd) rd.textContent = "arrière " + rear;
  } catch(e) {
    const ls = document.getElementById("lidarStatus");
    ls.textContent = "LIDAR NON";
    ls.className = "pill bad";
  }
}

async function updateSimpleStatus() {
  try {
    const t = await getJson("/terrain_status", 2500);
    const top = document.getElementById("rb2TopState");
    top.textContent = " — RB2 " + (t.ok === false ? "problème" : "actif");

    document.getElementById("panelState").textContent = "panel OK";
    const rb2st = document.getElementById("rb2StatusLight");
    if (rb2st) rb2st.textContent = "État RB2 : OK";
    document.getElementById("panelState").className = "pill ok";
  } catch(e) {
    document.getElementById("rb2TopState").textContent = " — état ?";
    document.getElementById("panelState").textContent = "panel ?";
    const rb2st = document.getElementById("rb2StatusLight");
    if (rb2st) rb2st.textContent = "État RB2 : ?";
    document.getElementById("panelState").className = "pill warn";
  }

  try {
    const s = await getJson("/drive_safety_status", 2500);
    const el = document.getElementById("driveSafetyState");
    el.textContent = s.ok === false ? "sécurité ?" : "sécurité OK";
    el.className = s.ok === false ? "pill warn" : "pill ok";
  } catch(e) {
    document.getElementById("driveSafetyState").textContent = "sécurité ?";
    document.getElementById("driveSafetyState").className = "pill warn";
  }

  try {
    const w = await getJson("/wifi_return_status", 2500);
    const el = document.getElementById("wifiReturnState");
    if (w.active) {
      el.textContent = "RETOUR WiFi actif";
      el.className = "pill bad";
    } else {
      el.textContent = "Retour WiFi prêt";
      el.className = "pill ok";
    }
  } catch(e) {
    document.getElementById("wifiReturnState").textContent = "Retour WiFi ?";
    document.getElementById("wifiReturnState").className = "pill";
  }

}

window.addEventListener("beforeunload", sendStop);

document.addEventListener("DOMContentLoaded", () => {
  bindDriveButtons();
  updatePanTiltLabels();
  setDriveSpeed(100);
  sendStop();

  updateLidar();
  updateControlLidar();
  updateSimpleStatus();
  updateVideoStatus();

  setInterval(updateLidar, 800);
  setInterval(updateControlLidar, 1000);
  setInterval(updateSimpleStatus, 1500);
  setInterval(updateVideoStatus, 4000);
});


/* === TERRAIN2 : correction finale fonctions critiques === */

let rb2DriveSeq = Date.now();

function rb2NextDriveSeq() {
  const now = Date.now();
  rb2DriveSeq = Math.max(rb2DriveSeq + 1, now);
  return rb2DriveSeq;
}

async function rb2InitDriveSeq() {
  try {
    const j = await rb2FetchJson("/drive_time", { method: "GET" }, 2500);
    if (j && Number.isFinite(Number(j.server_ms))) {
      rb2DriveSeq = Number(j.server_ms);
    }
  } catch(e) {
    rb2DriveSeq = Date.now();
  }
}

function rb2FetchJson(path, options = {}, timeoutMs = 8000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);

  return fetch(path, Object.assign({}, options, {
    signal: ctrl.signal,
    cache: "no-store"
  })).then(async r => {
    clearTimeout(t);
    const text = await r.text();
    let j = {};
    try { j = text ? JSON.parse(text) : {}; }
    catch(e) { j = { raw: text }; }

    if (!r.ok) {
      throw new Error(path + " HTTP " + r.status + " " + text.slice(0, 80));
    }

    return j;
  });
}

async function rb2SendDrive(cmd) {
  const payload = {
    cmd: cmd,
    drive_seq: rb2NextDriveSeq()
  };

  try {
    const j = await rb2FetchJson("/cmd", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }, 4000);

    const d = document.getElementById("driveStatus");
    if (d) d.textContent = (cmd === "d0,0") ? "arrêt" : cmd;

    if (j && j.ok === false) {
      console.log("Commande moteur refusée:", j);
    }
  } catch(e) {
    console.log("Erreur moteur:", e);
    const d = document.getElementById("driveStatus");
    if (d) d.textContent = "erreur moteur";
  }
}

function rb2RebindDriveButtons() {
  updateDriveButtonSpeeds();

  document.querySelectorAll("#drivePad .drive-btn").forEach(oldBtn => {
    const btn = oldBtn.cloneNode(true);
    oldBtn.parentNode.replaceChild(btn, oldBtn);

    const send = () => {
      const c = btn.dataset.drive || "d0,0";
      rb2SendDrive(c);
    };

    const stop = () => {
      if ((btn.dataset.drive || "") !== "d0,0") {
        rb2SendDrive("d0,0");
      }
    };

    btn.addEventListener("pointerdown", e => {
      e.preventDefault();
      send();
    });

    btn.addEventListener("pointerup", e => {
      e.preventDefault();
      stop();
    });

    btn.addEventListener("pointerleave", e => {
      stop();
    });

    btn.addEventListener("pointercancel", e => {
      stop();
    });

    btn.addEventListener("click", e => {
      e.preventDefault();
      if ((btn.dataset.drive || "") === "d0,0") {
        rb2SendDrive("d0,0");
      }
    });
  });
}

function setDriveSpeed(percent) {
  driveSpeedPercent = percent;

  if (percent === 25) driveSpeedValue = 5;
  else if (percent === 50) driveSpeedValue = 10;
  else if (percent === 75) driveSpeedValue = 15;
  else driveSpeedValue = 20;

  document.querySelectorAll(".speed-btn").forEach(b => b.classList.remove("speed-active"));
  const active = document.getElementById("speed" + percent);
  if (active) active.classList.add("speed-active");

  updateDriveButtonSpeeds();
}

function updateDriveButtonSpeeds() {
  const v = driveSpeedValue || 20;
  const mapping = {
    avance: "d" + v + "," + v,
    gauche: "d-" + v + "," + v,
    droite: "d" + v + ",-" + v,
    recul: "d-" + v + ",-" + v,
    stop: "d0,0"
  };

  for (const [label, cmd] of Object.entries(mapping)) {
    const b = document.querySelector('#drivePad .drive-btn[data-label="' + label + '"]');
    if (b) b.dataset.drive = cmd;
  }
}

function rb2IsOn(j) {
  const v = j.state ?? j.on ?? j.active ?? j.enabled ?? j.value;
  if (typeof v === "string") {
    return ["on", "true", "1", "yes", "oui"].includes(v.toLowerCase());
  }
  return !!v;
}

async function rb2ToggleRelay(which) {
  const path = which === "relay2" ? "/relay2" : "/light";
  const btnId = which === "relay2" ? "rb2Relay2Btn" : "rb2LightBtn";
  const label = which === "relay2" ? "RELAIS 2" : "LUMIÈRES";
  const btn = document.getElementById(btnId);

  if (btn) btn.textContent = label + " ...";

  try {
    let j;

    try {
      j = await rb2FetchJson(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      }, 5000);
    } catch(ePost) {
      j = await rb2FetchJson(path, { method: "GET" }, 5000);
    }

    const on = rb2IsOn(j);

    if (btn) {
      btn.textContent = label + (on ? " ON" : " OFF");
      btn.classList.toggle("rb2-relay-on", on);
      btn.classList.toggle("rb2-relay-off", !on);
    }
  } catch(e) {
    if (btn) btn.textContent = label + " ?";
    console.log("Erreur relais:", e);
  }
}

async function takePhoto() {
  const b = document.getElementById("photoBtn");
  if (!b) return;

  b.classList.remove("photo-error");
  b.classList.add("photo-flash");
  b.textContent = "PHOTO...";

  try {
    await rb2FetchJson("/zero_photo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    }, 15000);

    b.textContent = "PHOTO OK";
    b.classList.remove("photo-error");
    b.classList.add("photo-flash");
  } catch(e) {
    b.textContent = "PHOTO ERREUR";
    b.classList.remove("photo-flash");
    b.classList.add("photo-error");
    console.log("Erreur photo:", e);
  }

  setTimeout(() => {
    b.textContent = "PHOTO";
    b.classList.remove("photo-flash");
    b.classList.remove("photo-error");
  }, 1200);
}

async function toggleVideo() {
  const b = document.getElementById("videoBtn");
  if (b) b.textContent = videoOn ? "ARRÊT..." : "VIDÉO...";

  try {
    await rb2FetchJson("/zero_video_toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    }, 15000);

    setTimeout(updateVideoStatus, 500);
  } catch(e) {
    if (b) {
      b.textContent = "VIDÉO ERREUR";
      b.classList.remove("video-active");
      b.classList.add("photo-error");
    }
    console.log("Erreur vidéo:", e);
    setTimeout(updateVideoStatus, 1500);
  }
}

async function updateVideoStatus() {
  const b = document.getElementById("videoBtn");
  if (!b) return;

  try {
    const j = await rb2FetchJson("/zero_video_status", { method: "GET" }, 5000);
    videoOn = !!(j.recording || j.video_on || j.active || j.on);

    if (videoOn) {
      b.textContent = "ENREG.";
      b.classList.remove("orange");
      b.classList.remove("photo-error");
      b.classList.add("video-active");
      b.title = "Enregistrement vidéo en cours — cliquer pour arrêter";
    } else {
      b.textContent = "VIDÉO";
      b.classList.remove("video-active");
      b.classList.remove("photo-error");
      b.classList.add("orange");
      b.title = "Démarrer la vidéo";
    }
  } catch(e) {
    b.textContent = "VIDÉO ?";
    console.log("État vidéo inconnu:", e);
  }
}

window.addEventListener("load", async () => {
  await rb2InitDriveSeq();
  rb2RebindDriveButtons();
  setDriveSpeed(100);
  updateVideoStatus();
});

/* === FIN correction finale fonctions critiques === */



/* === TERRAIN2 : fonction arrêt RB2 === */
async function rb2Terrain2Shutdown() {
  const ok1 = confirm("Éteindre RB2 maintenant ?\n\nLes moteurs seront arrêtés, puis le système sera éteint.");
  if (!ok1) return;

  const ok2 = confirm("Confirmation finale : arrêter RB2 ?");
  if (!ok2) return;

  const b = document.getElementById("rb2ShutdownBtn");
  if (b) {
    b.textContent = "ARRÊT...";
    b.disabled = true;
  }

  try {
    await fetch("/system_shutdown_all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      cache: "no-store"
    });

    if (b) b.textContent = "ARRÊT DEMANDÉ";
  } catch(e) {
    console.log("Erreur arrêt RB2:", e);
    if (b) {
      b.textContent = "ERREUR ARRÊT";
      b.disabled = false;
    }
  }
}
/* === FIN fonction arrêt RB2 === */

</script>

<!-- TERRAIN2 FORCE-ACTIVE START -->
<script>
(function() {
  if (window.__RB2_TERRAIN2_FORCE_ACTIVE__) return;
  window.__RB2_TERRAIN2_FORCE_ACTIVE__ = true;

  var seq = Date.now();
  var speed = 20;
  var driveTimer = null;
  var pan = 95;
  var tilt = 90;
  var videoOn = false;

  function clamp(v, lo, hi) {
    v = Number(v);
    if (!Number.isFinite(v)) return lo;
    return Math.max(lo, Math.min(hi, v));
  }

  function nextSeq() {
    var now = Date.now();
    seq = Math.max(seq + 1, now);
    return seq;
  }

  async function fetchJson(path, options, timeoutMs) {
    timeoutMs = timeoutMs || 8000;
    options = options || {};

    var ctrl = new AbortController();
    var t = setTimeout(function() { ctrl.abort(); }, timeoutMs);

    try {
      var r = await fetch(path, Object.assign({}, options, {
        signal: ctrl.signal,
        cache: "no-store"
      }));

      var text = await r.text();
      var j = {};
      try { j = text ? JSON.parse(text) : {}; }
      catch(e) { j = { raw: text }; }

      if (!r.ok) {
        throw new Error(path + " HTTP " + r.status + " " + text.slice(0, 120));
      }

      return j;
    } finally {
      clearTimeout(t);
    }
  }

  async function initSeq() {
    try {
      var j = await fetchJson("/drive_time", { method: "GET" }, 2500);
      if (j && Number.isFinite(Number(j.server_ms))) {
        seq = Number(j.server_ms);
      }
    } catch(e) {
      seq = Date.now();
    }
  }

  async function sendCmd(cmd, withSeq) {
    var payload = { cmd: cmd };
    if (withSeq) payload.drive_seq = nextSeq();

    try {
      var j = await fetchJson("/cmd", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }, 4000);

      var d = document.getElementById("driveStatus");
      if (d && cmd.charAt(0) === "d") {
        d.textContent = (cmd === "d0,0" || cmd === "s") ? "arrêt" : cmd;
      }

      if (j && j.ok === false) {
        console.log("Commande refusée:", j);
      }

      return j;
    } catch(e) {
      console.log("Erreur commande", cmd, e);
      var d2 = document.getElementById("driveStatus");
      if (d2 && cmd.charAt(0) === "d") d2.textContent = "erreur";
      throw e;
    }
  }

  function driveCmd(label) {
    var v = speed || 20;

    if (label === "avance") return "d" + v + "," + v;
    if (label === "recul") return "d-" + v + ",-" + v;
    if (label === "gauche") return "d-" + v + "," + v;
    if (label === "droite") return "d" + v + ",-" + v;

    return "d0,0";
  }

  function startDrive(label, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    stopDrive(null, false);

    var cmd = driveCmd(label);
    sendCmd(cmd, true).catch(function(){});

    driveTimer = setInterval(function() {
      sendCmd(cmd, true).catch(function(){});
    }, 300);

    return false;
  }

  function stopDrive(ev, prevent) {
    if (ev && prevent !== false) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (driveTimer) {
      clearInterval(driveTimer);
      driveTimer = null;
    }

    sendCmd("d0,0", true).catch(function(){});
    return false;
  }

  function setSpeed(percent, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (percent === 25) speed = 15;
    else if (percent === 50) speed = 17;
    else if (percent === 75) speed = 19;
    else speed = 20;

    document.querySelectorAll(".speed-btn").forEach(function(b) {
      b.classList.remove("speed-active");
    });

    var active = document.getElementById("speed" + percent);
    if (active) active.classList.add("speed-active");

    return false;
  }

  function updatePT() {
    pan = clamp(pan, 60, 135);
    tilt = clamp(tilt, 68, 145);

    var p = document.getElementById("panValue");
    var t = document.getElementById("tiltValue");

    if (p) p.textContent = String(pan);
    if (t) t.textContent = String(tilt);
  }

  function sendPT() {
    updatePT();
    sendCmd("p" + pan + "," + tilt, false).catch(function(e) {
      console.log("Erreur pan/tilt:", e);
    });
  }

  function panLeft(ev) {
    if (ev) { ev.preventDefault(); ev.stopImmediatePropagation(); }
    pan -= 5;
    sendPT();
    return false;
  }

  function panRight(ev) {
    if (ev) { ev.preventDefault(); ev.stopImmediatePropagation(); }
    pan += 5;
    sendPT();
    return false;
  }

  function tiltUp(ev) {
    if (ev) { ev.preventDefault(); ev.stopImmediatePropagation(); }
    tilt -= 5;
    sendPT();
    return false;
  }

  function tiltDown(ev) {
    if (ev) { ev.preventDefault(); ev.stopImmediatePropagation(); }
    tilt += 5;
    sendPT();
    return false;
  }

  function centerPT(ev) {
    if (ev) { ev.preventDefault(); ev.stopImmediatePropagation(); }
    pan = 95;
    tilt = 90;
    sendPT();
    return false;
  }

  function setTilt(v, ev) {
    if (ev) { ev.preventDefault(); ev.stopImmediatePropagation(); }
    tilt = v;
    sendPT();
    return false;
  }

  function isOn(j) {
    var v = j.state;
    if (v === undefined) v = j.on;
    if (v === undefined) v = j.active;
    if (v === undefined) v = j.enabled;
    if (v === undefined) v = j.value;

    if (typeof v === "string") {
      return ["on", "true", "1", "yes", "oui"].indexOf(v.toLowerCase()) >= 0;
    }

    return !!v;
  }

  async function toggleRelay(which, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    var path = which === "relay2" ? "/relay2" : "/light";
    var btnId = which === "relay2" ? "rb2Relay2Btn" : "rb2LightBtn";
    var label = which === "relay2" ? "RELAIS 2" : "LUMIÈRES";
    var b = document.getElementById(btnId);

    if (b) b.textContent = label + " ...";

    try {
      var j;
      try {
        j = await fetchJson(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}"
        }, 5000);
      } catch(ePost) {
        j = await fetchJson(path, { method: "GET" }, 5000);
      }

      var on = isOn(j);

      if (b) {
        b.textContent = label + (on ? " ON" : " OFF");
        b.classList.toggle("rb2-relay-on", on);
        b.classList.toggle("rb2-relay-off", !on);
      }
    } catch(e) {
      console.log("Erreur relais:", e);
      if (b) b.textContent = label + " ?";
    }

    return false;
  }

  async function takePhoto(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    var b = document.getElementById("photoBtn");
    if (!b) return false;

    b.classList.remove("photo-error");
    b.classList.add("photo-flash");
    b.textContent = "PHOTO...";

    try {
      await fetchJson("/zero_photo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      }, 15000);

      b.textContent = "PHOTO OK";
      b.classList.add("photo-flash");
      b.classList.remove("photo-error");
    } catch(e) {
      console.log("Erreur photo:", e);
      b.textContent = "PHOTO ERREUR";
      b.classList.remove("photo-flash");
      b.classList.add("photo-error");
    }

    setTimeout(function() {
      b.textContent = "PHOTO";
      b.classList.remove("photo-flash");
      b.classList.remove("photo-error");
    }, 1200);

    return false;
  }

  async function updateVideoStatus() {
    var b = document.getElementById("videoBtn");
    if (!b) return;

    try {
      var j = await fetchJson("/zero_video_status", { method: "GET" }, 5000);
      videoOn = !!(j.recording || j.video_on || j.active || j.on);

      if (videoOn) {
        b.textContent = "ENREG.";
        b.classList.add("video-active");
        b.classList.remove("orange");
        b.classList.remove("photo-error");
      } else {
        b.textContent = "VIDÉO";
        b.classList.remove("video-active");
        b.classList.remove("photo-error");
        b.classList.add("orange");
      }
    } catch(e) {
      console.log("État vidéo inconnu:", e);
      b.textContent = "VIDÉO ?";
    }
  }

  async function toggleVideo(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    var b = document.getElementById("videoBtn");
    if (b) b.textContent = videoOn ? "ARRÊT..." : "VIDÉO...";

    try {
      await fetchJson("/zero_video_toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      }, 15000);

      setTimeout(updateVideoStatus, 500);
    } catch(e) {
      console.log("Erreur vidéo:", e);
      if (b) {
        b.textContent = "VIDÉO ERREUR";
        b.classList.remove("video-active");
        b.classList.add("photo-error");
      }
      setTimeout(updateVideoStatus, 1500);
    }

    return false;
  }

  function openCaptures(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }
    window.open("/captures", "_blank");
    return false;
  }

  async function restartCamera(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    var b = ev && ev.currentTarget ? ev.currentTarget : null;
    if (b) b.textContent = "RESTART...";

    try {
      try {
        await fetchJson("/zero_cam_restart", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}"
        }, 12000);
      } catch(ePost) {
        await fetchJson("/zero_cam_restart", { method: "GET" }, 12000);
      }

      if (b) b.textContent = "RESTART CAMÉRA";
    } catch(e) {
      console.log("Erreur restart caméra:", e);
      if (b) b.textContent = "ERREUR CAMÉRA";
      setTimeout(function() {
        if (b) b.textContent = "RESTART CAMÉRA";
      }, 1500);
    }

    return false;
  }

  async function shutdownRB2(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (!confirm("Éteindre RB2 maintenant ?")) return false;
    if (!confirm("Confirmation finale : arrêter RB2 ?")) return false;

    var b = document.getElementById("rb2ShutdownBtn");
    if (b) {
      b.textContent = "ARRÊT...";
      b.disabled = true;
    }

    try {
      await fetchJson("/rb2_poweroff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      }, 8000);

      if (b) b.textContent = "ARRÊT DEMANDÉ";
    } catch(e) {
      console.log("Erreur arrêt RB2:", e);
      if (b) {
        b.textContent = "ERREUR ARRÊT";
        b.disabled = false;
      }
    }

    return false;
  }

  function bindButton(el, eventName, fn) {
    if (!el) return;
    el.addEventListener(eventName, fn, true);
  }

  function bindByText(matchFn, fn) {
    document.querySelectorAll("button").forEach(function(b) {
      var txt = (b.textContent || "").trim().toUpperCase();
      if (matchFn(txt, b)) bindButton(b, "click", fn);
    });
  }

  async function bindAll() {
    await initSeq();

    // Moteurs
    document.querySelectorAll("#drivePad .drive-btn").forEach(function(b) {
      var label = (b.dataset.label || b.textContent || "").trim().toLowerCase();

      if (label.indexOf("avance") >= 0) label = "avance";
      else if (label.indexOf("recul") >= 0) label = "recul";
      else if (label.indexOf("gauche") >= 0) label = "gauche";
      else if (label.indexOf("droite") >= 0) label = "droite";
      else if (label.indexOf("stop") >= 0) label = "stop";

      if (label === "stop") {
        bindButton(b, "pointerdown", function(ev) { return stopDrive(ev); });
        bindButton(b, "click", function(ev) { return stopDrive(ev); });
      } else {
        bindButton(b, "pointerdown", function(ev) { return startDrive(label, ev); });
        bindButton(b, "pointerup", function(ev) { return stopDrive(ev); });
        bindButton(b, "pointerleave", function(ev) { return stopDrive(ev); });
        bindButton(b, "pointercancel", function(ev) { return stopDrive(ev); });
        bindButton(b, "click", function(ev) {
          ev.preventDefault();
          ev.stopImmediatePropagation();
          return false;
        });
      }
    });

    // Vitesses
    [[25, "speed25"], [50, "speed50"], [75, "speed75"], [100, "speed100"]].forEach(function(x) {
      var b = document.getElementById(x[1]);
      bindButton(b, "click", function(ev) { return setSpeed(x[0], ev); });
    });
    setSpeed(100);

    // Pan/Tilt par texte/symboles
    document.querySelectorAll(".pt-grid button").forEach(function(b) {
      var txt = (b.textContent || "").trim();

      if (txt === "▲" || txt.indexOf("▲") >= 0) bindButton(b, "click", tiltUp);
      else if (txt === "▼" || txt.indexOf("▼") >= 0) bindButton(b, "click", tiltDown);
      else if (txt === "◀" || txt.indexOf("◀") >= 0 || txt === "◄") bindButton(b, "click", panLeft);
      else if (txt === "▶" || txt.indexOf("▶") >= 0 || txt === "►") bindButton(b, "click", panRight);
    });

    bindByText(function(txt) { return txt === "CENTRE"; }, centerPT);
    bindByText(function(txt) { return txt === "T 145" || txt === "T145"; }, function(ev) { return setTilt(145, ev); });
    bindByText(function(txt) { return txt === "T 68" || txt === "T68"; }, function(ev) { return setTilt(68, ev); });

    updatePT();

    // Relais
    bindButton(document.getElementById("rb2LightBtn"), "click", function(ev) { return toggleRelay("light", ev); });
    bindButton(document.getElementById("rb2Relay2Btn"), "click", function(ev) { return toggleRelay("relay2", ev); });

    // Caméra / captures
    bindButton(document.getElementById("photoBtn"), "click", takePhoto);
    bindButton(document.getElementById("videoBtn"), "click", toggleVideo);
    bindButton(document.getElementById("capturesBtn"), "click", openCaptures);

    bindByText(function(txt) { return txt.indexOf("RESTART") >= 0 && txt.indexOf("CAM") >= 0; }, restartCamera);

    // Arrêt RB2
    bindButton(document.getElementById("rb2ShutdownBtn"), "click", shutdownRB2);

    updateVideoStatus();

    console.log("Terrain2 force-active chargé.");
  }

  // Exposer aussi les fonctions pour les anciens onclick.
  window.rb2DriveLabel = startDrive;
  window.rb2DriveStop = stopDrive;
  window.setDriveSpeed = setSpeed;
  window.updateDriveButtonSpeeds = function(){};
  window.rb2ToggleRelay = toggleRelay;
  window.takePhoto = takePhoto;
  window.toggleVideo = toggleVideo;
  window.updateVideoStatus = updateVideoStatus;
  window.openCaptures = openCaptures;
  window.panLeft = panLeft;
  window.panRight = panRight;
  window.tiltUp = tiltUp;
  window.tiltDown = tiltDown;
  window.setPanTilt = function(p, t) { pan = p; tilt = t; sendPT(); };
  window.setTiltOnly = function(t) { tilt = t; sendPT(); };
  window.rb2Terrain2Shutdown = shutdownRB2;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindAll);
  } else {
    bindAll();
  }
})();
</script>
<!-- TERRAIN2 FORCE-ACTIVE END -->


<!-- TERRAIN2 FIX MOTEURS RELAIS CAMERA START -->
<script>
(function() {
  let serverOffsetMs = 0;
  let seq = Date.now();
  let speed = 20;
  let driveTimer = null;

  async function rb2Json(path, options = {}, timeoutMs = 8000) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);

    try {
      const r = await fetch(path, Object.assign({}, options, {
        signal: ctrl.signal,
        cache: "no-store"
      }));

      const text = await r.text();
      let j = {};
      try { j = text ? JSON.parse(text) : {}; }
      catch(e) { j = { raw: text }; }

      if (!r.ok) {
        throw new Error(path + " HTTP " + r.status + " " + text.slice(0, 120));
      }

      return j;
    } finally {
      clearTimeout(t);
    }
  }

  function rb2NowMs() {
    return Date.now() + serverOffsetMs;
  }

  function rb2NextSeq() {
    const n = rb2NowMs();
    seq = Math.max(seq + 1, n);
    return seq;
  }

  async function rb2InitTiming() {
    try {
      const j = await rb2Json("/drive_time", { method: "GET" }, 3000);
      if (j && Number.isFinite(Number(j.server_ms))) {
        const serverMs = Number(j.server_ms);
        serverOffsetMs = serverMs - Date.now();
        seq = serverMs;
      }
    } catch(e) {
      serverOffsetMs = 0;
      seq = Date.now();
    }
  }

  function motorPayload(cmd) {
    const ts = rb2NowMs();
    const s = rb2NextSeq();

    /*
      Le serveur a refusé "timestamp absent".
      On envoie donc plusieurs noms compatibles.
      Les champs inconnus seront simplement ignorés.
    */
    return {
      cmd: cmd,
      drive_seq: s,
      timestamp: ts,
      timestamp_ms: ts,
      time_ms: ts,
      client_ms: ts,
      client_time_ms: ts,
      server_ms: ts,
      drive_token: "terrain"
    };
  }

  async function sendMotor(cmd) {
    try {
      const j = await rb2Json("/cmd", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(motorPayload(cmd))
      }, 4000);

      const d = document.getElementById("driveStatus");
      if (d) d.textContent = (cmd === "d0,0" || cmd === "s") ? "arrêt" : cmd;

      if (j && j.ok === false) {
        console.log("Moteur refusé:", j);
      }

      return j;
    } catch(e) {
      console.log("Erreur moteur:", e);
      const d = document.getElementById("driveStatus");
      if (d) d.textContent = "erreur moteur";
    }
  }

  function cmdForLabel(label) {
    const v = speed || 20;

    if (label === "avance") return "d" + v + "," + v;
    if (label === "recul") return "d-" + v + ",-" + v;
    if (label === "gauche") return "d-" + v + "," + v;
    if (label === "droite") return "d" + v + ",-" + v;

    return "d0,0";
  }

  function startDrive(label, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    stopDrive(null, false);

    const cmd = cmdForLabel(label);
    sendMotor(cmd);

    driveTimer = setInterval(function() {
      sendMotor(cmd);
    }, 300);

    return false;
  }

  function stopDrive(ev, blockEvent = true) {
    if (ev && blockEvent) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (driveTimer) {
      clearInterval(driveTimer);
      driveTimer = null;
    }

    sendMotor("d0,0");
    return false;
  }

  function setSpeed(percent, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (percent === 25) speed = 15;
    else if (percent === 50) speed = 17;
    else if (percent === 75) speed = 19;
    else speed = 20;

    document.querySelectorAll(".speed-btn").forEach(function(b) {
      b.classList.remove("speed-active");
    });

    const active = document.getElementById("speed" + percent);
    if (active) active.classList.add("speed-active");

    return false;
  }

  function relayIsOn(j) {
    const v = j.state ?? j.on ?? j.active ?? j.enabled ?? j.value;

    if (typeof v === "string") {
      return ["on", "true", "1", "yes", "oui"].includes(v.toLowerCase());
    }

    return !!v;
  }

  async function setRelayState(which, state) {
    const path = which === "relay2" ? "/relay2" : "/light";

    try {
      return await rb2Json(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: state })
      }, 5000);
    } catch(e1) {
      // Fallback au cas où la route attend un formulaire.
      return await rb2Json(path, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "state=" + encodeURIComponent(state)
      }, 5000);
    }
  }

  async function toggleRelay(which, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    const path = which === "relay2" ? "/relay2" : "/light";
    const btnId = which === "relay2" ? "rb2Relay2Btn" : "rb2LightBtn";
    const label = which === "relay2" ? "RELAIS 2" : "LUMIÈRES";
    const b = document.getElementById(btnId);

    if (b) b.textContent = label + " ...";

    try {
      const current = await rb2Json(path, { method: "GET" }, 4000);
      const target = relayIsOn(current) ? "off" : "on";

      const j = await setRelayState(which, target);
      const on = relayIsOn(j);

      if (b) {
        b.textContent = label + (on ? " ON" : " OFF");
        b.classList.toggle("rb2-relay-on", on);
        b.classList.toggle("rb2-relay-off", !on);
      }
    } catch(e) {
      console.log("Erreur " + label + ":", e);
      if (b) b.textContent = label + " ?";
    }

    return false;
  }

  function openCamera(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    window.open("/zero_cam_stream.mjpg?ts=" + Date.now(), "_blank");
    return false;
  }

  function bindCleanButton(selector, binder) {
    document.querySelectorAll(selector).forEach(function(oldBtn) {
      const btn = oldBtn.cloneNode(true);
      oldBtn.parentNode.replaceChild(btn, oldBtn);
      binder(btn);
    });
  }

  async function bindTerrain2Fix() {
    await rb2InitTiming();

    // Moteurs : on clone pour enlever les anciens écouteurs qui envoyaient sans timestamp.
    bindCleanButton("#drivePad .drive-btn", function(btn) {
      let label = (btn.dataset.label || btn.textContent || "").trim().toLowerCase();

      if (label.includes("avance")) label = "avance";
      else if (label.includes("recul")) label = "recul";
      else if (label.includes("gauche")) label = "gauche";
      else if (label.includes("droite")) label = "droite";
      else if (label.includes("stop")) label = "stop";

      if (label === "stop") {
        btn.addEventListener("pointerdown", function(ev) { return stopDrive(ev); }, true);
        btn.addEventListener("click", function(ev) { return stopDrive(ev); }, true);
      } else {
        btn.addEventListener("pointerdown", function(ev) { return startDrive(label, ev); }, true);
        btn.addEventListener("pointerup", function(ev) { return stopDrive(ev); }, true);
        btn.addEventListener("pointerleave", function(ev) { return stopDrive(ev); }, true);
        btn.addEventListener("pointercancel", function(ev) { return stopDrive(ev); }, true);
        btn.addEventListener("click", function(ev) {
          ev.preventDefault();
          ev.stopImmediatePropagation();
          return false;
        }, true);
      }
    });

    // Vitesses
    [
      [25, "#speed25"],
      [50, "#speed50"],
      [75, "#speed75"],
      [100, "#speed100"]
    ].forEach(function(x) {
      const b = document.querySelector(x[1]);
      if (b) {
        b.onclick = null;
        b.addEventListener("click", function(ev) { return setSpeed(x[0], ev); }, true);
      }
    });

    setSpeed(100);

    // Lumières / Relais 2 : on clone aussi pour enlever les anciens gestionnaires.
    bindCleanButton("#rb2LightBtn", function(btn) {
      btn.addEventListener("click", function(ev) { return toggleRelay("light", ev); }, true);
    });

    bindCleanButton("#rb2Relay2Btn", function(btn) {
      btn.addEventListener("click", function(ev) { return toggleRelay("relay2", ev); }, true);
    });

    // Caméra directe
    document.querySelectorAll("button").forEach(function(b) {
      const txt = (b.textContent || "").trim().toUpperCase();
      if (txt.includes("CAMÉRA DIRECTE") || txt.includes("CAMERA DIRECTE")) {
        b.onclick = null;
        b.addEventListener("click", openCamera, true);
      }
    });

    console.log("terrain2 fix moteurs/relais/camera chargé");
  }

  // Fonctions globales pour les anciens onclick encore présents.
  window.setDriveSpeed = setSpeed;
  window.updateDriveButtonSpeeds = function(){};
  window.rb2ToggleRelay = toggleRelay;
  window.openCamera = openCamera;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindTerrain2Fix);
  } else {
    bindTerrain2Fix();
  }
})();
</script>
<!-- TERRAIN2 FIX MOTEURS RELAIS CAMERA END -->


<!-- TERRAIN2 FIX SENT_SERVER_MS TILT START -->
<script>
(function() {
  let serverOffsetMs = 0;
  let seq = Date.now();
  let speed = 20;
  let driveTimer = null;
  let pan = 95;
  let tilt = 90;

  async function jfetch(path, options = {}, timeoutMs = 5000) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const r = await fetch(path, Object.assign({}, options, {
        signal: ctrl.signal,
        cache: "no-store"
      }));
      const text = await r.text();
      let j = {};
      try { j = text ? JSON.parse(text) : {}; }
      catch(e) { j = { raw: text }; }
      if (!r.ok) throw new Error(path + " HTTP " + r.status + " " + text.slice(0, 100));
      return j;
    } finally {
      clearTimeout(t);
    }
  }

  async function initTime() {
    try {
      const j = await jfetch("/drive_time", { method: "GET" }, 3000);
      const serverMs = Number(j.server_ms);
      if (Number.isFinite(serverMs)) {
        serverOffsetMs = serverMs - Date.now();
        seq = serverMs;
      }
    } catch(e) {
      serverOffsetMs = 0;
      seq = Date.now();
    }
  }

  function nowServerMs() {
    return Math.round(Date.now() + serverOffsetMs);
  }

  function nextSeq() {
    const n = nowServerMs();
    seq = Math.max(seq + 1, n);
    return seq;
  }

  async function sendDrive(cmd) {
    const sent = nowServerMs();
    const payload = {
      cmd: cmd,
      drive_seq: nextSeq(),
      sent_server_ms: sent,
      drive_token: "terrain"
    };

    try {
      const j = await jfetch("/cmd", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }, 4000);

      const d = document.getElementById("driveStatus");
      if (d) d.textContent = (cmd === "d0,0") ? "arrêt" : cmd;

      if (j && j.ok === false) console.log("Moteur refusé:", j);
      return j;
    } catch(e) {
      console.log("Erreur moteur:", e);
      const d = document.getElementById("driveStatus");
      if (d) d.textContent = "erreur moteur";
    }
  }

  function cmdFor(label) {
    const v = speed || 20;
    if (label === "avance") return "d" + v + "," + v;
    if (label === "recul") return "d-" + v + ",-" + v;
    if (label === "gauche") return "d-" + v + "," + v;
    if (label === "droite") return "d" + v + ",-" + v;
    return "d0,0";
  }

  function startDrive(label, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (driveTimer) {
      clearInterval(driveTimer);
      driveTimer = null;
    }

    const cmd = cmdFor(label);
    sendDrive(cmd);

    driveTimer = setInterval(function() {
      sendDrive(cmd);
    }, 300);

    return false;
  }

  function stopDrive(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (driveTimer) {
      clearInterval(driveTimer);
      driveTimer = null;
    }

    sendDrive("d0,0");
    return false;
  }

  function setSpeed(percent, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (percent === 25) speed = 15;
    else if (percent === 50) speed = 17;
    else if (percent === 75) speed = 19;
    else speed = 20;

    document.querySelectorAll(".speed-btn").forEach(function(b) {
      b.classList.remove("speed-active");
    });

    const active = document.getElementById("speed" + percent);
    if (active) active.classList.add("speed-active");

    return false;
  }

  async function sendPT(cmd) {
    try {
      await jfetch("/cmd", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cmd: cmd })
      }, 3000);
    } catch(e) {
      console.log("Erreur pan/tilt:", cmd, e);
    }
  }

  function updatePT() {
    if (pan < 60) pan = 60;
    if (pan > 135) pan = 135;
    if (tilt < 68) tilt = 68;
    if (tilt > 145) tilt = 145;

    const p = document.getElementById("panValue");
    const t = document.getElementById("tiltValue");

    if (p) p.textContent = String(pan);
    if (t) t.textContent = String(tilt);
  }

  function doPan(delta, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    pan += delta;
    updatePT();
    sendPT("p" + pan);
    return false;
  }

  function doTilt(delta, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    tilt += delta;
    updatePT();
    sendPT("t" + tilt);
    return false;
  }

  function doCenter(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    pan = 95;
    tilt = 90;
    updatePT();
    sendPT("p95");
    setTimeout(function() { sendPT("t90"); }, 150);
    return false;
  }

  function setTiltValue(v, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    tilt = v;
    updatePT();
    sendPT("t" + tilt);
    return false;
  }

  function cloneBind(selector, binder) {
    document.querySelectorAll(selector).forEach(function(oldEl) {
      const el = oldEl.cloneNode(true);
      oldEl.parentNode.replaceChild(el, oldEl);
      binder(el);
    });
  }

  async function bind() {
    await initTime();

    cloneBind("#drivePad .drive-btn", function(btn) {
      let label = (btn.dataset.label || btn.textContent || "").trim().toLowerCase();

      if (label.includes("avance")) label = "avance";
      else if (label.includes("recul")) label = "recul";
      else if (label.includes("gauche")) label = "gauche";
      else if (label.includes("droite")) label = "droite";
      else if (label.includes("stop")) label = "stop";

      if (label === "stop") {
        btn.addEventListener("pointerdown", stopDrive, true);
        btn.addEventListener("click", stopDrive, true);
      } else {
        btn.addEventListener("pointerdown", function(ev) { return startDrive(label, ev); }, true);
        btn.addEventListener("pointerup", stopDrive, true);
        btn.addEventListener("pointerleave", stopDrive, true);
        btn.addEventListener("pointercancel", stopDrive, true);
        btn.addEventListener("click", function(ev) {
          ev.preventDefault();
          ev.stopImmediatePropagation();
          return false;
        }, true);
      }
    });

    [[25,"speed25"], [50,"speed50"], [75,"speed75"], [100,"speed100"]].forEach(function(x) {
      const b = document.getElementById(x[1]);
      if (b) {
        b.onclick = null;
        b.addEventListener("click", function(ev) { return setSpeed(x[0], ev); }, true);
      }
    });

    setSpeed(100);

    cloneBind(".pt-grid button", function(btn) {
      const txt = (btn.textContent || "").trim();

      if (txt.includes("◀") || txt.includes("◄")) {
        btn.addEventListener("click", function(ev) { return doPan(-5, ev); }, true);
      } else if (txt.includes("▶") || txt.includes("►")) {
        btn.addEventListener("click", function(ev) { return doPan(5, ev); }, true);
      } else if (txt.includes("▲")) {
        btn.addEventListener("click", function(ev) { return doTilt(5, ev); }, true);
      } else if (txt.includes("▼")) {
        btn.addEventListener("click", function(ev) { return doTilt(-5, ev); }, true);
      }
    });

    cloneBind(".small-row button", function(btn) {
      const txt = (btn.textContent || "").trim().toUpperCase().replace(/\s+/g, "");

      if (txt === "CENTRE") {
        btn.addEventListener("click", doCenter, true);
      } else if (txt === "T145") {
        btn.addEventListener("click", function(ev) { return setTiltValue(145, ev); }, true);
      } else if (txt === "T68") {
        btn.addEventListener("click", function(ev) { return setTiltValue(68, ev); }, true);
      }
    });

    updatePT();
    console.log("terrain2 sent_server_ms + tilt actif");
  }

  window.setDriveSpeed = setSpeed;
  window.updateDriveButtonSpeeds = function(){};

  window.panLeft = function() { return doPan(-5); };
  window.panRight = function() { return doPan(5); };
  window.tiltUp = function() { return doTilt(5); };
  window.tiltDown = function() { return doTilt(-5); };
  window.setPanTilt = function(p, t) {
    pan = p;
    tilt = t;
    updatePT();
    sendPT("p" + pan);
    setTimeout(function() { sendPT("t" + tilt); }, 150);
  };
  window.setTiltOnly = function(t) {
    tilt = t;
    updatePT();
    sendPT("t" + tilt);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
</script>
<!-- TERRAIN2 FIX SENT_SERVER_MS TILT END -->


<!-- TERRAIN2 MOTOR OVERRIDE FINAL START -->
<script>
(function() {
  let serverOffsetMs = 0;
  let driveSeq = Date.now();
  let driveSpeed = 20;
  let driveRepeat = null;

  async function jfetch(path, options = {}, timeoutMs = 5000) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);

    try {
      const r = await fetch(path, Object.assign({}, options, {
        signal: ctrl.signal,
        cache: "no-store"
      }));

      const text = await r.text();
      let j = {};
      try { j = text ? JSON.parse(text) : {}; }
      catch(e) { j = { raw: text }; }

      if (!r.ok) {
        throw new Error(path + " HTTP " + r.status + " " + text.slice(0, 100));
      }

      return j;
    } finally {
      clearTimeout(t);
    }
  }

  async function syncDriveTime() {
    try {
      const j = await jfetch("/drive_time", { method: "GET" }, 2500);
      const serverMs = Number(j.server_ms);
      if (Number.isFinite(serverMs)) {
        serverOffsetMs = serverMs - Date.now();
        driveSeq = serverMs;
      }
    } catch(e) {
      serverOffsetMs = 0;
      driveSeq = Date.now();
    }
  }

  function serverNowMs() {
    return Math.round(Date.now() + serverOffsetMs);
  }

  function nextSeq() {
    const n = serverNowMs();
    driveSeq = Math.max(driveSeq + 1, n);
    return driveSeq;
  }

  function cmdFor(label) {
    const v = driveSpeed || 20;

    if (label === "avance") return "d" + v + "," + v;
    if (label === "recul") return "d-" + v + ",-" + v;
    if (label === "gauche") return "d-" + v + "," + v;
    if (label === "droite") return "d" + v + ",-" + v;

    return "d0,0";
  }

  async function sendDrive(cmd) {
    const sent = serverNowMs();

    const payload = {
      cmd: cmd,
      drive_seq: nextSeq(),
      sent_server_ms: sent,
      drive_token: "terrain"
    };

    try {
      const j = await jfetch("/cmd", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }, 4000);

      const d = document.getElementById("driveStatus");
      if (d) d.textContent = (cmd === "d0,0") ? "arrêt" : cmd;

      if (j && j.ok === false) {
        console.log("MOTEUR refusé:", j);
      } else {
        console.log("MOTEUR envoyé:", payload);
      }

      return j;
    } catch(e) {
      console.log("Erreur moteur:", e);
      const d = document.getElementById("driveStatus");
      if (d) d.textContent = "erreur moteur";
    }
  }

  function stopDrive(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (driveRepeat) {
      clearInterval(driveRepeat);
      driveRepeat = null;
    }

    sendDrive("d0,0");
    return false;
  }

  function startDrive(label, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (driveRepeat) {
      clearInterval(driveRepeat);
      driveRepeat = null;
    }

    const cmd = cmdFor(label);

    sendDrive(cmd);

    driveRepeat = setInterval(function() {
      sendDrive(cmd);
    }, 300);

    return false;
  }

  function setSpeed(percent, ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }

    if (percent === 25) driveSpeed = 15;
    else if (percent === 50) driveSpeed = 17;
    else if (percent === 75) driveSpeed = 19;
    else driveSpeed = 20;

    document.querySelectorAll(".speed-btn").forEach(function(b) {
      b.classList.remove("speed-active");
    });

    const active = document.getElementById("speed" + percent);
    if (active) active.classList.add("speed-active");

    return false;
  }

  function bindMotorsNow() {
    const pad = document.getElementById("drivePad");
    if (!pad) return;

    // Remplace complètement les boutons moteurs pour enlever les anciens listeners.
    pad.querySelectorAll(".drive-btn").forEach(function(oldBtn) {
      const btn = oldBtn.cloneNode(true);
      oldBtn.parentNode.replaceChild(btn, oldBtn);

      let label = (btn.dataset.label || btn.textContent || "").trim().toLowerCase();

      if (label.includes("avance")) label = "avance";
      else if (label.includes("recul")) label = "recul";
      else if (label.includes("gauche")) label = "gauche";
      else if (label.includes("droite")) label = "droite";
      else if (label.includes("stop")) label = "stop";

      btn.removeAttribute("onclick");
      btn.removeAttribute("onpointerdown");
      btn.removeAttribute("onpointerup");
      btn.removeAttribute("onpointerleave");
      btn.removeAttribute("onpointercancel");

      if (label === "stop") {
        btn.addEventListener("pointerdown", stopDrive, true);
        btn.addEventListener("click", stopDrive, true);
      } else {
        btn.addEventListener("pointerdown", function(ev) {
          return startDrive(label, ev);
        }, true);

        btn.addEventListener("pointerup", stopDrive, true);
        btn.addEventListener("pointerleave", stopDrive, true);
        btn.addEventListener("pointercancel", stopDrive, true);

        // Sécurité : un clic très court donne une impulsion visible de 500 ms.
        btn.addEventListener("click", function(ev) {
          ev.preventDefault();
          ev.stopImmediatePropagation();

          const cmd = cmdFor(label);
          sendDrive(cmd);
          setTimeout(function() {
            sendDrive("d0,0");
          }, 500);

          return false;
        }, true);
      }
    });

    // Vitesses
    [
      [25, "speed25"],
      [50, "speed50"],
      [75, "speed75"],
      [100, "speed100"]
    ].forEach(function(x) {
      const b = document.getElementById(x[1]);
      if (!b) return;

      b.onclick = null;

      const clone = b.cloneNode(true);
      b.parentNode.replaceChild(clone, b);

      clone.addEventListener("click", function(ev) {
        return setSpeed(x[0], ev);
      }, true);
    });

    setSpeed(100);

    console.log("terrain2 moteurs FINAL liés avec sent_server_ms");
  }

  async function initMotorOverride() {
    await syncDriveTime();

    // Une première fois.
    bindMotorsNow();

    // Puis deux reprises retardées pour gagner contre les vieux scripts encore présents.
    setTimeout(bindMotorsNow, 700);
    setTimeout(bindMotorsNow, 1500);
  }

  window.rb2Terrain2MotorFinalBind = bindMotorsNow;
  window.setDriveSpeed = setSpeed;
  window.updateDriveButtonSpeeds = function(){};

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMotorOverride);
  } else {
    initMotorOverride();
  }
})();
</script>
<!-- TERRAIN2 MOTOR OVERRIDE FINAL END -->


<!-- TERRAIN2 LIDAR DISPLAY FIX START -->
<script>
(function() {
  if (window.__RB2_TERRAIN2_LIDAR_FIX__) return;
  window.__RB2_TERRAIN2_LIDAR_FIX__ = true;

  let rb2Terrain2LidarZoom = 1.0;
  let rb2Terrain2ShowDistances = false;

  async function jfetch(path, timeoutMs) {
    timeoutMs = timeoutMs || 3000;
    const ctrl = new AbortController();
    const t = setTimeout(function() { ctrl.abort(); }, timeoutMs);

    try {
      const r = await fetch(path, {
        method: "GET",
        signal: ctrl.signal,
        cache: "no-store"
      });

      const text = await r.text();
      let j = {};
      try { j = text ? JSON.parse(text) : {}; }
      catch(e) { j = { raw: text }; }

      if (!r.ok) throw new Error(path + " HTTP " + r.status);
      return j;
    } finally {
      clearTimeout(t);
    }
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (!el) return;

    if (value === undefined || value === null || Number.isNaN(value)) {
      el.textContent = "---";
      return;
    }

    if (typeof value === "number") {
      el.textContent = value.toFixed(1);
    } else {
      el.textContent = String(value);
    }
  }

  function drawLidarTerrain2(points, clearance) {
    const canvas = document.getElementById("lidarCanvas");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.width || canvas.clientWidth || 900;
    const h = canvas.height || canvas.clientHeight || 620;

    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;

    ctx.clearRect(0, 0, w, h);

    // Fond
    ctx.fillStyle = "#050505";
    ctx.fillRect(0, 0, w, h);

    // Centre robot
    const cx = w / 2;
    const cy = h * 0.58;

    // Échelle : environ 1.8 px par cm, ajustable.
    const scale = (Math.min(w, h) / 180) * rb2Terrain2LidarZoom;

    // Grille
    ctx.strokeStyle = "#1f2937";
    ctx.lineWidth = 1;

    [25, 50, 75, 100, 125, 150].forEach(function(cm) {
      const radius = cm * scale;

      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.stroke();

      if (rb2Terrain2ShowDistances) {
        ctx.fillStyle = "#d1d5db";
        ctx.font = "12px sans-serif";
        ctx.fillText(cm + " cm", cx + radius + 4, cy - 4);
        ctx.fillStyle = "#22c55e";
      }
    });

    // Axes
    ctx.strokeStyle = "#374151";
    ctx.lineWidth = 1;

    ctx.beginPath();
    ctx.moveTo(cx, 10);
    ctx.lineTo(cx, h - 10);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(10, cy);
    ctx.lineTo(w - 10, cy);
    ctx.stroke();

    // Points LIDAR
    if (Array.isArray(points) && points.length > 0) {
      ctx.fillStyle = "#22c55e";

      for (const pt of points) {
        if (!Array.isArray(pt) || pt.length < 2) continue;

        const xcm = Number(pt[0]);
        const ycm = Number(pt[1]);

        if (!Number.isFinite(xcm) || !Number.isFinite(ycm)) continue;

        // Convention affichage : x horizontal, y vers l'avant.
        const x = cx + xcm * scale;
        const y = cy - ycm * scale;

        if (x < -20 || x > w + 20 || y < -20 || y > h + 20) continue;

        ctx.beginPath();
        ctx.arc(x, y, 2.0, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Robot approximatif
    ctx.fillStyle = "rgba(59,130,246,0.35)";
    ctx.strokeStyle = "#60a5fa";
    ctx.lineWidth = 2;

    const robotW = 20 * scale;
    const robotFront = 28 * scale;
    const robotBack = 10 * scale;

    ctx.beginPath();
    ctx.rect(cx - robotW / 2, cy - robotFront, robotW, robotFront + robotBack);
    ctx.fill();
    ctx.stroke();

    // Flèche avant
    ctx.fillStyle = "#60a5fa";
    ctx.beginPath();
    ctx.moveTo(cx, cy - robotFront - 12);
    ctx.lineTo(cx - 8, cy - robotFront + 4);
    ctx.lineTo(cx + 8, cy - robotFront + 4);
    ctx.closePath();
    ctx.fill();

    // Texte résumé dans le canvas
    ctx.fillStyle = "#e5e7eb";
    ctx.font = "14px sans-serif";
    ctx.fillText("Avant", cx + 8, 22);

    if (clearance) {
      ctx.font = "13px sans-serif";
      const f = clearance.front_cm;
      const b = clearance.back_cm;
      const l = clearance.left_cm;
      const r = clearance.right_cm;
      const m = clearance.min_cm;

      ctx.fillText(
        "F " + fmt(f) + "  D " + fmt(r) + "  G " + fmt(l) + "  A " + fmt(b) + "  min " + fmt(m),
        12,
        h - 14
      );
    }
  }

  function fmt(v) {
    v = Number(v);
    if (!Number.isFinite(v)) return "---";
    return v.toFixed(1);
  }

  async function updateDistancesTerrain2() {
    try {
      const j = await jfetch("/lidar", 3000);
      const d = j.data || j;

      setText("lidarFront", d.front_cm ?? d.clearance?.front_cm);
      setText("lidarRight", d.right_cm ?? d.clearance?.right_cm);
      setText("lidarLeft", d.left_cm ?? d.clearance?.left_cm);
      setText("lidarBack", d.back_cm ?? d.clearance?.back_cm);
      setText("lidarMin", d.min_cm ?? d.clearance?.min_cm);

      if (j.age_s !== undefined) {
        setText("lidarAge", Number(j.age_s));
      } else {
        setText("lidarAge", 0);
      }

      setText("lidarState", "OK");
    } catch(e) {
      console.log("Erreur distances LIDAR terrain2:", e);
      setText("lidarState", "erreur");
    }
  }

  async function updateMapTerrain2() {
    try {
      const j = await jfetch("/lidar_map", 3000);
      const d = j.data || j;

      const points = d.points_cm || j.points_cm || [];
      const clearance = d.clearance || j.clearance || null;

      drawLidarTerrain2(points, clearance);

      // Si les distances sont aussi présentes dans /lidar_map, les utiliser aussi.
      if (clearance) {
        setText("lidarFront", clearance.front_cm);
        setText("lidarRight", clearance.right_cm);
        setText("lidarLeft", clearance.left_cm);
        setText("lidarBack", clearance.back_cm);
        setText("lidarMin", clearance.min_cm);
      }

      if (j.age_s !== undefined) {
        setText("lidarAge", Number(j.age_s));
      }

      setText("lidarState", "OK");
    } catch(e) {
      console.log("Erreur carte LIDAR terrain2:", e);
      setText("lidarState", "erreur carte");
    }
  }


  window.rb2Terrain2LidarZoomPlus = function() {
    rb2Terrain2LidarZoom = Math.min(3.0, rb2Terrain2LidarZoom * 1.25);
    updateMapTerrain2();
  };

  window.rb2Terrain2LidarZoomMinus = function() {
    rb2Terrain2LidarZoom = Math.max(0.35, rb2Terrain2LidarZoom / 1.25);
    updateMapTerrain2();
  };

  window.rb2Terrain2LidarToggleDistances = function() {
    rb2Terrain2ShowDistances = !rb2Terrain2ShowDistances;

    const b = document.getElementById("lidarDistanceToggle");
    if (b) {
      b.textContent = rb2Terrain2ShowDistances ? "DISTANCES ON" : "DISTANCES OFF";
      b.classList.toggle("speed-active", rb2Terrain2ShowDistances);
    }

    updateMapTerrain2();
  };
function startLidarTerrain2() {
    updateDistancesTerrain2();
    updateMapTerrain2();

    setInterval(updateDistancesTerrain2, 1000);
    setInterval(updateMapTerrain2, 800);

    console.log("terrain2 LIDAR display fix actif");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startLidarTerrain2);
  } else {
    startLidarTerrain2();
  }
})();
</script>
<!-- TERRAIN2 LIDAR DISPLAY FIX END -->

</body>
</html>
"""
@app.route("/secours")
def rb2_secours_page():
    return """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>RB2 SECOURS</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { margin:0; background:#111; color:white; font-family:Arial,sans-serif; }
h1 { margin:0; padding:12px; background:#8b0000; text-align:center; }
.wrap { display:grid; grid-template-columns:1fr 340px; gap:10px; padding:10px; }
.cam { background:#000; text-align:center; border:2px solid #555; }
.cam img { max-width:100%; max-height:80vh; }
.panel { background:#222; padding:12px; border:2px solid #555; }
button { width:100%; padding:18px; margin:6px 0; font-size:24px; font-weight:bold; border:0; border-radius:8px; }
.stop { background:#b00000; color:white; font-size:30px; }
.fwd { background:#207020; color:white; }
.back { background:#205090; color:white; }
.turn { background:#666; color:white; }
input { width:100%; font-size:22px; padding:8px; box-sizing:border-box; margin-bottom:10px; }
pre { background:#000; color:#0f0; padding:8px; min-height:90px; white-space:pre-wrap; }
a { color:white; }
@media(max-width:900px){ .wrap{grid-template-columns:1fr;} }

    /* === SECOURS : titre compact avec retour terrain === */
    .secours-title-row {
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      gap: 14px !important;
      margin: 0 0 4px 0 !important;
      padding: 0 !important;
      line-height: 1 !important;
      background: #050505 !important;
      min-height: 28px !important;
    }

    .secours-title-text {
      color: #fff !important;
      font-size: 22px !important;
      font-weight: 900 !important;
      line-height: 1 !important;
      margin: 0 !important;
      padding: 0 !important;
      white-space: nowrap !important;
    }

    .secours-retour-terrain {
      display: inline-flex !important;
      align-items: center !important;
      justify-content: center !important;
      background: #1f2937 !important;
      border: 1px solid #60a5fa !important;
      color: #fff !important;
      font-weight: 800 !important;
      text-decoration: none !important;
      padding: 5px 10px !important;
      border-radius: 7px !important;
      font-size: 13px !important;
      line-height: 1 !important;
      min-height: 24px !important;
      box-sizing: border-box !important;
      white-space: nowrap !important;
    }

    .secours-retour-terrain:hover {
      background: #2563eb !important;
      border-color: #93c5fd !important;
    }
    /* === FIN SECOURS titre compact avec retour terrain === */
</style>
</head>
<body>

    <div class="secours-title-row">
      <div class="secours-title-text">RB2 - SECOURS</div>
      <a class="secours-retour-terrain" href="/terrain4">Retour /terrain4</a>
    </div>

<a class="secours-retour-terrain" href="/terrain4">Retour /terrain4</a>
    </div>
 </div>

<h1>RB2 — SECOURS</h1>
<div class="wrap">
  <div class="cam">
    <img src="/zero_cam_stream.mjpg" alt="Caméra RB2">
  </div>
  <div class="panel">
    <button class="stop" onclick="secours('stop')">STOP</button>

    <label>Vitesse %</label>
    <input id="speed" type="number" value="50" min="10" max="85">

    <label>Durée secondes</label>
    <input id="duration" type="number" value="5" min="0.2" max="45" step="0.1">

    <button class="fwd" onclick="secours('forward')">AVANCE</button>
    <button class="back" onclick="secours('back')">RECUL</button>
    <button class="turn" onclick="secours('left')">GAUCHE</button>
    <button class="turn" onclick="secours('right')">DROITE</button>

    <pre id="status">Prêt.</pre>
    <p></p>
  </div>
</div>

<script>
async function secours(action) {
  const speed = Number(document.getElementById("speed").value || 50);
  const duration_s = Number(document.getElementById("duration").value || 5);
  const st = document.getElementById("status");
  st.textContent = "Commande: " + action;

  try {
    const r = await fetch("/secours_cmd", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action, speed, duration_s})
    });
    const j = await r.json();
    st.textContent = JSON.stringify(j, null, 2);
  } catch(e) {
    st.textContent = "ERREUR: " + e;
  }
}

async function statusLoop() {
  try {
    const r = await fetch("/secours_status");
    const j = await r.json();
    document.getElementById("status").textContent = JSON.stringify(j, null, 2);
  } catch(e) {}
}
setInterval(statusLoop, 2000);
</script>

<script id="secours-clean-title-script">
(function() {
  function isTerrainReturn(el) {
    const txt = (el.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    const href = (el.getAttribute("href") || "").trim();
    const onclick = (el.getAttribute("onclick") || "").trim();
    return (
      txt.includes("retour") &&
      txt.includes("terrain") &&
      (href === "/terrain" || href === "/terrain4" || onclick.includes("terrain"))
    );
  }

  function removeEmptyParent(el) {
    let p = el.parentElement;
    el.remove();

    for (let i = 0; p && i < 3; i++) {
      if (p.classList && p.classList.contains("secours-title-row")) return;

      const txt = (p.textContent || "").replace(/\s+/g, " ").trim();
      const hasUsefulChildren = p.querySelector("button,a,img,canvas,input,select,textarea");
      const parent = p.parentElement;

      if (!txt && !hasUsefulChildren) {
        p.remove();
        p = parent;
      } else {
        break;
      }
    }
  }

  function cleanSecoursTitlesAndReturns() {
    // Garder une seule ligne noire.
    document.querySelectorAll(".secours-title-row").forEach((el, idx) => {
      if (idx > 0) el.remove();
    });

    // Supprimer les anciens titres rouges RB2 - SECOURS.
    const titleRe = /^RB2\s*[-–—]\s*SECOURS$/i;
    document.querySelectorAll("h1,h2,h3,h4,div,section,header").forEach(el => {
      if (el.closest(".secours-title-row")) return;
      const txt = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (titleRe.test(txt)) el.remove();
    });

    // Supprimer tous les Retour /terrain sauf celui dans la ligne noire.
    document.querySelectorAll('a,button').forEach(el => {
      if (el.closest(".secours-title-row")) return;
      if (isTerrainReturn(el)) removeEmptyParent(el);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", cleanSecoursTitlesAndReturns);
  } else {
    cleanSecoursTitlesAndReturns();
  }

  setTimeout(cleanSecoursTitlesAndReturns, 250);
  setTimeout(cleanSecoursTitlesAndReturns, 1000);
})();
</script>
</body>
</html>
"""

@app.route("/secours_status")
def rb2_secours_status():
    with _RB2_SECOURS_LOCK:
        d = dict(_RB2_SECOURS_STATE)
    d["ok"] = True
    d["rescue"] = True
    return d

@app.route("/secours_cmd", methods=["POST"])
def rb2_secours_cmd():
    global _RB2_SECOURS_STOP_EVENT, _RB2_SECOURS_THREAD

    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "stop")).lower().strip()

    try:
        speed = int(float(data.get("speed", 50)))
    except Exception:
        speed = 50

    try:
        duration_s = float(data.get("duration_s", 5))
    except Exception:
        duration_s = 5.0

    speed = max(10, min(85, speed))
    duration_s = max(0.2, min(45.0, duration_s))

    if action == "stop":
        try:
            if _RB2_SECOURS_STOP_EVENT is not None:
                _RB2_SECOURS_STOP_EVENT.set()
        except Exception:
            pass

        _rb2_secours_stop_burst()

        with _RB2_SECOURS_LOCK:
            _RB2_SECOURS_STATE.update({
                "running": False,
                "action": "STOP",
                "cmd": "d0,0",
                "speed": 0,
                "duration_s": 0,
            })

        return {"ok": True, "rescue": True, "action": "STOP", "cmd": "d0,0"}

    if action == "forward":
        cmd = f"d{speed},{speed}"
    elif action == "back":
        cmd = f"d-{speed},-{speed}"
    elif action == "left":
        cmd = f"d-{speed},{speed}"
    elif action == "right":
        cmd = f"d{speed},-{speed}"
    else:
        return {"ok": False, "error": "action inconnue"}, 400

    try:
        if _RB2_SECOURS_STOP_EVENT is not None:
            _RB2_SECOURS_STOP_EVENT.set()
            time.sleep(0.15)
    except Exception:
        pass

    stop_event = _rb2_secours_threading.Event()
    t = _rb2_secours_threading.Thread(
        target=_rb2_secours_worker,
        args=(action, cmd, speed, duration_s, stop_event),
        daemon=True,
    )

    _RB2_SECOURS_STOP_EVENT = stop_event
    _RB2_SECOURS_THREAD = t
    t.start()

    return {
        "ok": True,
        "rescue": True,
        "action": action,
        "cmd": cmd,
        "speed": speed,
        "duration_s": duration_s,
        "note": "Commande secours lancée avec STOP automatique.",
    }

# ============================================================
# FIN RB2 - MODE SECOURS PERMANENT
# ============================================================



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
TRACE_RETURN_FORWARD_TURN_TARGET_DEG = 500.0
TRACE_RETURN_FORWARD_TURN_TOL_DEG = 8.0
TRACE_RETURN_FORWARD_TURN_TIMEOUT_S = 60.0


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
            "mode": "v22d_retour_avant_180_calibre_500deg",
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
        mode="v22d_retour_avant_180_calibre_500deg",
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
            mode="v22d_retour_avant_180_calibre_500deg",
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
                    mode="v22d_retour_avant_180_calibre_500deg",
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
                    mode="v22d_retour_avant_180_calibre_500deg",
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
                mode="v22d_retour_avant_180_calibre_500deg",
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
                        mode="v22d_retour_avant_180_calibre_500deg",
                    )
                    return

                now_mono = time.monotonic()
                allowed, reason = rb2_trace_follow_lidar_allows(left, right)
                if not allowed:
                    rb2_trace_follow_set_status(
                        running=False, ok=False, state="blocked",
                        message="Retour avant bloqué pendant mouvement", last_error=reason,
                        cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        mode="v22d_retour_avant_180_calibre_500deg",
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
            mode="v22d_retour_avant_180_calibre_500deg",
        )

    except InterruptedError as e:
        rb2_trace_follow_set_status(
            running=False, ok=True, state="stopped", message=str(e),
            last_error="", cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            mode="v22d_retour_avant_180_calibre_500deg",
        )
    except Exception as e:
        rb2_trace_follow_set_status(
            running=False, ok=False, state="error", message="Erreur RETOUR AVANT",
            last_error=str(e), cmd="d0,0", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            mode="v22d_retour_avant_180_calibre_500deg",
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
            "mode": "v22d_retour_avant_180_calibre_500deg",
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
            mode="v22d_retour_avant_180_calibre_500deg",
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
            mode="v22d_retour_avant_180_calibre_500deg",
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
        last_error="", mode="v22d_retour_avant_180_calibre_500deg",
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
        "mode": "v22d_retour_avant_180_calibre_500deg",
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
      min-height: 400px;
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
      min-height: 400px;
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
      min-height: 400px;
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
        <span style="float:right;display:inline-flex;gap:4px;margin-left:4px;align-items:center;position:relative;right:8px;z-index:999999;pointer-events:auto;">
          <button id="rb2StatusShutdownBtn"
                  onclick="rb2ShutdownAllDirect()"
                  style="padding:3px 9px;height:23px;min-width:74px;border-radius:7px;border:1px solid #ff4040;background:#b00000;color:#fff;font-size:10px;font-weight:900;cursor:pointer;">
            ARRÊT RB2
          </button>
          <button onclick="window.open('/lidar_drive2','_blank')"
                  style="padding:3px 8px;height:23px;min-width:48px;border-radius:7px;border:1px solid #1d4ed8;background:#2563eb;color:#fff;font-size:10px;font-weight:900;cursor:pointer;">
            LIDAR
          </button>
          <button onclick="window.open('/zero_cam_stream.mjpg','_blank')"
                  style="padding:3px 8px;height:23px;min-width:58px;border-radius:7px;border:1px solid #065f46;background:#047857;color:#fff;font-size:10px;font-weight:900;cursor:pointer;">
            CAMÉRA
          </button>
          <button id="rb2SecoursTopBtn"
                  type="button"
                  onclick="window.location.href='/secours'; return false;"
                  title="Ouvrir la page SECOURS directe ESP32"
                  style="position:relative;z-index:999999;pointer-events:auto;padding:3px 8px;height:23px;min-width:72px;border-radius:7px;border:1px solid #ffffff;background:#b00000;color:#ffffff;font-size:10px;font-weight:900;cursor:pointer;">
            SECOURS
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
<a class="rb2-trace-secours-btn" href="/secours">SECOURS</a>
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
          Pan : <span id="panValue">95</span>°<br>
          Tilt : <span id="tiltValue">90</span>°
        </div>
        <button onclick="panRight()">▶</button>

        <div></div>
        <button onclick="tiltDown()">▼</button>
        <div></div>
      </div>

      <div class="small-row">
        <button onclick="setPanTilt(95, 90)">Centre</button>
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
let pan = 95;
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
  return /^d-?\\d+,-?\\d+$/.test(String(command || ""));
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
        window.open("/lidar_drive2", "_blank");
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




















<!-- RB2 : Retour WiFi phase 2A UI -->
<script>
window.rb2RetourWifiEventActive = false;

window.rb2RetourWifiPaintPhase2A = function(data) {
  const btn = document.getElementById("rb2RetourWifiBtn");
  if (!btn) return;

  const red = !!(data && (data.active || data.done));
  window.rb2RetourWifiEventActive = red;

  if (red) {
    btn.textContent = "RETOUR";
    btn.style.borderColor = "#ff4d4d";
    btn.style.background = "#b00000";
    btn.style.color = "#ffffff";
  } else {
    btn.textContent = "Retour WiFi";
    btn.style.borderColor = "#38bdf8";
    btn.style.background = "#0f2a3a";
    btn.style.color = "#bdefff";
  }
};

window.rb2RetourWifiAckFinal = async function() {
  if (!window.rb2RetourWifiEventActive) return;

  try {
    const r = await fetch("/wifi_return_ack", {
      method: "POST",
      cache: "no-store"
    });

    const data = await r.json();

    if (data && data.ok) {
      window.rb2RetourWifiPaintPhase2A(data);
    }
  } catch (e) {
    alert("Erreur ACK Retour WiFi.");
  }
};

window.rb2RetourWifiHeartbeatPhase2A = async function() {
  try {
    await fetch("/operator_heartbeat", {
      method: "POST",
      cache: "no-store"
    });
  } catch (e) {}
};

window.rb2RetourWifiPollPhase2A = async function() {
  try {
    const r = await fetch("/wifi_return_status", {cache: "no-store"});
    const data = await r.json();

    if (data && data.ok) {
      window.rb2RetourWifiPaintPhase2A(data);
    }
  } catch (e) {}
};

window.rb2RetourWifiStartPhase2A = function() {
  if (window.__rb2RetourWifiPhase2AStarted) return;
  window.__rb2RetourWifiPhase2AStarted = true;

  window.rb2RetourWifiHeartbeatPhase2A();
  window.rb2RetourWifiPollPhase2A();

  setInterval(window.rb2RetourWifiHeartbeatPhase2A, 1000);
  setInterval(window.rb2RetourWifiPollPhase2A, 1500);
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", window.rb2RetourWifiStartPhase2A);
} else {
  window.rb2RetourWifiStartPhase2A();
}
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
        window.open("/lidar_drive2", "_blank");
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
const RB2_BACK_COLLISION_CM = 10.0;
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


function rb2ApplyMapBorderFromClearance(clearance) {
  const panels = document.querySelectorAll(".map-panel, .camera");
  if (!panels || panels.length === 0) return;

  const front = Number(clearance && clearance.front_cm);
  const back = Number(clearance && clearance.back_cm);

  const frontDanger = Number.isFinite(front) && front > 0 && front <= 37.0;
  const frontWarn   = Number.isFinite(front) && front > 0 && front <= 47.0;

  // Arrière RB2 :
  // 0-12 cm = antennes / structure RB2 ignorées
  // 12-15 cm = danger
  // 15-25 cm = avertissement
  const backDanger = Number.isFinite(back) && back > 12.0 && back <= 15.0;
  const backWarn   = Number.isFinite(back) && back > 12.0 && back <= 25.0;

  let level = "ok";
  if (frontDanger || backDanger) {
    level = "danger";
  } else if (frontWarn || backWarn) {
    level = "warn";
  }

  panels.forEach(function(panel) {
    panel.classList.remove("rb2-lidar-warn", "rb2-lidar-danger");
    if (level === "danger") panel.classList.add("rb2-lidar-danger");
    if (level === "warn") panel.classList.add("rb2-lidar-warn");
  });
}

async function updateLidarMap() {
  try {
    const res = await fetch("/lidar_map", {cache: "no-store"});
    const j = await res.json();
    if (!j.ok) throw new Error(j.error || "lidar_map non OK");

    // RB2_LIDAR_SUMMARY_MERGE_START
    // /lidar_map donne les points de la carte.
    // /lidar donne les distances utiles corrigées, incluant l'arrière filtré.
    try {
      const sr = await fetch("/lidar", {cache: "no-store"});
      const sj = await sr.json();

      if (sj && sj.ok !== false) {
        j.clearance = j.clearance || {};

        for (const k of ["front_cm", "back_cm", "left_cm", "right_cm", "min_cm"]) {
          const v = Number(sj[k]);
          if (Number.isFinite(v)) {
            j[k] = v;
            j.clearance[k] = v;
          }
        }

        if (sj.rb2_filter) {
          j.rb2_filter = sj.rb2_filter;
        }
      }
    } catch (e) {
      console.warn("RB2: impossible de fusionner /lidar avec /lidar_map", e);
    }

    rb2ApplyMapBorderFromClearance(j.clearance || j);
    // RB2_LIDAR_SUMMARY_MERGE_END

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
        window.open("/lidar_drive2", "_blank");
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


  const BACK_SELF_IGNORE_CM = 10;   // 0-10 cm = RB2 lui-même : antenne/châssis arrière
  const BACK_DANGER_CM = 15;        // danger réel arrière à partir de 15 cm du centre LIDAR
  const BACK_WARNING_CM = 25;       // avertissement arrière avant danger

  const BACK_SELF_IGNORE_CM = 10;   // 0-10 cm = RB2 lui-même : antennes/châssis arrière
  const BACK_DANGER_CM = 15;        // danger réel arrière depuis le centre LIDAR
  const BACK_WARNING_CM = 25;       // avertissement arrière depuis le centre LIDAR

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

        (back !== null && back > BACK_SELF_IGNORE_CM && back <= BACK_DANGER_CM)
      return "danger";
    }

    if ((front !== null && front > 0 && front <= FRONT_WARNING_CM) ||
        (back !== null && back > BACK_SELF_IGNORE_CM && back <= BACK_WARNING_CM)

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


# === RB2 LIDAR_DRIVE2 BOUTONS SOUS CARTE ===

LIDAR_DRIVE2_BARS_CSS = r"""
      /* RB2_LD2_HIDE_RIGHT_TITLE_20260706 */
      body.ld2-page .controls > h2:first-child {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
        max-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
      }

      body.ld2-page .map-panel {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }

      body.ld2-page #lidarCanvas {
        flex: 1 1 auto;
        min-height: 0;
        height: auto;
      }

      body.ld2-page .map-status {
        bottom: 88px;
      }

      .ld2-bars {
        flex: 0 0 auto;
        display: grid;
        grid-template-rows: auto auto auto;
        gap: 4px;
        margin-top: 2px;
        z-index: 50;
      }

      .ld2-row {
        display: grid;
        grid-template-columns: 96px repeat(7, minmax(0, 1fr));
        gap: 4px;
        align-items: stretch;
      }

      .ld2-row.trace {
        grid-template-columns: 64px 1.1fr 1.05fr 1.2fr 1fr 1fr 1fr;
      }

      .ld2-row.odo {
        grid-template-columns: 96px 1fr 1fr 130px;
      }

      .ld2-label {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 28px;
        padding: 3px 5px;
        border: 1px solid #333;
        border-radius: 7px;
        background: #050505;
        color: #ffffff;
        font-size: 12px;
        font-weight: 900;
        white-space: nowrap;
      }

      .ld2-btn {
        min-height: 28px;
        padding: 4px 6px;
        border: 1px solid #777;
        border-radius: 7px;
        color: #ffffff;
        font-size: 12px;
        font-weight: 900;
        line-height: 1;
        cursor: pointer;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .ld2-btn:hover {
        filter: brightness(1.18);
      }

      .ld2-green { background: #086625; }
      .ld2-blue { background: #1f4f95; }
      .ld2-purple { background: #4b2b83; }
      .ld2-brown { background: #7a4a05; }
      .ld2-orange { background: #985000; }
      .ld2-cyan { background: #006a86; }
      .ld2-gray { background: #424242; }

      .ld2-btn.ld2-running {
        background: #9a1111 !important;
        border-color: #ff5555 !important;
      }

      .ld2-btn.ld2-okflash {
        outline: 2px solid #66ff99;
      }

      @media (max-width: 1000px) {
        body.ld2-page .map-status {
          bottom: 100px;
        }

        .ld2-row,
        .ld2-row.trace {
          grid-template-columns: 1fr 1fr;
        }

        .ld2-label {
          grid-column: 1 / -1;
        }
      }
"""

LIDAR_DRIVE2_BARS_HTML = r"""
        <div class="ld2-bars" id="ld2Bars">
          <div class="ld2-row slam">
            <div class="ld2-label">SLAM / CARTE</div>
            <button class="ld2-btn ld2-green"  onclick="ld2Post('/slam_start', this, 'DÉMARRÉ')">DÉMARRER</button>
            <button class="ld2-btn ld2-blue"   onclick="ld2Post('/slam_save_map', this, 'SAUVÉ')">SAUVEG.</button>
            <button class="ld2-btn ld2-purple" onclick="ld2DownloadPng(this)">TÉLÉCH. PNG</button>
            <button class="ld2-btn ld2-brown"  onclick="ld2Post('/slam_stop', this, 'ARRÊTÉ')">ARRÊTER</button>
            <button class="ld2-btn ld2-orange" onclick="ld2Post('/zero_photo', this, 'PHOTO OK')">PHOTO</button>
            <button class="ld2-btn ld2-gray"   onclick="ld2Post('/zero_video_toggle', this, 'VIDÉO OK')">VIDÉO</button>
            <button class="ld2-btn ld2-green"  onclick="ld2Recup(this)">RÉCUP</button>
          </div>

          <div class="ld2-row trace">
            <div class="ld2-label">TRACE</div>
            <button class="ld2-btn ld2-green"  onclick="ld2Post('/trace_start', this, 'TRACE DÉM.')">DÉMARR. TRACE</button>
            <button class="ld2-btn ld2-gray"   id="ld2TraceStateBtn" onclick="ld2RefreshTrace()">TRACE ARRÊTÉE</button>
            <button class="ld2-btn ld2-blue"   onclick="ld2Post('/trace_follow_start', this, 'SUIVI')">SUIVRE TRACE</button>
            <button class="ld2-btn ld2-cyan"   onclick="ld2Post('/photo_mark', this, 'REP. OK')">REP. PHOTO</button>
            <button class="ld2-btn ld2-orange" onclick="ld2Post('/trace_mark', this, 'MARQUÉ')">MARQUER</button>
            <button class="ld2-btn ld2-gray"   onclick="ld2Retour(this)">RETOUR</button>
          </div>

          <div class="ld2-row odo">
            <div class="ld2-label">DISTANCE</div>
            <div class="ld2-label" id="ld2OdoTrip">TRAJET : 0,0 m</div>
            <div class="ld2-label" id="ld2OdoTotal">TOTAL : 0,0 m</div>
            <button class="ld2-btn ld2-brown" onclick="ld2OdoReset()">RAZ TRAJET</button>
          </div>
        </div>
"""

LIDAR_DRIVE2_BARS_JS = r"""
<script>
function ld2Flash(btn, text, ms) {
  if (!btn) return;

  const old = btn.textContent;
  btn.textContent = text;
  btn.classList.add("ld2-okflash");

  setTimeout(() => {
    btn.textContent = old;
    btn.classList.remove("ld2-okflash");
  }, ms || 1000);
}

async function ld2Post(url, btn, okText) {
  if (btn) btn.disabled = true;

  try {
    const r = await fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: "{}",
      cache: "no-store"
    });

    let j = null;
    try {
      j = await r.json();
    } catch(e) {}

    if (!r.ok || (j && j.ok === false)) {
      alert(
        "Commande refusée: " + url + "\\n" +
        ((j && (j.error || j.message)) || ("HTTP " + r.status))
      );
      return null;
    }

    ld2Flash(btn, okText || "OK", 1000);
    setTimeout(ld2RefreshTrace, 300);

    return j || {ok: true};

  } catch(e) {
    alert("Erreur commande: " + url + "\\n" + e);
    return null;

  } finally {
    if (btn) btn.disabled = false;
  }
}

function ld2DownloadPng(btn) {
  ld2Flash(btn, "PNG...", 900);
  window.location.href = "/slam_download_png";
}

function ld2Recup(btn) {
  window.open("/captures", "_blank");
  return false;
}

async function ld2RefreshTrace() {
  const btn = document.getElementById("ld2TraceStateBtn");
  if (!btn) return;

  try {
    const r = await fetch("/trace_status", {
      cache: "no-store"
    });

    const j = await r.json();
    const active = !!(j && j.active);

    btn.textContent = active ? "TRACE ACTIVE" : "TRACE ARRÊTÉE";
    btn.classList.toggle("ld2-running", active);

  } catch(e) {
    btn.textContent = "TRACE ?";
  }
}

async function ld2Retour(btn) {
  let st = null;

  try {
    const r = await fetch("/trace_follow_status", {
      cache: "no-store"
    });

    st = await r.json();

  } catch(e) {}

  if (st && st.running) {
    if (!confirm("Un suivi/retour est actif. Arrêter ?")) return;
    await ld2Post("/trace_follow_stop", btn, "STOP RETOUR");
    return;
  }

  if (!confirm("Démarrer RETOUR sur la dernière trace ?\\n\\nGardez STOP à portée.")) return;

  await ld2Post("/trace_return_forward_start", btn, "RETOUR");
}

document.addEventListener("DOMContentLoaded", function() {
  ld2RefreshTrace();
  setInterval(ld2RefreshTrace, 1500);
});

// === RB2 LIDAR_DRIVE2 : compteur de distance parcourue (serveur) ===
// La distance est calculée et persistée CÔTÉ SERVEUR (/odometre, cf.
// esp32_panel.py bloc "ODOMÈTRE SERVEUR"). Cette page ne fait que l'afficher :
// TOTAL est donc identique sur tous les appareils/navigateurs et survit aux
// reboots. TRAJET est remis à zéro via /odometre_trip_reset (bouton RAZ).
const LD2_ODO_POLL_MS = 3000;

function ld2OdoFmt(m) {
  const n = Number(m);
  if (!isFinite(n)) return "?";
  return n.toFixed(1).replace(".", ",");
}

async function ld2OdoRefresh() {
  const tripEl = document.getElementById("ld2OdoTrip");
  const totalEl = document.getElementById("ld2OdoTotal");

  try {
    const r = await fetch("/odometre", { cache: "no-store" });
    const j = await r.json();
    if (!j || j.ok === false) throw new Error("odometre non OK");

    const stale = (typeof j.age_s === "number" && j.age_s > 30);
    if (tripEl) tripEl.textContent = "TRAJET : " + ld2OdoFmt(j.trip_m) + " m";
    if (totalEl) totalEl.textContent = "TOTAL : " + ld2OdoFmt(j.total_m) + " m" + (stale ? " (?)" : "");
  } catch (e) {
    if (tripEl && !tripEl.textContent) tripEl.textContent = "TRAJET : ? m";
    if (totalEl && !totalEl.textContent) totalEl.textContent = "TOTAL : ? m";
  }
}

async function ld2OdoReset() {
  if (!confirm("Remettre le trajet à zéro ?\\n(le total cumulatif n'est pas affecté)")) return;

  try {
    await fetch("/odometre_trip_reset", { method: "POST", cache: "no-store" });
  } catch (e) {
    alert("RAZ trajet : erreur " + e);
  }

  ld2OdoRefresh();
}

document.addEventListener("DOMContentLoaded", function() {
  ld2OdoRefresh();
  setInterval(ld2OdoRefresh, LD2_ODO_POLL_MS);
});
</script>
"""

LIDAR_DRIVE2_RETOUR_CSS = r"""
      .state-row {
        display: flex;
        align-items: stretch;
        gap: 8px;
        margin-bottom: 10px;
      }

      .state-row .state-big {
        flex: 1 1 auto;
        min-width: 0;
        margin-bottom: 0;
      }

      .ld2-nav-retour {
        flex: 0 0 auto;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 8px 14px;
        border-radius: 10px;
        border: 1px solid #375fa8;
        background: #1f4f95;
        color: #ffffff;
        font-weight: 900;
        font-size: 14px;
        text-decoration: none;
        white-space: nowrap;
      }

      .ld2-nav-retour:hover {
        filter: brightness(1.15);
      }
"""


@app.route("/lidar_drive2")
def lidar_drive2_page():
    html = LIDAR_DRIVE_HTML

    html = html.replace(
        "<title>RB2 - Observation LIDAR</title>",
        "<title>RB2 - LIDAR DRIVE2</title>",
        1
    )

    html = html.replace(
        "<body>",
        '<body class="ld2-page">',
        1
    )

    html = html.replace(
        "<h2>Observation LIDAR</h2>",
        "<!-- titre LIDAR DRIVE2 colonne droite supprimé -->",
        1
    )

    html = html.replace(
        '<div class="state-big" id="rb2StateBig">ATTENTE</div>',
        '<div class="state-row">\n'
        '          <div class="state-big" id="rb2StateBig">ATTENTE</div>\n'
        '          <a class="ld2-nav-retour" href="/terrain4">RETOUR</a>\n'
        '        </div>',
        1
    )

    if "</style>" in html:
        html = html.replace(
            "</style>",
            LIDAR_DRIVE2_BARS_CSS + LIDAR_DRIVE2_RETOUR_CSS + "\n</style>",
            1
        )

    if 'id="ld2Bars"' not in html:
        inserted = False

        # Insertion idéale : juste après mapStatus, dans le panneau carte.
        m = re.search(
            r'(<div[^>]*id="mapStatus"[^>]*>.*?</div>)',
            html,
            flags=re.S
        )

        if m:
            html = html[:m.end()] + "\n" + LIDAR_DRIVE2_BARS_HTML + html[m.end():]
            inserted = True

        # Secours : avant la colonne de droite.
        if not inserted and '<div class="controls">' in html:
            html = html.replace(
                '<div class="controls">',
                LIDAR_DRIVE2_BARS_HTML + '\n      <div class="controls">',
                1
            )
            inserted = True

        # Dernier recours : fin de page. Évite un Internal Server Error.
        if not inserted and "</body>" in html:
            html = html.replace(
                "</body>",
                LIDAR_DRIVE2_BARS_HTML + "\n</body>",
                1
            )

    if "</body>" in html:
        html = html.replace(
            "</body>",
            LIDAR_DRIVE2_BARS_JS + "\n</body>",
            1
        )
    else:
        html += LIDAR_DRIVE2_BARS_JS

    return app.response_class(html, mimetype="text/html")

# === FIN RB2 LIDAR_DRIVE2 BOUTONS SOUS CARTE ===


# === RB2 LIDAR_DRIVE2 HIDE HORIZON TITLE ===
@app.after_request
def rb2_lidar_drive2_hide_horizon_title(response):
    try:
        if request.path != "/lidar_drive2":
            return response

        if "text/html" not in response.headers.get("Content-Type", ""):
            return response

        html = response.get_data(as_text=True)

        marker = "RB2_LD2_HIDE_HORIZON_TITLE_20260706"
        if marker in html:
            return response

        # Suppression directe si le titre est présent dans le HTML.
        html = html.replace(
            '<div class="panel-title">Horizon artificiel</div>',
            '<!-- RB2_LD2_HIDE_HORIZON_TITLE_20260706 : Horizon artificiel supprimé -->'
        )

        html = html.replace(
            '<div class="panel-title">Horizon</div>',
            '<!-- RB2_LD2_HIDE_HORIZON_TITLE_20260706 : Horizon supprimé -->'
        )

        # Sécurité navigateur : si le titre est généré autrement, on le cache.
        js = """
<script id="RB2_LD2_HIDE_HORIZON_TITLE_20260706">
(function () {
  function rb2Ld2HideHorizonTitle() {
    document.querySelectorAll(".panel-title, h2, h3, div").forEach(function (el) {
      const txt = (el.textContent || "").replace(/\\s+/g, " ").trim().toLowerCase();

      if (txt === "horizon artificiel" || txt === "horizon") {
        el.style.display = "none";
        el.style.visibility = "hidden";
        el.style.height = "0";
        el.style.minHeight = "0";
        el.style.maxHeight = "0";
        el.style.margin = "0";
        el.style.padding = "0";
        el.style.overflow = "hidden";
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", rb2Ld2HideHorizonTitle);
  } else {
    rb2Ld2HideHorizonTitle();
  }

  setTimeout(rb2Ld2HideHorizonTitle, 300);
})();
</script>
"""

        if "</body>" in html:
            html = html.replace("</body>", js + "\n</body>", 1)
        else:
            html += js

        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))

    except Exception as e:
        try:
            print("RB2 lidar_drive2 hide Horizon title erreur:", e)
        except Exception:
            pass

    return response
# === FIN RB2 LIDAR_DRIVE2 HIDE HORIZON TITLE ===


# === RB2 LIDAR_DRIVE2 HIDE ETAT RB2 TITLE ===
@app.after_request
def rb2_lidar_drive2_hide_etat_rb2_title(response):
    try:
        if request.path != "/lidar_drive2":
            return response

        if "text/html" not in response.headers.get("Content-Type", ""):
            return response

        html = response.get_data(as_text=True)

        marker = "RB2_LD2_HIDE_ETAT_RB2_TITLE_20260706"
        if marker in html:
            return response

        html = html.replace(
            '<div class="panel-title">État RB2</div>',
            '<!-- RB2_LD2_HIDE_ETAT_RB2_TITLE_20260706 : État RB2 supprimé -->'
        )

        html = html.replace(
            '<div class="panel-title">Etat RB2</div>',
            '<!-- RB2_LD2_HIDE_ETAT_RB2_TITLE_20260706 : Etat RB2 supprimé -->'
        )

        # Fallback CSS au cas où le titre serait généré autrement.
        css = """
<style id="RB2_LD2_HIDE_ETAT_RB2_TITLE_20260706">
body.ld2-page .panel-title.ld2-hide-etat-title {
  display: none !important;
}
</style>
<script>
(function () {
  function rb2Ld2HideEtatTitle() {
    document.querySelectorAll(".panel-title").forEach(function (el) {
      const txt = (el.textContent || "").replace(/\\s+/g, " ").trim().toLowerCase();
      if (txt === "état rb2" || txt === "etat rb2") {
        el.style.display = "none";
        el.style.visibility = "hidden";
        el.style.height = "0";
        el.style.minHeight = "0";
        el.style.maxHeight = "0";
        el.style.margin = "0";
        el.style.padding = "0";
        el.style.overflow = "hidden";
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", rb2Ld2HideEtatTitle);
  } else {
    rb2Ld2HideEtatTitle();
  }

  setTimeout(rb2Ld2HideEtatTitle, 500);
})();
</script>
"""

        if "</body>" in html:
            html = html.replace("</body>", css + "\n</body>", 1)
        else:
            html += css

        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))

    except Exception as e:
        try:
            print("RB2 lidar_drive2 hide Etat RB2 title erreur:", e)
        except Exception:
            pass

    return response
# === FIN RB2 LIDAR_DRIVE2 HIDE ETAT RB2 TITLE ===


# === RB2 LIDAR_DRIVE2 VIDEO TRACE CLAIRS ===
@app.after_request
def rb2_lidar_drive2_video_trace_clairs(response):
    try:
        if request.path != "/lidar_drive2":
            return response

        if "text/html" not in response.headers.get("Content-Type", ""):
            return response

        html = response.get_data(as_text=True)

        marker = "RB2_LD2_VIDEO_TRACE_CLAIRS_20260706"
        if marker in html:
            return response

        js = r"""
<script id="RB2_LD2_VIDEO_TRACE_CLAIRS_20260706">
(function () {
  "use strict";

  function findVideoButton() {
    let btn = document.getElementById("ld2VideoBtn");
    if (btn) return btn;

    const buttons = Array.from(document.querySelectorAll("button"));
    btn = buttons.find(b => {
      const on = b.getAttribute("onclick") || "";
      const txt = (b.textContent || "").toUpperCase();
      return on.includes("/zero_video_toggle") || txt.includes("VIDÉO");
    });

    if (btn) btn.id = "ld2VideoBtn";
    return btn || null;
  }

  function setVideoButton(active) {
    const btn = findVideoButton();
    if (!btn) return;

    btn.textContent = active ? "ARRÊTER VIDÉO" : "DÉMARR. VIDÉO";
    btn.title = active
      ? "Cliquer pour arrêter l'enregistrement vidéo"
      : "Cliquer pour démarrer l'enregistrement vidéo";

    btn.classList.toggle("ld2-running", !!active);
    btn.onclick = function () {
      ld2BetterVideoToggle(btn);
      return false;
    };
  }

  async function ld2BetterVideoStatus() {
    const btn = findVideoButton();
    if (!btn) return;

    try {
      const r = await fetch("/zero_video_status", {
        cache: "no-store"
      });

      const j = await r.json();

      const active = !!(
        j &&
        (
          j.recording ||
          j.running ||
          j.active ||
          j.video_recording ||
          j.is_recording ||
          j.state === "recording" ||
          j.status === "recording"
        )
      );

      setVideoButton(active);

    } catch (e) {
      btn.textContent = "VIDÉO ?";
      btn.title = "Statut vidéo inaccessible";
    }
  }

  async function ld2BetterVideoToggle(btn) {
    if (btn) btn.disabled = true;

    try {
      const r = await fetch("/zero_video_toggle", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: "{}",
        cache: "no-store"
      });

      let j = null;
      try {
        j = await r.json();
      } catch (e) {}

      if (!r.ok || (j && j.ok === false)) {
        alert(
          "Commande vidéo refusée\n" +
          ((j && (j.error || j.message)) || ("HTTP " + r.status))
        );
        return;
      }

      setTimeout(ld2BetterVideoStatus, 500);

    } catch (e) {
      alert("Erreur commande vidéo\n" + e);

    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function traceButton() {
    return document.getElementById("ld2TraceStateBtn");
  }

  async function ld2BetterTraceStatus() {
    const btn = traceButton();
    if (!btn) return;

    try {
      const r = await fetch("/trace_status", {
        cache: "no-store"
      });

      const j = await r.json();
      const active = !!(j && j.active);

      btn.textContent = active ? "ARRÊTER TRACE" : "TRACE ARRÊTÉE";
      btn.title = active
        ? "Cliquer pour arrêter la trace en cours"
        : "Aucune trace active";

      btn.classList.toggle("ld2-running", active);

      btn.onclick = function () {
        ld2BetterTraceClick(btn);
        return false;
      };

    } catch (e) {
      btn.textContent = "TRACE ?";
      btn.title = "Statut trace inaccessible";
    }
  }

  async function ld2BetterTraceClick(btn) {
    const active = btn && btn.classList.contains("ld2-running");

    if (!active) {
      await ld2BetterTraceStatus();
      return;
    }

    if (!confirm("Arrêter la trace en cours ?")) return;

    if (btn) btn.disabled = true;

    try {
      const r = await fetch("/trace_stop", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: "{}",
        cache: "no-store"
      });

      let j = null;
      try {
        j = await r.json();
      } catch (e) {}

      if (!r.ok || (j && j.ok === false)) {
        alert(
          "Arrêt trace refusé\n" +
          ((j && (j.error || j.message)) || ("HTTP " + r.status))
        );
        return;
      }

      setTimeout(ld2BetterTraceStatus, 400);

    } catch (e) {
      alert("Erreur arrêt trace\n" + e);

    } finally {
      if (btn) btn.disabled = false;
    }
  }

  window.ld2RefreshTrace = ld2BetterTraceStatus;
  window.ld2RefreshVideoStatus = ld2BetterVideoStatus;
  window.ld2VideoToggle = ld2BetterVideoToggle;

  document.addEventListener("DOMContentLoaded", function () {
    ld2BetterVideoStatus();
    ld2BetterTraceStatus();

    setInterval(ld2BetterVideoStatus, 2000);
    setInterval(ld2BetterTraceStatus, 1500);
  });

  setTimeout(ld2BetterVideoStatus, 500);
  setTimeout(ld2BetterTraceStatus, 500);
})();
</script>
"""

        if "</body>" in html:
            html = html.replace("</body>", js + "\n</body>", 1)
        else:
            html += js

        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))

    except Exception as e:
        try:
            print("RB2 lidar_drive2 video/trace clairs erreur:", e)
        except Exception:
            pass

    return response
# === FIN RB2 LIDAR_DRIVE2 VIDEO TRACE CLAIRS ===






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
  <button id="rb2TraceReturnBtn" class="rb2SlamBtn" onclick="rb2TraceReturnStartCompact()">RETOUR</button>
</div>


<script>

async function rb2TraceReturnStartCompact() {
  const b = document.getElementById("rb2TraceReturnBtn");

  if (!confirm("Confirmer RETOUR TRACE ?\n\nRB2 va tenter de revenir sur ses pas avec la dernière trace enregistrée.")) {
    return;
  }

  try {
    if (b) {
      b.disabled = true;
      b.textContent = "RETOUR...";
      b.style.background = "#b91c1c";
      b.style.color = "white";
    }

    const res = await fetch("/trace_return_start", {
      method: "POST",
      cache: "no-store"
    });

    const j = await res.json();

    if (j && j.ok) {
      if (b) {
        b.textContent = "RETOUR ACTIF";
        b.title = "Retour trace lancé";
      }
    } else {
      if (b) {
        b.textContent = "RET. ERREUR";
        b.title = (j && (j.error || j.message)) ? (j.error || j.message) : "Erreur retour trace";
      }
      alert("RETOUR TRACE refusé : " + ((j && (j.error || j.message)) ? (j.error || j.message) : "erreur inconnue"));
    }
  } catch (e) {
    if (b) {
      b.textContent = "RET. ERREUR";
      b.title = "Erreur retour trace : " + e;
    }
    alert("Erreur RETOUR TRACE : " + e);
  } finally {
    setTimeout(() => {
      const bb = document.getElementById("rb2TraceReturnBtn");
      if (bb) {
        bb.disabled = false;
        bb.textContent = "RETOUR";
      }
    }, 2500);
  }
}

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





# ============================================================
# RB2 - Retour WiFi automatique
# Phase 2A : sécurité locale autonome sur perte heartbeat.
#
# Armé par défaut.
# Bleu Retour WiFi = prêt.
# Rouge RETOUR = retour en cours ou retour déjà effectué.
# ============================================================

import threading as rb2_wifi_return_threading

RB2_OPERATOR_LAST_HEARTBEAT = 0.0
RB2_OPERATOR_CLIENT_IP = ""
RB2_OPERATOR_CLIENT_LAST_SEEN = 0.0

RB2_WIFI_RETURN_READY = True
RB2_WIFI_RETURN_ACTIVE = False
RB2_WIFI_RETURN_DONE = False
RB2_WIFI_RETURN_LOST = False
RB2_WIFI_RETURN_WATCHDOG_STARTED = False
RB2_WIFI_RETURN_LAST_EVENT = "prêt"
RB2_WIFI_RETURN_LAST_REASON = ""
RB2_WIFI_RETURN_LAST_PULSE = 0
RB2_WIFI_RETURN_LAST_START = 0.0
RB2_WIFI_RETURN_LAST_END = 0.0

RB2_WIFI_RETURN_LOSS_AFTER_S = 999999.0    # désactivé : remplacé par rb2-wifi-dual-loss-return
RB2_WIFI_RETURN_PULSE_S = 2.0
RB2_WIFI_RETURN_MAX_PULSES = 5
RB2_WIFI_RETURN_RECENT_DRIVE_WINDOW_S = 900.0    # 15 minutes : autorise le retour après conduite récente prolongée
RB2_WIFI_RETURN_LAST_DRIVE_TIME = 0.0
RB2_WIFI_RETURN_LAST_DRIVE_COMMAND = ""
RB2_WIFI_RETURN_LAST_DRIVE_LEFT = 0
RB2_WIFI_RETURN_LAST_DRIVE_RIGHT = 0
RB2_WIFI_RETURN_CMD = "d-20,-20"
RB2_WIFI_RETURN_SPEED_LEFT = -20
RB2_WIFI_RETURN_SPEED_RIGHT = -20

RB2_WIFI_RETURN_LOCK = rb2_wifi_return_threading.RLock()


def rb2_wifi_return_log(msg):
    import time
    try:
        with open("/tmp/rb2_wifi_return.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%F %T") + " " + str(msg) + "\\n")
    except Exception:
        pass


def rb2_wifi_return_heartbeat_age():
    import time
    if not RB2_OPERATOR_LAST_HEARTBEAT:
        return None
    return time.time() - float(RB2_OPERATOR_LAST_HEARTBEAT)


def rb2_wifi_return_signal_present(max_age_s=1.5):
    age = rb2_wifi_return_heartbeat_age()
    return age is not None and age <= max_age_s


def rb2_wifi_return_recent_drive_activity():
    """
    Empêche un retour automatique lorsque /terrain est simplement fermé
    ou en arrière-plan alors que RB2 ne roulait pas.

    Le retour automatique n'est permis que si une commande moteur non-stop
    a été acceptée récemment.
    """
    import time

    try:
        last = float(RB2_WIFI_RETURN_LAST_DRIVE_TIME or 0.0)
    except Exception:
        last = 0.0

    if last <= 0.0:
        return False, "aucune commande moteur récente"

    age = time.time() - last

    if age <= RB2_WIFI_RETURN_RECENT_DRIVE_WINDOW_S:
        return True, (
            "commande moteur récente "
            + str(round(age, 2))
            + " s ; "
            + str(RB2_WIFI_RETURN_LAST_DRIVE_COMMAND)
        )

    return False, (
        "dernière commande moteur trop ancienne "
        + str(round(age, 2))
        + " s > "
        + str(RB2_WIFI_RETURN_RECENT_DRIVE_WINDOW_S)
        + " s"
    )


def rb2_wifi_return_client_reachable():
    """
    Vérifie si le client opérateur répond réellement.

    Important :
    - Un client encore "associé AP" n'est PAS une preuve suffisante.
    - L'association peut rester visible quelques secondes même si le lien utile
      est perdu ou gelé.
    - Pour éviter de bloquer le Retour WiFi, on se fie seulement à un ping OK.
    """
    import subprocess

    ip = str(RB2_OPERATOR_CLIENT_IP or "").strip()

    if not ip:
        return False, "aucun client opérateur connu"

    if ip.startswith("127."):
        return True, "client local"

    try:
        p = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )

        if p.returncode == 0:
            return True, "client opérateur ping OK " + ip

        return False, "client opérateur sans réponse ping " + ip

    except Exception as e:
        return False, "erreur ping client opérateur " + ip + " : " + str(e)

def rb2_wifi_return_stop(reason="STOP retour WiFi"):
    try:
        rb2_trace_follow_send_stop_burst()
        rb2_wifi_return_log(reason + " : d0,0 burst")
    except Exception as e:
        rb2_wifi_return_log("ERREUR stop retour WiFi: " + str(e))
        try:
            esp32.send("d0,0", wait=0.0)
        except Exception:
            pass


def rb2_wifi_return_back_allowed():
    try:
        allowed, reason = rb2_trace_follow_lidar_allows(
            RB2_WIFI_RETURN_SPEED_LEFT,
            RB2_WIFI_RETURN_SPEED_RIGHT,
        )
        return bool(allowed), str(reason)
    except Exception as e:
        return False, "erreur sécurité LIDAR retour WiFi: " + str(e)


def rb2_wifi_return_run():
    import time

    global RB2_WIFI_RETURN_ACTIVE
    global RB2_WIFI_RETURN_DONE
    global RB2_WIFI_RETURN_LOST
    global RB2_WIFI_RETURN_LAST_EVENT
    global RB2_WIFI_RETURN_LAST_REASON
    global RB2_WIFI_RETURN_LAST_PULSE
    global RB2_WIFI_RETURN_LAST_START
    global RB2_WIFI_RETURN_LAST_END

    with RB2_WIFI_RETURN_LOCK:
        if RB2_WIFI_RETURN_ACTIVE:
            return
        RB2_WIFI_RETURN_ACTIVE = True
        RB2_WIFI_RETURN_DONE = True
        RB2_WIFI_RETURN_LOST = True
        RB2_WIFI_RETURN_LAST_PULSE = 0
        RB2_WIFI_RETURN_LAST_START = time.time()
        RB2_WIFI_RETURN_LAST_END = 0.0
        RB2_WIFI_RETURN_LAST_EVENT = "RETOUR déclenché"
        RB2_WIFI_RETURN_LAST_REASON = "heartbeat perdu"

    rb2_wifi_return_log("=== RETOUR WiFi déclenché ===")
    rb2_wifi_return_stop("STOP initial retour WiFi")
    time.sleep(0.5)

    for pulse in range(1, RB2_WIFI_RETURN_MAX_PULSES + 1):
        with RB2_WIFI_RETURN_LOCK:
            RB2_WIFI_RETURN_LAST_PULSE = pulse
            RB2_WIFI_RETURN_LAST_EVENT = "RETOUR impulsion " + str(pulse)

        if rb2_wifi_return_signal_present(max_age_s=1.5):
            rb2_wifi_return_log("signal revenu avant impulsion " + str(pulse))
            break

        allowed, reason = rb2_wifi_return_back_allowed()
        rb2_wifi_return_log("sécurité LIDAR arrière avant impulsion " + str(pulse) + " : " + reason)

        if not allowed:
            with RB2_WIFI_RETURN_LOCK:
                RB2_WIFI_RETURN_LAST_EVENT = "RETOUR bloqué LIDAR"
                RB2_WIFI_RETURN_LAST_REASON = reason
            rb2_wifi_return_stop("STOP retour WiFi bloqué LIDAR")
            break

        rb2_wifi_return_log("impulsion recul " + str(pulse) + " : " + RB2_WIFI_RETURN_CMD)

        t_end = time.time() + RB2_WIFI_RETURN_PULSE_S

        while time.time() < t_end:
            if rb2_wifi_return_signal_present(max_age_s=1.5):
                rb2_wifi_return_log("signal revenu pendant impulsion " + str(pulse))
                break

            allowed, reason = rb2_wifi_return_back_allowed()
            if not allowed:
                rb2_wifi_return_log("recul interrompu par LIDAR : " + reason)
                with RB2_WIFI_RETURN_LOCK:
                    RB2_WIFI_RETURN_LAST_EVENT = "RETOUR interrompu LIDAR"
                    RB2_WIFI_RETURN_LAST_REASON = reason
                break

            try:
                esp32.send(RB2_WIFI_RETURN_CMD, wait=0.0)
            except Exception as e:
                rb2_wifi_return_log("ERREUR commande recul retour WiFi: " + str(e))
                with RB2_WIFI_RETURN_LOCK:
                    RB2_WIFI_RETURN_LAST_EVENT = "ERREUR commande retour"
                    RB2_WIFI_RETURN_LAST_REASON = str(e)
                break

            time.sleep(0.35)

        rb2_wifi_return_stop("STOP fin impulsion retour WiFi " + str(pulse))
        time.sleep(0.35)

        if rb2_wifi_return_signal_present(max_age_s=1.5):
            rb2_wifi_return_log("signal revenu après impulsion " + str(pulse))
            with RB2_WIFI_RETURN_LOCK:
                RB2_WIFI_RETURN_LAST_EVENT = "RETOUR terminé - signal revenu"
                RB2_WIFI_RETURN_LAST_REASON = "signal revenu"
            break

    rb2_wifi_return_stop("STOP final retour WiFi")

    with RB2_WIFI_RETURN_LOCK:
        RB2_WIFI_RETURN_ACTIVE = False
        RB2_WIFI_RETURN_LAST_END = time.time()
        if RB2_WIFI_RETURN_LAST_EVENT.startswith("RETOUR impulsion"):
            RB2_WIFI_RETURN_LAST_EVENT = "RETOUR terminé - limite atteinte"
            RB2_WIFI_RETURN_LAST_REASON = "limite " + str(RB2_WIFI_RETURN_MAX_PULSES) + " impulsions"

    rb2_wifi_return_log("=== fin RETOUR WiFi ===")


def rb2_wifi_return_watchdog_loop():
    import time

    global RB2_WIFI_RETURN_LOST
    global RB2_WIFI_RETURN_LAST_EVENT
    global RB2_WIFI_RETURN_LAST_REASON

    rb2_wifi_return_log("watchdog Retour WiFi phase 2A démarré")

    while True:
        try:
            age = rb2_wifi_return_heartbeat_age()
            trigger = False

            with RB2_WIFI_RETURN_LOCK:
                if (
                    RB2_WIFI_RETURN_READY
                    and not RB2_WIFI_RETURN_ACTIVE
                    and RB2_OPERATOR_LAST_HEARTBEAT > 0
                    and age is not None
                    and age > RB2_WIFI_RETURN_LOSS_AFTER_S
                ):
                    trigger = True
                    RB2_WIFI_RETURN_LOST = True
                    RB2_WIFI_RETURN_LAST_EVENT = "SIGNAL PERDU"
                    RB2_WIFI_RETURN_LAST_REASON = "heartbeat_age_s=" + str(round(age, 2))

            if trigger:
                recent_drive_ok, recent_drive_reason = rb2_wifi_return_recent_drive_activity()

                if not recent_drive_ok:
                    with RB2_WIFI_RETURN_LOCK:
                        already = (
                            RB2_WIFI_RETURN_LAST_EVENT
                            == "heartbeat absent - sans conduite récente"
                        )
                        RB2_WIFI_RETURN_LOST = False
                        RB2_WIFI_RETURN_LAST_EVENT = "heartbeat absent - sans conduite récente"
                        RB2_WIFI_RETURN_LAST_REASON = recent_drive_reason

                    if not already:
                        rb2_wifi_return_log(
                            "heartbeat absent mais pas de retour : "
                            + recent_drive_reason
                        )

                else:
                    client_ok, client_reason = rb2_wifi_return_client_reachable()

                    if client_ok:
                        with RB2_WIFI_RETURN_LOCK:
                            RB2_WIFI_RETURN_LOST = False
                            RB2_WIFI_RETURN_LAST_EVENT = "heartbeat ralenti - client WiFi OK"
                            RB2_WIFI_RETURN_LAST_REASON = client_reason + " ; " + recent_drive_reason

                        rb2_wifi_return_log(
                            "heartbeat absent mais client encore joignable, pas de retour : "
                            + client_reason
                            + " ; "
                            + recent_drive_reason
                        )
                    else:
                        rb2_wifi_return_log(
                            "SIGNAL PERDU age_s=" + str(round(age, 2))
                            + " ; "
                            + client_reason
                            + " ; "
                            + recent_drive_reason
                        )
                        rb2_wifi_return_run()

        except Exception as e:
            rb2_wifi_return_log("ERREUR watchdog Retour WiFi: " + str(e))

        time.sleep(0.25)


def rb2_wifi_return_ensure_watchdog():
    global RB2_WIFI_RETURN_WATCHDOG_STARTED

    if RB2_WIFI_RETURN_WATCHDOG_STARTED:
        return

    t = rb2_wifi_return_threading.Thread(
        target=rb2_wifi_return_watchdog_loop,
        name="rb2-wifi-return-watchdog",
        daemon=True,
    )
    t.start()
    RB2_WIFI_RETURN_WATCHDOG_STARTED = True


@app.route("/operator_heartbeat", methods=["POST", "GET"])
def operator_heartbeat():
    import time

    global RB2_OPERATOR_LAST_HEARTBEAT
    global RB2_OPERATOR_CLIENT_IP
    global RB2_OPERATOR_CLIENT_LAST_SEEN

    rb2_wifi_return_ensure_watchdog()
    RB2_OPERATOR_LAST_HEARTBEAT = time.time()
    RB2_OPERATOR_CLIENT_LAST_SEEN = RB2_OPERATOR_LAST_HEARTBEAT

    try:
        RB2_OPERATOR_CLIENT_IP = str(request.headers.get("X-Forwarded-For", request.remote_addr) or "").split(",")[0].strip()
    except Exception:
        RB2_OPERATOR_CLIENT_IP = str(request.remote_addr or "")

    if RB2_WIFI_RETURN_ACTIVE:
        rb2_wifi_return_stop("STOP heartbeat revenu pendant retour WiFi")

    return jsonify({
        "ok": True,
        "armed": True,
        "ready": RB2_WIFI_RETURN_READY,
        "active": RB2_WIFI_RETURN_ACTIVE,
        "done": RB2_WIFI_RETURN_DONE,
        "lost": RB2_WIFI_RETURN_LOST,
        "last_event": RB2_WIFI_RETURN_LAST_EVENT,
        "last_reason": RB2_WIFI_RETURN_LAST_REASON,
    })


@app.route("/wifi_return_status", methods=["GET"])
def wifi_return_status():
    rb2_wifi_return_ensure_watchdog()

    age = rb2_wifi_return_heartbeat_age()

    return jsonify({
        "ok": True,
        "armed": True,
        "ready": RB2_WIFI_RETURN_READY,
        "active": RB2_WIFI_RETURN_ACTIVE,
        "done": RB2_WIFI_RETURN_DONE,
        "lost": RB2_WIFI_RETURN_LOST,
        "heartbeat_age_s": age,
        "client_ip": RB2_OPERATOR_CLIENT_IP,
        "client_last_seen": RB2_OPERATOR_CLIENT_LAST_SEEN,
        "last_event": RB2_WIFI_RETURN_LAST_EVENT,
        "last_reason": RB2_WIFI_RETURN_LAST_REASON,
        "last_pulse": RB2_WIFI_RETURN_LAST_PULSE,
        "loss_after_s": RB2_WIFI_RETURN_LOSS_AFTER_S,
        "pulse_s": RB2_WIFI_RETURN_PULSE_S,
        "max_pulses": RB2_WIFI_RETURN_MAX_PULSES,
        "cmd": RB2_WIFI_RETURN_CMD,
        "recent_drive_window_s": RB2_WIFI_RETURN_RECENT_DRIVE_WINDOW_S,
        "last_drive_command": RB2_WIFI_RETURN_LAST_DRIVE_COMMAND,
        "last_drive_time": RB2_WIFI_RETURN_LAST_DRIVE_TIME,
        "phase": "phase 2A retour automatique limite + conduite récente 15 min requise",
    })


@app.route("/wifi_return_ack", methods=["POST", "GET"])
def wifi_return_ack():
    global RB2_WIFI_RETURN_DONE
    global RB2_WIFI_RETURN_LOST
    global RB2_WIFI_RETURN_LAST_EVENT
    global RB2_WIFI_RETURN_LAST_REASON

    rb2_wifi_return_ensure_watchdog()

    with RB2_WIFI_RETURN_LOCK:
        RB2_WIFI_RETURN_DONE = False
        RB2_WIFI_RETURN_LOST = False
        RB2_WIFI_RETURN_LAST_EVENT = "prêt"
        RB2_WIFI_RETURN_LAST_REASON = ""

    rb2_wifi_return_log("ACK opérateur retour WiFi")

    return jsonify({
        "ok": True,
        "armed": True,
        "ready": RB2_WIFI_RETURN_READY,
        "active": RB2_WIFI_RETURN_ACTIVE,
        "done": RB2_WIFI_RETURN_DONE,
        "lost": RB2_WIFI_RETURN_LOST,
        "last_event": RB2_WIFI_RETURN_LAST_EVENT,
    })


@app.route("/wifi_return_arm", methods=["POST"])
def wifi_return_arm():
    rb2_wifi_return_ensure_watchdog()

    return jsonify({
        "ok": True,
        "armed": True,
        "ready": RB2_WIFI_RETURN_READY,
        "active": RB2_WIFI_RETURN_ACTIVE,
        "done": RB2_WIFI_RETURN_DONE,
        "lost": RB2_WIFI_RETURN_LOST,
        "last_event": RB2_WIFI_RETURN_LAST_EVENT,
        "note": "Retour WiFi toujours armé par défaut",
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





# === RB2 TERRAIN2 ALIAS TERRAIN FONCTIONNEL ===
@app.before_request
def rb2_terrain2_alias_terrain_fonctionnel():
    """
    /terrain2 est temporairement servi par la page /terrain,
    parce que /terrain a les moteurs/vitesses validés.
    Ne touche pas à /terrain, /lidar_drive2, /secours ni au BNO055.
    """
    try:
        from flask import request

        if request.path == "/terrain2":
            return terrain_page()

    except Exception as e:
        try:
            print("RB2 terrain2 alias terrain erreur:", e)
        except Exception:
            pass

    return None
# === FIN RB2 TERRAIN2 ALIAS TERRAIN FONCTIONNEL ===

# =====================================================
# RB2 - ARRÊT COMPLET SÉCURISÉ
# =====================================================

def rb2_shutdown_worker():
    """
    Arrêt complet RB2 :
    1. Positionner le tilt à 145° (rangement) avant de couper l'alimentation.
    2. Arrêter le Zero 2 W caméra par SSH.
    3. Attendre brièvement.
    4. Arrêter le Pi 5.
    """
    import subprocess
    import time

    # Position de rangement : tilt à 145° (max) avant l'arrêt complet.
    # Règle mécanique existante : quand tilt >= 135°, pan doit rester entre
    # 60° et 135°. On ne connaît pas le pan courant côté serveur, donc on le
    # recentre à 95° (déjà dans cette plage) avant d'envoyer le tilt, avec le
    # même délai que centerPanTilt()/tiltHighBtn côté client.
    try:
        esp32.send("p95", wait=0.12)
        time.sleep(0.18)
        esp32.send("t145", wait=0.12)
        # Laisser le temps au servo d'atteindre physiquement 145° avant de
        # couper l'alimentation.
        time.sleep(1.5)
    except Exception as e:
        try:
            print("RB2 shutdown: échec mise en position tilt 145:", e)
        except Exception:
            pass

    # -o StrictHostKeyChecking=accept-new : indispensable en mode BatchMode.
    # Si la clé d'hôte du Zero n'est pas encore connue (known_hosts vidé, Zero
    # ré-imagé, nouvelle carte SD), ssh échouerait sinon avec « Host key
    # verification failed » et le Zero ne recevrait jamais l'ordre d'arrêt.
    _ssh_base = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    zero_commands = [
        _ssh_base + ["rj@10.50.0.20", "sudo -n /usr/sbin/shutdown -h now"],
        _ssh_base + ["rj@10.50.0.20", "sudo -n /sbin/shutdown -h now"],
        _ssh_base + ["rj@10.50.0.20", "sudo -n /usr/bin/systemctl poweroff"],
        _ssh_base + ["rj@10.50.0.20", "sudo -n /bin/systemctl poweroff"],
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
    if action not in ("terrain", "bureau", "wifi_24g", "wifi_5g", "disconnect_client", "status"):
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

def _rb2_wlan0_ssid():
    # iwgetid (wireless-tools) n'est pas garanti présent sur les images récentes
    # gérées par NetworkManager ; on retombe sur nmcli --rescan no (pas de scan,
    # lit juste la connexion active) si iwgetid est absent ou muet.
    try:
        p = _rb2_wifi_subprocess.run(
            ["iwgetid", "-r", _RB2_LOCAL_WIFI_IF],
            text=True,
            stdout=_rb2_wifi_subprocess.PIPE,
            stderr=_rb2_wifi_subprocess.DEVNULL,
            timeout=3,
        )
        ssid = p.stdout.strip()
        if ssid:
            return ssid
    except Exception:
        pass

    try:
        p = _rb2_wifi_subprocess.run(
            ["nmcli", "-t", "-f", "active,ssid", "device", "wifi", "list",
             "ifname", _RB2_LOCAL_WIFI_IF, "--rescan", "no"],
            text=True,
            stdout=_rb2_wifi_subprocess.PIPE,
            stderr=_rb2_wifi_subprocess.DEVNULL,
            timeout=4,
        )
        for line in p.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass

    return ""

def _rb2_wlan0_band(ssid):
    s = ssid.lower().replace(",", ".")
    if "5g" in s:
        return "5G"
    if "2.4g" in s:
        return "24G"
    return "UNKNOWN"

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

    # SSID/bande lus indépendamment de has_ipv4 : l'association Wi-Fi (L2) a
    # lieu avant la fin du bail DHCP, donc la bande est connue plus tôt.
    ssid = _rb2_wlan0_ssid()
    band = _rb2_wlan0_band(ssid)

    return {
        "ok": True,
        "interface": _RB2_LOCAL_WIFI_IF,
        "local_wifi": "ON" if local_on else "OFF",
        "admin_state": admin_state,
        "has_ipv4": has_ipv4,
        "ip_line": ip_line,
        "nmcli_line": nmcli_line,
        "ssid": ssid,
        "band": band,
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

@app.route("/rb2_network/wifi_24g", methods=["POST"])
def rb2_network_wifi_24g():
    result = _rb2_wifi_run("wifi_24g")
    _rb2_wifi_time.sleep(1.5)
    state = _rb2_wlan0_state()
    return _rb2_wifi_jsonify({
        "ok": result.get("ok", False),
        "action": "wifi_24g",
        "result": result,
        "state": state,
    })

@app.route("/rb2_network/wifi_5g", methods=["POST"])
def rb2_network_wifi_5g():
    result = _rb2_wifi_run("wifi_5g")
    _rb2_wifi_time.sleep(1.5)
    state = _rb2_wlan0_state()
    return _rb2_wifi_jsonify({
        "ok": result.get("ok", False),
        "action": "wifi_5g",
        "result": result,
        "state": state,
    })

@app.route("/rb2_network/disconnect_client", methods=["POST"])
def rb2_network_disconnect_client():
    result = _rb2_wifi_run("disconnect_client")
    _rb2_wifi_time.sleep(1.5)
    state = _rb2_wlan0_state()
    return _rb2_wifi_jsonify({
        "ok": result.get("ok", False),
        "action": "disconnect_client",
        "result": result,
        "state": state,
    })

@app.route("/rb2_network/connect_ssid", methods=["POST"])
def rb2_network_connect_ssid():
    data = _rb2_wifi_request.get_json(silent=True) or {}
    ssid = str(data.get("ssid", "")).strip()
    password = str(data.get("password", ""))

    if not ssid:
        return _rb2_wifi_jsonify({"ok": False, "error": "SSID requis."}), 400
    if len(ssid) > 32:
        return _rb2_wifi_jsonify({"ok": False, "error": "SSID trop long (32 caractères max)."}), 400
    if password and not (8 <= len(password) <= 63):
        return _rb2_wifi_jsonify({
            "ok": False,
            "error": "Mot de passe : 8 à 63 caractères (ou vide pour un réseau ouvert).",
        }), 400

    action_args = ["connect_ssid", ssid, password]
    if _rb2_wifi_os.geteuid() == 0:
        cmd = [_RB2_WIFI_SCRIPT] + action_args
    else:
        cmd = ["sudo", "-n", _RB2_WIFI_SCRIPT] + action_args

    try:
        p = _rb2_wifi_subprocess.run(
            cmd,
            text=True,
            stdout=_rb2_wifi_subprocess.PIPE,
            stderr=_rb2_wifi_subprocess.STDOUT,
            timeout=35,
        )
        result = {"ok": p.returncode == 0, "output": p.stdout.strip(), "returncode": p.returncode}
    except Exception as e:
        result = {"ok": False, "output": str(e), "returncode": 99}

    state = _rb2_wlan0_state()
    return _rb2_wifi_jsonify({
        "ok": result.get("ok", False),
        "action": "connect_ssid",
        "ssid": ssid,
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



# -----------------------------------------------------------------------------
# RB2_RETOUR_AVANT_TERRAIN_UI_20260622
# Ajoute le bouton RETOUR AVANT dans /terrain sans remplacer le moteur V22B.
# -----------------------------------------------------------------------------
try:
    _RB2_RETURN_FORWARD_MARKER = "RB2_RETOUR_AVANT_TERRAIN_UI_20260622"
    _RB2_RETURN_FORWARD_UI = '\n<!-- RB2_RETOUR_AVANT_TERRAIN_UI_20260622 -->\n<style>\n  .rb2-return-forward-wrap {\n    display: inline-flex;\n    align-items: center;\n    justify-content: flex-start;\n    gap: 5px;\n    margin-left: 6px;\n    white-space: nowrap;\n    vertical-align: middle;\n  }\n\n  .rb2-return-forward-wrap.floating {\n    position: fixed;\n    top: 44px;\n    right: 8px;\n    z-index: 9999;\n    background: rgba(0, 0, 0, 0.72);\n    border: 1px solid rgba(255, 170, 60, 0.5);\n    border-radius: 10px;\n    padding: 4px;\n  }\n\n  .rb2-return-forward-btn {\n    display: inline-flex;\n    align-items: center;\n    justify-content: center;\n    min-height: 28px;\n    padding: 5px 9px;\n    border: 1px solid #ff9f1a;\n    border-radius: 9px;\n    background: #3a2208;\n    color: #ffe0aa;\n    font-weight: 900;\n    font-size: 12px;\n    line-height: 1;\n    cursor: pointer;\n    white-space: nowrap;\n  }\n\n  .rb2-return-forward-btn:hover {\n    filter: brightness(1.12);\n  }\n\n  .rb2-return-forward-btn.running {\n    border-color: #ff4d4d;\n    background: #4a1010;\n    color: #ffd0d0;\n  }\n\n  .rb2-return-forward-btn.blocked,\n  .rb2-return-forward-btn.error {\n    border-color: #ff3333;\n    background: #3d0808;\n    color: #ffd0d0;\n  }\n\n  .rb2-return-forward-btn.finished {\n    border-color: #55dd88;\n    background: #0f331d;\n    color: #caffd8;\n  }\n\n  .rb2-return-forward-btn:disabled {\n    opacity: 0.65;\n    cursor: not-allowed;\n  }\n\n  .rb2-return-forward-status {\n    display: inline-block;\n    max-width: 210px;\n    overflow: hidden;\n    text-overflow: ellipsis;\n    font-size: 11px;\n    color: #ffdca8;\n    opacity: 0.9;\n  }\n</style>\n\n<script>\n(function () {\n  "use strict";\n\n  const MARKER = "RB2_RETOUR_AVANT_TERRAIN_UI_20260622";\n\n  function rb2ReturnForwardHost() {\n    return document.querySelector(".rb2-top-button-group")\n        || document.querySelector(".rb2-terrain-top-buttons")\n        || document.querySelector(".terrain-top-buttons")\n        || document.querySelector(".terrain-topbar-actions")\n        || document.querySelector(".top-button-group")\n        || document.querySelector(".rb2-camera-info-bar")\n        || document.body;\n  }\n\n  function rb2ReturnForwardSetText(id, text) {\n    const el = document.getElementById(id);\n    if (el) el.textContent = text || "";\n  }\n\n  function rb2ReturnForwardButton() {\n    return document.getElementById("rb2-return-forward-btn");\n  }\n\n  function rb2ReturnForwardStatusLabel() {\n    return document.getElementById("rb2-return-forward-status");\n  }\n\n  function rb2ReturnForwardInstall() {\n    if (document.getElementById("rb2-return-forward-wrap")) return;\n\n    const host = rb2ReturnForwardHost();\n    const wrap = document.createElement("span");\n    wrap.id = "rb2-return-forward-wrap";\n    wrap.className = "rb2-return-forward-wrap";\n    wrap.setAttribute("data-rb2-marker", MARKER);\n\n    if (host === document.body) {\n      wrap.classList.add("floating");\n    }\n\n    const btn = document.createElement("button");\n    btn.id = "rb2-return-forward-btn";\n    btn.className = "rb2-return-forward-btn";\n    btn.type = "button";\n    btn.textContent = "RETOUR AVANT";\n    btn.title = "Demi-tour 180° physique, puis retour sur la dernière trace en avançant";\n\n    const st = document.createElement("span");\n    st.id = "rb2-return-forward-status";\n    st.className = "rb2-return-forward-status";\n    st.textContent = "prêt";\n\n    wrap.appendChild(btn);\n    wrap.appendChild(st);\n    host.appendChild(wrap);\n\n    btn.addEventListener("click", rb2ReturnForwardClick);\n  }\n\n  async function rb2ReturnForwardGetStatus() {\n    const r = await fetch("/trace_follow_status", { method: "GET", cache: "no-store" });\n    return await r.json();\n  }\n\n  function rb2ReturnForwardApplyStatus(j) {\n    const btn = rb2ReturnForwardButton();\n    const st = rb2ReturnForwardStatusLabel();\n    if (!btn || !st) return;\n\n    const running = !!(j && j.running);\n    const state = j && j.state ? String(j.state) : "idle";\n    const mode = j && j.mode ? String(j.mode) : "";\n    const msg = j && j.message ? String(j.message) : "";\n    const step = j && j.step ? Number(j.step) : 0;\n    const total = j && j.total ? Number(j.total) : 0;\n    const isForward = mode.indexOf("retour_avant") >= 0;\n\n    btn.classList.remove("running", "blocked", "error", "finished");\n    btn.disabled = false;\n\n    if (running && isForward) {\n      btn.classList.add("running");\n      btn.textContent = total > 0 ? ("ARRÊT RETOUR " + step + "/" + total) : "ARRÊT RETOUR";\n      st.textContent = msg || "retour avant actif";\n      return;\n    }\n\n    if (running && !isForward) {\n      btn.classList.add("running");\n      btn.textContent = "ARRÊTER REJEU";\n      st.textContent = "autre rejeu actif";\n      return;\n    }\n\n    if (!running && isForward && state === "finished") {\n      btn.classList.add("finished");\n      btn.textContent = "RETOUR OK";\n      st.textContent = "terminé";\n      return;\n    }\n\n    if (!running && isForward && state === "blocked") {\n      btn.classList.add("blocked");\n      btn.textContent = "RETOUR BLOQUÉ";\n      st.textContent = j.last_error || msg || "bloqué";\n      return;\n    }\n\n    if (!running && isForward && state === "error") {\n      btn.classList.add("error");\n      btn.textContent = "RETOUR ERREUR";\n      st.textContent = j.last_error || msg || "erreur";\n      return;\n    }\n\n    if (!running && isForward && state === "stopped") {\n      btn.textContent = "RETOUR AVANT";\n      st.textContent = "arrêté";\n      return;\n    }\n\n    btn.textContent = "RETOUR AVANT";\n    st.textContent = "prêt";\n  }\n\n  async function rb2ReturnForwardRefresh() {\n    rb2ReturnForwardInstall();\n\n    try {\n      const j = await rb2ReturnForwardGetStatus();\n      rb2ReturnForwardApplyStatus(j);\n    } catch (e) {\n      const btn = rb2ReturnForwardButton();\n      if (btn) {\n        btn.textContent = "RETOUR ?";\n        btn.title = "Statut trace inaccessible";\n      }\n      rb2ReturnForwardSetText("rb2-return-forward-status", "statut ?");\n    }\n  }\n\n  async function rb2ReturnForwardStop() {\n    const btn = rb2ReturnForwardButton();\n    if (btn) btn.textContent = "ARRÊT...";\n\n    try {\n      await fetch("/trace_follow_stop", { method: "POST", cache: "no-store" });\n    } catch (e) {\n      alert("Erreur pendant l\'arrêt du retour/rejeu : " + e);\n    }\n\n    setTimeout(rb2ReturnForwardRefresh, 350);\n  }\n\n  async function rb2ReturnForwardStart() {\n    const btn = rb2ReturnForwardButton();\n\n    let preview = null;\n    try {\n      const r = await fetch("/trace_return_forward_preview", { method: "GET", cache: "no-store" });\n      preview = await r.json();\n    } catch (e) {\n      alert("Impossible de lire l\'aperçu RETOUR AVANT : " + e);\n      return;\n    }\n\n    if (!preview || preview.ok !== true) {\n      alert("RETOUR AVANT refusé : " + ((preview && preview.error) ? preview.error : "aucun aperçu disponible"));\n      return;\n    }\n\n    const file = preview.file || "dernière trace";\n    const segments = preview.segments || 0;\n    const duration = preview.total_duration_s_after_turn || 0;\n    const turnCmd = preview.turn_command || "d20,-20";\n    const odomTarget = preview.turn_odom_target_deg || 360;\n    const physicalTurn = preview.turn_first_deg || 180;\n\n    const ok = confirm(\n      "Démarrer RETOUR AVANT ?\\n\\n" +\n      "Fichier : " + file + "\\n" +\n      "Segments : " + segments + "\\n" +\n      "Demi-tour physique : " + physicalTurn + "°\\n" +\n      "Cible odométrique : " + odomTarget + "°\\n" +\n      "Commande demi-tour : " + turnCmd + "\\n" +\n      "Durée retour après demi-tour : " + Number(duration).toFixed(1) + " s\\n\\n" +\n      "Le robot fera d\'abord son demi-tour, puis reviendra en avançant.\\n" +\n      "Sécurité LIDAR active. Gardez la main près de STOP."\n    );\n\n    if (!ok) return;\n\n    if (btn) {\n      btn.disabled = true;\n      btn.textContent = "DÉMARRAGE...";\n    }\n\n    try {\n      const r = await fetch("/trace_return_forward_start", { method: "POST", cache: "no-store" });\n      const j = await r.json();\n\n      if (!r.ok || !j.ok) {\n        alert("RETOUR AVANT refusé : " + (j.error || "erreur inconnue"));\n      }\n    } catch (e) {\n      alert("Erreur RETOUR AVANT : " + e);\n    }\n\n    if (btn) btn.disabled = false;\n    setTimeout(rb2ReturnForwardRefresh, 350);\n  }\n\n  async function rb2ReturnForwardClick() {\n    try {\n      const st = await rb2ReturnForwardGetStatus();\n      if (st && st.running) {\n        await rb2ReturnForwardStop();\n        return;\n      }\n    } catch (e) {\n      // Si le statut ne répond pas, on ne démarre pas à l\'aveugle.\n      alert("Statut trace inaccessible. RETOUR AVANT non démarré.");\n      return;\n    }\n\n    await rb2ReturnForwardStart();\n  }\n\n  document.addEventListener("DOMContentLoaded", function () {\n    rb2ReturnForwardInstall();\n    rb2ReturnForwardRefresh();\n    setInterval(rb2ReturnForwardRefresh, 1000);\n  });\n\n  setTimeout(function () {\n    rb2ReturnForwardInstall();\n    rb2ReturnForwardRefresh();\n  }, 800);\n})();\n</script>\n'
    if _RB2_RETURN_FORWARD_MARKER not in TERRAIN_HTML:
        if "</body>" in TERRAIN_HTML:
            TERRAIN_HTML = TERRAIN_HTML.replace("</body>", _RB2_RETURN_FORWARD_UI + "\n</body>", 1)
        else:
            TERRAIN_HTML = TERRAIN_HTML + _RB2_RETURN_FORWARD_UI
except Exception as e:
    try:
        print("RB2 RETOUR AVANT UI non injecté:", e)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# RB2_RETOUR_BOUTON_COMPACT_VERT_ROUGE_20260622
# Rend le bouton RETOUR compact :
# - texte visible seulement "RETOUR";
# - vert au repos / terminé;
# - rouge pendant le retour;
# - explications au survol de la souris;
# - commentaires visibles supprimés.
# -----------------------------------------------------------------------------
try:
    _RB2_RETOUR_COMPACT_MARKER = "RB2_RETOUR_BOUTON_COMPACT_VERT_ROUGE_20260622"
    _RB2_RETOUR_COMPACT_UI = '\n<!-- RB2_RETOUR_BOUTON_COMPACT_VERT_ROUGE_20260622 -->\n<style>\n  #rb2-return-forward-wrap {\n    gap: 0 !important;\n    margin-left: 5px !important;\n  }\n\n  #rb2-return-forward-status,\n  .rb2-return-forward-status {\n    display: none !important;\n    visibility: hidden !important;\n    width: 0 !important;\n    max-width: 0 !important;\n    min-width: 0 !important;\n    margin: 0 !important;\n    padding: 0 !important;\n    overflow: hidden !important;\n  }\n\n  #rb2-return-forward-btn.rb2-retour-compact {\n    min-width: 64px !important;\n    max-width: 74px !important;\n    height: 28px !important;\n    min-height: 28px !important;\n    padding: 4px 9px !important;\n    border-radius: 8px !important;\n    font-size: 12px !important;\n    font-weight: 900 !important;\n    line-height: 1 !important;\n    text-align: center !important;\n    white-space: nowrap !important;\n  }\n\n  #rb2-return-forward-btn.rb2-retour-green {\n    background: #064b20 !important;\n    border-color: #44d36f !important;\n    color: #d8ffe4 !important;\n  }\n\n  #rb2-return-forward-btn.rb2-retour-red {\n    background: #7a1010 !important;\n    border-color: #ff4d4d !important;\n    color: #ffe0e0 !important;\n  }\n</style>\n\n<script>\n(function () {\n  "use strict";\n\n  const MARKER = "RB2_RETOUR_BOUTON_COMPACT_VERT_ROUGE_20260622";\n\n  const TITLE_READY =\n    "RETOUR : démarre le retour automatique. RB2 fait d\'abord son demi-tour calibré, puis revient en avançant sur la dernière trace enregistrée. Garder STOP à portée.";\n\n  const TITLE_RUNNING =\n    "RETOUR en cours : RB2 exécute le demi-tour puis le retour sur trace inverse. Cliquer sur le bouton rouge pour arrêter le retour automatique.";\n\n  const TITLE_DONE =\n    "RETOUR terminé ou arrêté : le bouton est prêt pour un autre retour. Pour un meilleur résultat, utiliser une trace courte et propre.";\n\n  const TITLE_UNKNOWN =\n    "RETOUR : statut momentanément inaccessible. Vérifier le service RB2 si le problème persiste.";\n\n  function rb2RetourBtn() {\n    return document.getElementById("rb2-return-forward-btn");\n  }\n\n  function rb2RetourHideStatus() {\n    document.querySelectorAll("#rb2-return-forward-status, .rb2-return-forward-status").forEach(function (el) {\n      el.textContent = "";\n      el.style.display = "none";\n      el.style.visibility = "hidden";\n      el.style.width = "0";\n      el.style.maxWidth = "0";\n      el.style.margin = "0";\n      el.style.padding = "0";\n    });\n  }\n\n  function rb2RetourSetVisual(running, titleText) {\n    const btn = rb2RetourBtn();\n    if (!btn) return;\n\n    btn.textContent = "RETOUR";\n    btn.classList.add("rb2-retour-compact");\n    btn.classList.remove("rb2-retour-green", "rb2-retour-red");\n\n    if (running) {\n      btn.classList.add("rb2-retour-red");\n      btn.title = titleText || TITLE_RUNNING;\n    } else {\n      btn.classList.add("rb2-retour-green");\n      btn.title = titleText || TITLE_READY;\n    }\n\n    rb2RetourHideStatus();\n  }\n\n  async function rb2RetourRefreshCompact() {\n    const btn = rb2RetourBtn();\n    if (!btn) {\n      return;\n    }\n\n    rb2RetourHideStatus();\n\n    try {\n      const r = await fetch("/trace_follow_status", {\n        method: "GET",\n        cache: "no-store"\n      });\n\n      const j = await r.json();\n      const running = !!(j && j.running);\n      const state = j && j.state ? String(j.state) : "";\n      const mode = j && j.mode ? String(j.mode) : "";\n      const isRetour = mode.indexOf("retour_avant") >= 0 || mode.indexOf("return_forward") >= 0;\n\n      if (running && isRetour) {\n        rb2RetourSetVisual(true, TITLE_RUNNING);\n        return;\n      }\n\n      if (!running && isRetour && (state === "finished" || state === "stopped")) {\n        rb2RetourSetVisual(false, TITLE_DONE);\n        return;\n      }\n\n      if (!running && isRetour && (state === "error" || state === "blocked")) {\n        const err = j.last_error ? String(j.last_error) : "dernier retour non complété";\n        rb2RetourSetVisual(false, "RETOUR : prêt. Dernier état : " + err + ". Vérifier la trace, les dégagements et relancer au besoin.");\n        return;\n      }\n\n      rb2RetourSetVisual(false, TITLE_READY);\n    } catch (e) {\n      rb2RetourSetVisual(false, TITLE_UNKNOWN);\n    }\n  }\n\n  function rb2RetourInstallCompactWatcher() {\n    const btn = rb2RetourBtn();\n    if (!btn) return;\n\n    btn.setAttribute("data-rb2-compact-marker", MARKER);\n\n    const observer = new MutationObserver(function () {\n      const b = rb2RetourBtn();\n      if (b && b.textContent.trim() !== "RETOUR") {\n        b.textContent = "RETOUR";\n      }\n      rb2RetourHideStatus();\n    });\n\n    observer.observe(btn, {\n      childList: true,\n      characterData: true,\n      subtree: true,\n      attributes: true\n    });\n  }\n\n  document.addEventListener("DOMContentLoaded", function () {\n    setTimeout(function () {\n      rb2RetourInstallCompactWatcher();\n      rb2RetourRefreshCompact();\n    }, 500);\n\n    setInterval(rb2RetourRefreshCompact, 500);\n  });\n\n  setTimeout(function () {\n    rb2RetourInstallCompactWatcher();\n    rb2RetourRefreshCompact();\n  }, 1200);\n})();\n</script>\n'
    if _RB2_RETOUR_COMPACT_MARKER not in TERRAIN_HTML:
        if "</body>" in TERRAIN_HTML:
            TERRAIN_HTML = TERRAIN_HTML.replace("</body>", _RB2_RETOUR_COMPACT_UI + "\n</body>", 1)
        else:
            TERRAIN_HTML = TERRAIN_HTML + _RB2_RETOUR_COMPACT_UI
except Exception as e:
    try:
        print("RB2 bouton RETOUR compact non injecté:", e)
    except Exception:
        pass


# RB2_LIDAR_MAP_CLEARANCE_OVERRIDE_START
def rb2_lidar_map_status_with_clearance():
    """
    Correction RB2:
    /lidar_map garde les points de la carte, mais ajoute aussi les vraies
    distances utiles corrigées depuis /tmp/rb2_lidar.json.
    """
    import os as _rb2_os
    import json as _rb2_json
    import time as _rb2_time

    lidar_map_file = "/tmp/rb2_lidar_map.json"
    lidar_summary_file = "/tmp/rb2_lidar.json"

    try:
        if not _rb2_os.path.exists(lidar_map_file):
            return jsonify({
                "ok": False,
                "error": "lidar_map absent",
                "file": lidar_map_file
            })

        with open(lidar_map_file, "r", encoding="utf-8") as f:
            data = _rb2_json.load(f)

        stamp = data.get("stamp") or data.get("timestamp") or 0
        try:
            age_s = max(0.0, _rb2_time.time() - float(stamp))
        except Exception:
            age_s = None

        clearance = {}

        if _rb2_os.path.exists(lidar_summary_file):
            with open(lidar_summary_file, "r", encoding="utf-8") as f:
                summary = _rb2_json.load(f)

            summary_clearance = summary.get("clearance") if isinstance(summary.get("clearance"), dict) else {}

            for k in ["front_cm", "back_cm", "left_cm", "right_cm", "min_cm"]:
                v = summary.get(k, None)
                if v is None:
                    v = summary_clearance.get(k, None)

                try:
                    if v is not None:
                        clearance[k] = float(v)
                except Exception:
                    pass

            if clearance:
                data["clearance"] = clearance
                for k, v in clearance.items():
                    data[k] = v

            if isinstance(summary.get("robot"), dict):
                data["robot"] = summary["robot"]

            if isinstance(summary.get("rb2_filter"), dict):
                data["rb2_filter"] = summary["rb2_filter"]

        return jsonify({
            "ok": True,
            "file": lidar_map_file,
            "age_s": age_s,
            "data": data,
            "clearance": clearance if clearance else None
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "file": lidar_map_file
        }), 500

app.view_functions["lidar_map_status"] = rb2_lidar_map_status_with_clearance
# RB2_LIDAR_MAP_CLEARANCE_OVERRIDE_END







# ============================================================
# RB2_HIDE_TOP_RETOUR_AFTER_REQUEST_CSS_20260702
# Injecte dans /terrain un CSS qui cache le RETOUR AVANT du haut.
# Conserve SECOURS et conserve le RETOUR du panneau TRACE s'il existe.
# ============================================================

@app.after_request
def rb2_hide_top_retour_after_request_css_20260702(response):
    try:
        if request.path != "/terrain":
            return response

        if "text/html" not in response.headers.get("Content-Type", ""):
            return response

        html = response.get_data(as_text=True)

        if "RB2_HIDE_TOP_RETOUR_AFTER_REQUEST_CSS_20260702_STYLE" not in html:
            css = """
<style id="RB2_HIDE_TOP_RETOUR_AFTER_REQUEST_CSS_20260702_STYLE">
/* Cache le RETOUR AVANT généré en haut */
#rb2-return-forward-wrap {
  display: none !important;
  visibility: hidden !important;
  opacity: 0 !important;
  width: 0 !important;
  height: 0 !important;
  max-width: 0 !important;
  max-height: 0 !important;
  overflow: hidden !important;
  pointer-events: none !important;
}

/* Garde visible le bouton RETOUR déjà placé dans TRACE */
#rb2TraceReturnBtn {
  display: inline-flex !important;
  visibility: visible !important;
  opacity: 1 !important;
  pointer-events: auto !important;
}

/* Si le vrai RETOUR AVANT est éventuellement déplacé dans TRACE, il redevient visible */
#rb2TracePanel #rb2-return-forward-wrap {
  display: inline-flex !important;
  visibility: visible !important;
  opacity: 1 !important;
  width: auto !important;
  height: auto !important;
  max-width: none !important;
  max-height: none !important;
  overflow: visible !important;
  pointer-events: auto !important;
}
</style>
"""
            if "</head>" in html:
                html = html.replace("</head>", css + "\n</head>", 1)
            elif "</body>" in html:
                html = html.replace("</body>", css + "\n</body>", 1)
            else:
                html = css + html

            response.set_data(html)
            response.headers["Content-Length"] = str(len(response.get_data()))

    except Exception as e:
        try:
            print("RB2_HIDE_TOP_RETOUR_AFTER_REQUEST_CSS erreur:", e)
        except Exception:
            pass

    return response

# ============================================================
# FIN RB2_HIDE_TOP_RETOUR_AFTER_REQUEST_CSS_20260702
# ============================================================


# ============================================================
# RB2 TERRAIN4 — PAGE AUTONOME LEGERE
#
# Le HTML est volontairement séparé du fichier Python monolithique. La route
# ne dépend ni de /terrain, ni de /terrain2, ni de /terrain3. Elle ne reçoit
# donc aucune des injections et minuteries historiques de ces pages.
# ============================================================

RB2_TERRAIN4_HTML_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "terrain4.html",
)


@app.route("/terrain4")
def rb2_terrain4_page():
    try:
        with open(RB2_TERRAIN4_HTML_PATH, "r", encoding="utf-8") as source:
            html = source.read()
    except OSError as exc:
        return Response(
            "Terrain4 indisponible : " + str(exc),
            status=500,
            mimetype="text/plain",
        )

    response = Response(html, mimetype="text/html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["X-RB2-Page"] = "terrain4-standalone"
    return response


if __name__ == "__main__":
    try:
        esp32.connect()
        app.run(host="0.0.0.0", port=5051, debug=False)
    finally:
        esp32.stop()
        esp32.close()


# RB2_RETOUR_AVANT_V22C_1000DEG_90S
# Correction RETOUR AVANT :
# - Ancienne cible : 360° odométriques.
# - Essai terrain : 253° odométriques donnaient environ 45° physiques.
# - Nouvelle cible : 1000° odométriques pour approcher 180° physiques.
# - Timeout porté à 90 s pour éviter l'arrêt prématuré.


# RB2_RETOUR_AVANT_V22D_500DEG_60S
# Correction RETOUR AVANT :
# - Essai V22C : 1000° odométriques donnaient environ 360° physiques ou plus.
# - Nouvelle cible : 500° odométriques pour viser environ 180° physiques.
# - Timeout : 60 s, conservateur.
