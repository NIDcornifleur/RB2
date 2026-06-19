#!/usr/bin/env python3
import json
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32MultiArray


class WheelTicksJsonNode(Node):
    def __init__(self):
        super().__init__("rb2_wheel_ticks_json")

        self.declare_parameter("json_file", "/tmp/rb2_wheel_ticks.json")
        self.declare_parameter("rate_hz", 10.0)
        self.declare_parameter("max_age_s", 2.0)

        self.json_file = str(self.get_parameter("json_file").value)
        self.rate_hz = float(self.get_parameter("rate_hz").value)
        self.max_age_s = float(self.get_parameter("max_age_s").value)

        if self.rate_hz <= 0:
            self.rate_hz = 10.0

        self.pub = self.create_publisher(Int32MultiArray, "/wheel_ticks", 10)

        self.last_data = None
        self.last_warn_time = 0.0

        period = 1.0 / self.rate_hz
        self.timer = self.create_timer(period, self.timer_cb)

        self.get_logger().info(
            f"RB2 wheel_ticks JSON publisher started: "
            f"file={self.json_file}, rate={self.rate_hz} Hz, max_age={self.max_age_s} s"
        )

    def warn_limited(self, message, interval_s=3.0):
        now = time.time()
        if now - self.last_warn_time >= interval_s:
            self.get_logger().warn(message)
            self.last_warn_time = now

    def read_ticks_file(self):
        if not os.path.exists(self.json_file):
            self.warn_limited(f"Fichier absent: {self.json_file}")
            return None

        try:
            with open(self.json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.warn_limited(f"Lecture JSON impossible: {e}")
            return None

        if not data.get("ok", False):
            self.warn_limited("JSON ticks indique ok=false")
            return None

        ticks = data.get("data")
        if not isinstance(ticks, list) or len(ticks) != 4:
            self.warn_limited(f"Champ data invalide dans {self.json_file}: {ticks}")
            return None

        try:
            ticks = [int(v) for v in ticks]
        except Exception:
            self.warn_limited(f"Valeurs ticks non entières: {ticks}")
            return None

        stamp = float(data.get("stamp", 0.0) or 0.0)
        if stamp <= 0:
            self.warn_limited("Stamp absent ou invalide dans JSON ticks")
            return None

        age_s = time.time() - stamp
        if age_s > self.max_age_s:
            self.warn_limited(f"Ticks trop vieux: age={age_s:.2f} s")
            return None

        return ticks

    def timer_cb(self):
        ticks = self.read_ticks_file()
        if ticks is None:
            return

        msg = Int32MultiArray()
        msg.data = ticks
        self.pub.publish(msg)
        self.last_data = ticks


def main(args=None):
    rclpy.init(args=args)
    node = WheelTicksJsonNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
