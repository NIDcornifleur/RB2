#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
import tempfile
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


OUT_FILE = "/tmp/rb2_lidar_map.json"

# Limites raisonnables pour affichage terrain.
MAX_POINTS = 720
MAX_RANGE_M = 4.0


class RB2LidarMapJson(Node):
    def __init__(self):
        super().__init__("rb2_lidar_map_json")
        self.sub = self.create_subscription(LaserScan, "/scan", self.cb_scan, 10)
        self.get_logger().info("RB2 LIDAR map JSON bridge actif : /scan -> /tmp/rb2_lidar_map.json")

    def cb_scan(self, msg: LaserScan):
        ranges = list(msg.ranges)
        n = len(ranges)

        if n <= 0:
            return

        step = max(1, n // MAX_POINTS)
        points = []

        for i in range(0, n, step):
            r = ranges[i]

            if not math.isfinite(r):
                continue

            if r <= 0.02:
                continue

            if r > MAX_RANGE_M:
                continue

            angle = msg.angle_min + i * msg.angle_increment

            # Convention d'affichage :
            # x = droite/gauche
            # y = avant/arrière
            #
            # Pour un LaserScan ROS standard :
            # angle 0 = avant
            # x_ros = r*cos(angle)
            # y_ros = r*sin(angle)
            #
            # Ici on convertit pour affichage :
            # avant = +y
            # droite = +x
            #
            # x_display = -y_ros
            # y_display = x_ros
            x_ros = r * math.cos(angle)
            y_ros = r * math.sin(angle)

            x_cm = -y_ros * 100.0
            y_cm = x_ros * 100.0

            points.append([round(x_cm, 1), round(y_cm, 1)])

        data = {
            "ok": True,
            "stamp": time.time(),
            "frame_id": msg.header.frame_id,
            "count": len(points),
            "range_max_m": float(msg.range_max),
            "angle_min": float(msg.angle_min),
            "angle_max": float(msg.angle_max),
            "points_cm": points,

            # Géométrie RB2 autour du centre du LIDAR.
            "robot": {
                "front_cm": 28.0,
                "back_cm": 8.0,
                "half_width_cm": 10.0,
                "front_line_cm": 35.0
            }
        }

        self.atomic_write_json(OUT_FILE, data)

    def atomic_write_json(self, path, data):
        directory = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(prefix=".rb2_lidar_map_", suffix=".json", dir=directory)

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
    node = RB2LidarMapJson()

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
