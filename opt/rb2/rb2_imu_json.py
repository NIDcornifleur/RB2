#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math

# Calibration horizon RB2 — mesurée robot à plat
ROLL_OFFSET_DEG = -1.606
PITCH_OFFSET_DEG = 2.231
import os
import tempfile
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu


OUT_FILE = "/tmp/rb2_imu.json"


class RB2ImuJson(Node):
    def __init__(self):
        super().__init__("rb2_imu_json")
        self.sub = self.create_subscription(Imu, "/imu", self.cb_imu, 10)
        self.get_logger().info("RB2 IMU JSON bridge actif : /imu -> /tmp/rb2_imu.json")

    def cb_imu(self, msg: Imu):
        ax = float(msg.linear_acceleration.x)
        ay = float(msg.linear_acceleration.y)
        az = float(msg.linear_acceleration.z)

        gx = float(msg.angular_velocity.x)
        gy = float(msg.angular_velocity.y)
        gz = float(msg.angular_velocity.z)

        # Inclinaison à partir de l'accéléromètre.
        # Convention pratique pour horizon artificiel :
        # roll  = inclinaison gauche/droite
        # pitch = inclinaison avant/arrière
        #
        # Ces signes pourront être inversés après observation réelle dans la page.
        roll_rad = math.atan2(ay, az)
        pitch_rad = math.atan2(-ax, math.sqrt(ay * ay + az * az))

        roll_deg_raw = math.degrees(roll_rad)
        pitch_deg_raw = math.degrees(pitch_rad)

        # Application des offsets pour que RB2 à plat affiche 0 / 0
        roll_deg = roll_deg_raw + ROLL_OFFSET_DEG
        pitch_deg = pitch_deg_raw + PITCH_OFFSET_DEG

        data = {
            "ok": True,
            "stamp": time.time(),
            "frame_id": msg.header.frame_id,
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
            "roll_deg": roll_deg,
            "pitch_deg": pitch_deg,
        }

        self.atomic_write_json(OUT_FILE, data)

    def atomic_write_json(self, path, data):
        directory = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(prefix=".rb2_imu_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp_path, path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass


def main():
    rclpy.init()
    node = RB2ImuJson()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
