#!/usr/bin/env python3
import json
import os
import serial
import tempfile
import threading
import time


class RB2ESP32:
    def __init__(
        self,
        port="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
        baudrate=115200,
    ):
        self.port = port
        self.baudrate = baudrate

        self.ser = None

        self.connect_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.data_lock = threading.Lock()

        self.last_lines = []
        self.max_lines = 200

        self.reader_thread = None
        self.reader_running = False

        self.last_encoder_values = {
            "FL": None,
            "FR": None,
            "RR": None,
            "RL": None,
        }
        self.last_encoder_time = 0.0

        self.wheel_ticks_json = "/tmp/rb2_wheel_ticks.json"

    # =====================================================
    # CONNEXION / THREAD LECTURE
    # =====================================================

    def connect(self):
        with self.connect_lock:
            if self.ser and self.ser.is_open:
                self._ensure_reader()
                return True

            try:
                self.ser = serial.Serial(self.port, self.baudrate, timeout=0.2)
                time.sleep(2.0)

                self.reader_running = True
                self._ensure_reader()

                self._append_line(f"INFO ESP32 connecté: {self.port} {self.baudrate}")
                return True

            except Exception as e:
                self._append_line(f"ERREUR connexion ESP32: {e}")
                return False

    def _ensure_reader(self):
        if self.reader_thread and self.reader_thread.is_alive():
            return

        self.reader_running = True
        self.reader_thread = threading.Thread(
            target=self._reader_loop,
            name="rb2_esp32_reader",
            daemon=True,
        )
        self.reader_thread.start()

    def close(self):
        self.reader_running = False

        try:
            if self.reader_thread and self.reader_thread.is_alive():
                self.reader_thread.join(timeout=1.0)
        except Exception:
            pass

        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    # =====================================================
    # LECTURE SÉRIE CONTINUE
    # =====================================================

    def _reader_loop(self):
        while self.reader_running:
            try:
                if not self.ser or not self.ser.is_open:
                    time.sleep(0.2)
                    continue

                line = self.ser.readline().decode("utf-8", errors="replace").strip()

                if not line:
                    continue

                self._append_line(line)
                self._handle_line(line)

            except Exception as e:
                self._append_line(f"ERREUR lecture ESP32: {e}")
                time.sleep(0.2)

    def _append_line(self, line):
        with self.data_lock:
            self.last_lines.append(str(line))
            self.last_lines = self.last_lines[-self.max_lines:]

    def _handle_line(self, line):
        if not line:
            return

        if line.startswith("ENC "):
            self._parse_compact_encoder_line(line)

    def _parse_compact_encoder_line(self, line):
        parts = line.split()

        if len(parts) != 5:
            return

        try:
            fl = int(parts[1])
            fr = int(parts[2])
            rr = int(parts[3])
            rl = int(parts[4])
        except ValueError:
            return

        now = time.time()

        values = {
            "FL": fl,
            "FR": fr,
            "RR": rr,
            "RL": rl,
        }

        with self.data_lock:
            self.last_encoder_values = values
            self.last_encoder_time = now

        self._write_wheel_ticks_json(values, now)

    def _write_wheel_ticks_json(self, values, stamp):
        data = {
            "ok": True,
            "stamp": stamp,
            "age_s": 0.0,
            "ticks": {
                "FL": values["FL"],
                "FR": values["FR"],
                "RR": values["RR"],
                "RL": values["RL"],
            },
            "data": [
                values["FL"],
                values["FR"],
                values["RR"],
                values["RL"],
            ],
            "source": "esp32_auto_enc",
        }

        directory = os.path.dirname(self.wheel_ticks_json) or "/tmp"

        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".rb2_wheel_ticks_",
                suffix=".json",
                dir=directory,
                text=True,
            )

            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)

            os.replace(tmp_path, self.wheel_ticks_json)

        except Exception as e:
            self._append_line(f"ERREUR écriture {self.wheel_ticks_json}: {e}")

    # =====================================================
    # API COMPATIBLE AVEC esp32_panel.py
    # =====================================================

    def send(self, command, wait=0.15):
        command = str(command).strip()

        if not command:
            return {
                "ok": False,
                "command": command,
                "lines": [],
                "error": "Commande vide",
            }

        if not self.connect():
            return {
                "ok": False,
                "command": command,
                "lines": self.get_last_lines(10),
                "error": "ESP32 non connecté",
            }

        with self.data_lock:
            start_index = len(self.last_lines)

        try:
            with self.write_lock:
                self.ser.write((command + "\n").encode("utf-8"))
                self.ser.flush()

            time.sleep(wait)

            with self.data_lock:
                lines = self.last_lines[start_index:]

            return {
                "ok": True,
                "command": command,
                "lines": lines,
                "error": None,
            }

        except Exception as e:
            return {
                "ok": False,
                "command": command,
                "lines": self.get_last_lines(10),
                "error": str(e),
            }

    def get_last_lines(self, count=10):
        with self.data_lock:
            return list(self.last_lines[-count:])

    def get_last_encoders(self):
        with self.data_lock:
            values = dict(self.last_encoder_values)
            stamp = self.last_encoder_time

        age = time.time() - stamp if stamp else None

        return {
            "ok": stamp > 0,
            "values": values,
            "stamp": stamp,
            "age_s": age,
            "source": "esp32_auto_enc",
        }

    def status(self):
        return self.send("status", wait=0.5)

    def stop(self):
        return self.send("d0,0", wait=0.1)

    def drive(self, left, right):
        left = max(-100, min(100, int(left)))
        right = max(-100, min(100, int(right)))
        return self.send(f"d{left},{right}", wait=0.1)

    def pan(self, value):
        value = max(0, min(180, int(value)))
        return self.send(f"p{value}", wait=0.1)

    def tilt(self, value):
        value = max(68, min(145, int(value)))
        return self.send(f"t{value}", wait=0.1)

    def encoders(self):
        result = self.send("enc", wait=0.5)
        result["auto_encoders"] = self.get_last_encoders()
        return result
