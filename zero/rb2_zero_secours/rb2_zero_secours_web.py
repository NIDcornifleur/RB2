#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
import html
import json
import subprocess
import urllib.request
import time

# Écoute sur toutes les interfaces du Zero.
# La page reste accessible par http://10.60.0.1:8088
LISTEN_HOST = "0.0.0.0"
PORT = 8088

PI5 = "10.50.0.1"
ZERO = "10.60.0.1"

SSH_BASE = [
    "ssh",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=5",
    f"rj@{PI5}",
]

ACTIONS = {
    "stop": {
        "label": "STOP moteurs",
        "danger": True,
        "kind": "http_stop",
    },

    "status_terrain": {
        "label": "Tester /terrain Pi5",
        "danger": False,
        "kind": "http_get",
        "url": f"http://{PI5}:5051/terrain",
    },

    "restart_panel": {
        "label": "Restart panneau Flask Pi5",
        "danger": False,
        "kind": "ssh",
        "cmd": "sudo -n systemctl restart --no-block rb2-esp32-panel.service && echo 'Restart panneau Flask demandé'",
    },

    "restart_lidar_ros": {
        "label": "Restart LIDAR / ROS bringup",
        "danger": False,
        "kind": "ssh",
        "cmd": "sudo -n systemctl restart --no-block rb2-bringup.service && sudo -n systemctl restart --no-block rb2-lidar-json.service && sudo -n systemctl restart --no-block rb2-lidar-map-json.service && echo 'Restart LIDAR / ROS demandé'",
    },

    "restart_lidar_json": {
        "label": "Restart ponts LIDAR JSON",
        "danger": False,
        "kind": "ssh",
        "cmd": "sudo -n systemctl restart --no-block rb2-lidar-json.service && sudo -n systemctl restart --no-block rb2-lidar-map-json.service && echo 'Restart ponts LIDAR JSON demandé'",
    },

    "restart_wifi_return": {
        "label": "Restart retour Wi-Fi",
        "danger": False,
        "kind": "ssh",
        "cmd": "sudo -n systemctl restart --no-block rb2-wifi-dual-loss-return.service && echo 'Restart retour Wi-Fi demandé'",
    },

    "restart_zero_cam": {
        "label": "Restart caméra Zero",
        "danger": False,
        "kind": "local",
        "cmd": "sudo -n systemctl restart --no-block rb2-zero-cam.service && echo 'Restart caméra Zero demandé'",
    },
}


def run_cmd(cmd, timeout=20):
    try:
        p = subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return p.returncode, (p.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return 998, "Commande expirée"
    except Exception as e:
        return 999, str(e)


def http_stop():
    url = f"http://{PI5}:5051/cmd"
    data = json.dumps({"cmd": "d0,0"}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8", "replace")
            return 0, f"HTTP {r.status} {r.reason}\n{body}"
    except Exception as e:
        return 999, str(e)


def http_get(url):
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            # On lit seulement un petit morceau.
            # Le but est de confirmer que Flask répond, pas de télécharger toute la page.
            r.read(256)
            return 0, f"HTTP {r.status} {r.reason}"
    except Exception as e:
        return 999, str(e)


def run_action(name):
    action = ACTIONS.get(name)

    if not action:
        return 404, f"Action inconnue: {name}"

    kind = action["kind"]

    if kind == "http_stop":
        return http_stop()

    if kind == "http_get":
        return http_get(action["url"])

    if kind == "ssh":
        return run_cmd(SSH_BASE + [action["cmd"]], timeout=25)

    if kind == "local":
        return run_cmd(action["cmd"], timeout=20)

    return 999, f"Type action non géré: {kind}"


def page(last_title="", last_code=None, last_output=""):
    buttons = []

    for name, action in ACTIONS.items():
        cls = "danger" if action.get("danger") else ""

        buttons.append(
            f"""
            <form method="POST" action="/action">
              <input type="hidden" name="name" value="{html.escape(name)}">
              <button class="{cls}" type="submit">{html.escape(action["label"])}</button>
            </form>
            """
        )

    result = ""

    if last_title:
        result = f"""
        <section class="result">
          <h2>Résultat : {html.escape(last_title)}</h2>
          <p><b>Code retour :</b> {html.escape(str(last_code))}</p>
          <pre>{html.escape(last_output)}</pre>
        </section>
        """

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RB2 Secours Zero</title>

<style>
body {{
  font-family: Arial, sans-serif;
  background: #111;
  color: #eee;
  margin: 0;
  padding: 16px;
}}

h1 {{
  margin-top: 0;
  font-size: 28px;
}}

.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}}

button, .biglink {{
  display: block;
  box-sizing: border-box;
  width: 100%;
  min-height: 64px;
  padding: 18px 10px;
  font-size: 18px;
  font-weight: bold;
  text-align: center;
  text-decoration: none;
  border-radius: 10px;
  border: 0;
  background: #2f6fed;
  color: white;
}}

button.danger {{
  background: #b00020;
}}

.biglink.video {{
  background: #0b7a3b;
}}

.biglink.terrain {{
  background: #6b4bc2;
}}

.card, .result {{
  background: #222;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 14px;
}}

a {{
  color: #7db7ff;
}}

pre {{
  white-space: pre-wrap;
  background: #000;
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
}}

.small {{
  color: #bbb;
  font-size: 14px;
}}
</style>
</head>

<body>
<h1>RB2 — Secours Zero 2 W</h1>

<div class="card">
  <p><b>Adresse page secours :</b> http://{ZERO}:{PORT}</p>
  <p><b>Zero secours :</b> {ZERO}</p>
  <p><b>Pi5 RB2 :</b> {PI5}</p>
  <p class="small">Page ouverte de secours. À utiliser seulement en récupération.</p>
</div>

<div class="grid">
  <a class="biglink video" href="http://{ZERO}:8080/stream.mjpg">
    Ouvrir caméra Zero
  </a>

  <a class="biglink terrain" href="http://{PI5}:5051/terrain">
    Ouvrir /terrain Pi5
  </a>
</div>

<br>

<div class="grid">
{''.join(buttons)}
</div>

{result}

<p class="small">Heure Zero : {html.escape(time.strftime("%Y-%m-%d %H:%M:%S"))}</p>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Évite les résultats étranges pour favicon.ico.
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        body = page().encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/action":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        data = parse_qs(raw)
        name = data.get("name", [""])[0]

        action = ACTIONS.get(name, {"label": name})
        code, output = run_action(name)

        body = page(action.get("label", name), code, output).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    server = ThreadingHTTPServer((LISTEN_HOST, PORT), Handler)
    print(f"RB2 Zero secours actif : http://{ZERO}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
