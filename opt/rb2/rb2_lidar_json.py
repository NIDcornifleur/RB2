#!/usr/bin/env python3
import json
import math
import os
import time
from pathlib import Path

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


OUT = Path("/tmp/rb2_lidar.json")
TMP = Path("/tmp/rb2_lidar.json.tmp")

# Géométrie pratique RB2, depuis le centre du LIDAR
FRONT_BODY_CM = 37.0
BACK_BODY_CM = 10.0

# Structures RB2 visibles par le LIDAR
# Arrière : antennes / structure arrière proches, environ 5 à 11 cm
BACK_SELF_IGNORE_CM = 12.0

# Droit / arrière-droit :
# antenne droite environ 9 cm, roue arrière droite environ 15 cm.
# On ignore seulement les retours très proches dans le secteur droit,
# pour éviter de contaminer right_cm et min_cm.
RIGHT_SELF_IGNORE_CM = 16.0

# Seuils utiles
BACK_DANGER_CM = 15.0
BACK_WARNING_CM = 25.0

FRONT_DANGER_CM = 37.0
FRONT_WARNING_CM = 47.0

SIDE_WARNING_CM = 20.0


def norm_deg(a):
    while a > 180.0:
        a -= 360.0
    while a <= -180.0:
        a += 360.0
    return a


def min_or_none(vals):
    vals = [v for v in vals if v is not None and math.isfinite(v) and v > 0]
    if not vals:
        return None
    return round(min(vals), 1)


class RB2LidarJson(Node):
    def __init__(self):
        super().__init__("rb2_lidar_json")
        self.sub = self.create_subscription(LaserScan, "/scan", self.scan_callback, 10)
        self.get_logger().info(
            "RB2 LIDAR JSON actif : arrière <= 12 cm ignoré ; droit <= 16 cm ignoré"
        )

    def scan_callback(self, msg: LaserScan):
        front_vals = []
        back_vals = []
        left_vals = []
        right_vals = []
        all_vals = []

        ignored_back_self = 0
        ignored_right_self = 0

        angle = msg.angle_min

        for r in msg.ranges:
            try:
                rr = float(r)
            except Exception:
                angle += msg.angle_increment
                continue

            if not math.isfinite(rr):
                angle += msg.angle_increment
                continue

            if rr <= 0:
                angle += msg.angle_increment
                continue

            if msg.range_min and rr < msg.range_min:
                angle += msg.angle_increment
                continue

            if msg.range_max and rr > msg.range_max:
                angle += msg.angle_increment
                continue

            cm = rr * 100.0
            deg = norm_deg(math.degrees(angle))

            # Convention RB2 validée :
            # 0° = avant, +/-180° = arrière
            # +90° = gauche, -90° = droite
            if -30.0 <= deg <= 30.0:
                front_vals.append(cm)
                all_vals.append(cm)

            elif deg >= 150.0 or deg <= -150.0:
                if cm <= BACK_SELF_IGNORE_CM:
                    ignored_back_self += 1
                else:
                    back_vals.append(cm)
                    all_vals.append(cm)

            elif 60.0 <= deg <= 120.0:
                left_vals.append(cm)
                all_vals.append(cm)

            elif -120.0 <= deg <= -60.0:
                if cm <= RIGHT_SELF_IGNORE_CM:
                    ignored_right_self += 1
                else:
                    right_vals.append(cm)
                    all_vals.append(cm)

            angle += msg.angle_increment

        front_cm = min_or_none(front_vals)
        back_cm = min_or_none(back_vals)
        left_cm = min_or_none(left_vals)
        right_cm = min_or_none(right_vals)

        useful_vals = [v for v in [front_cm, back_cm, left_cm, right_cm] if v is not None]
        min_cm = min_or_none(useful_vals)

        now = time.time()

        data = {
            "ok": True,
            "timestamp": now,
            "stamp": now,

            "front_cm": front_cm,
            "back_cm": back_cm,
            "left_cm": left_cm,
            "right_cm": right_cm,
            "min_cm": min_cm,

            "clearance": {
                "front_cm": front_cm,
                "back_cm": back_cm,
                "left_cm": left_cm,
                "right_cm": right_cm,
                "min_cm": min_cm,
            },

            "robot": {
                "front_cm": 28,
                "back_cm": 10,
                "half_width_cm": 10,
                "front_line_cm": 35,
            },

            "rb2_filter": {
                "back_self_ignore_cm": BACK_SELF_IGNORE_CM,
                "right_self_ignore_cm": RIGHT_SELF_IGNORE_CM,
                "ignored_back_self_points": ignored_back_self,
                "ignored_right_self_points": ignored_right_self,
                "back_body_cm": BACK_BODY_CM,
                "back_danger_cm": BACK_DANGER_CM,
                "back_warning_cm": BACK_WARNING_CM,
                "side_warning_cm": SIDE_WARNING_CM,
                "note": "Retours internes ignorés : arrière <= 12 cm ; droit/arrière-droit <= 16 cm",
            },
        }

        try:
            TMP.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(TMP, OUT)
        except Exception as e:
            self.get_logger().warn(f"Erreur écriture {OUT}: {e}")


def main():
    rclpy.init()
    node = RB2LidarJson()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
