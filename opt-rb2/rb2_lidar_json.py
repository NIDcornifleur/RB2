#!/usr/bin/env python3
import json
import math
import os
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


OUT_FILE = "/tmp/rb2_lidar.json"

# Secteurs en degrés, selon la convention ROS LaserScan :
# 0° = avant du LIDAR si le launch/driver est orienté correctement.
SECTORS = {
    "front": (-15, 15),
    "left": (75, 105),
    "right": (-105, -75),
    "back": (165, 180),
}


def norm_deg(angle):
    while angle > 180:
        angle -= 360
    while angle < -180:
        angle += 360
    return angle


def in_sector(angle_deg, start_deg, end_deg):
    angle_deg = norm_deg(angle_deg)
    start_deg = norm_deg(start_deg)
    end_deg = norm_deg(end_deg)

    if start_deg <= end_deg:
        return start_deg <= angle_deg <= end_deg

    return angle_deg >= start_deg or angle_deg <= end_deg


def valid_range(value, range_min, range_max):
    return (
        value is not None
        and math.isfinite(value)
        and value >= range_min
        and value <= range_max
    )


class RB2LidarJson(Node):
    def __init__(self):
        super().__init__("rb2_lidar_json")
        self.sub = self.create_subscription(
            LaserScan,
            "/scan",
            self.scan_callback,
            10,
        )
        self.get_logger().info("RB2 LIDAR JSON actif -> /tmp/rb2_lidar.json")

    def scan_callback(self, msg):
        sector_values = {name: [] for name in SECTORS}
        all_values = []

        for i, r in enumerate(msg.ranges):
            if not valid_range(r, msg.range_min, msg.range_max):
                continue

            angle_rad = msg.angle_min + i * msg.angle_increment
            angle_deg = math.degrees(angle_rad)
            angle_deg = norm_deg(angle_deg)

            r_cm = r * 100.0
            all_values.append(r_cm)

            for name, (a0, a1) in SECTORS.items():
                if in_sector(angle_deg, a0, a1):
                    sector_values[name].append(r_cm)

        def min_or_none(values):
            if not values:
                return None
            return round(min(values), 1)

        data = {
            "ok": True,
            "stamp": time.time(),
            "front_cm": min_or_none(sector_values["front"]),
            "left_cm": min_or_none(sector_values["left"]),
            "right_cm": min_or_none(sector_values["right"]),
            "back_cm": min_or_none(sector_values["back"]),
            "min_cm": min_or_none(all_values),
            "count": len(all_values),
        }

        tmp = OUT_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, OUT_FILE)


def main():
    rclpy.init()
    node = RB2LidarJson()

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
