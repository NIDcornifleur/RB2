#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, Response, render_template_string
import cv2
import threading
import time

CAMERA_DEVICE = "/dev/video0"
WIDTH = 640
HEIGHT = 480
FPS = 30

app = Flask(__name__)

lock = threading.Lock()
latest_frame = None
camera_ok = False
last_error = ""


def camera_loop():
    global latest_frame, camera_ok, last_error

    cap = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)

    if not cap.isOpened():
        camera_ok = False
        last_error = f"Impossible d'ouvrir {CAMERA_DEVICE}"
        return

    # Forcer MJPG pour éviter le YUYV lourd
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    time.sleep(0.5)

    camera_ok = True
    last_error = ""

    while True:
        ret, frame = cap.read()

        if not ret or frame is None:
            camera_ok = False
            last_error = "Image non reçue de la caméra"
            time.sleep(0.2)
            continue

        camera_ok = True
        last_error = ""

        ret, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])

        if ret:
            with lock:
                latest_frame = jpeg.tobytes()

        time.sleep(1.0 / FPS)


def generate_mjpeg():
    while True:
        with lock:
            frame = latest_frame

        if frame is None:
            time.sleep(0.1)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
            b"\r\n" + frame + b"\r\n"
        )


@app.route("/")
def index():
    html = """
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>RB2 - Caméra USB</title>
        <style>
            body {
                margin: 0;
                background: #111;
                color: #eee;
                font-family: Arial, sans-serif;
                text-align: center;
            }
            h1 {
                margin: 12px;
                font-size: 24px;
            }
            .info {
                margin-bottom: 10px;
                color: #bbb;
                font-size: 15px;
            }
            img {
                max-width: 98vw;
                max-height: 86vh;
                border: 2px solid #444;
                background: #000;
            }
            a {
                color: #9cf;
            }
        </style>
    </head>
    <body>
        <h1>RB2 - Caméra USB temporaire</h1>
        <div class="info">
            Périphérique : {{ device }} |
            Résolution demandée : {{ width }}x{{ height }} |
            FPS : {{ fps }}
        </div>
        <img src="/stream.mjpg" alt="Flux caméra RB2">
        <div class="info">
            Flux direct : <a href="/stream.mjpg">/stream.mjpg</a> |
            État : <a href="/status">/status</a>
        </div>
    </body>
    </html>
    """
    return render_template_string(
        html,
        device=CAMERA_DEVICE,
        width=WIDTH,
        height=HEIGHT,
        fps=FPS,
    )


@app.route("/stream.mjpg")
def stream():
    return Response(
        generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/status")
def status():
    return {
        "ok": camera_ok,
        "device": CAMERA_DEVICE,
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "last_error": last_error,
    }


if __name__ == "__main__":
    t = threading.Thread(target=camera_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=8082, threaded=True)
