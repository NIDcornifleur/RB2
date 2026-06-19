#!/usr/bin/env python3
import serial
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Int32MultiArray


class CmdVelSerialNode(Node):
    def __init__(self):
        super().__init__('rb2_cmd_vel_serial')

        self.declare_parameter('port', '/dev/esp32')
        self.declare_parameter('baud', 115200)
        self.declare_parameter('timeout_s', 0.5)
        self.declare_parameter('max_linear', 0.30)
        self.declare_parameter('max_angular', 1.50)

        self.port = str(self.get_parameter('port').value)
        self.baud = int(self.get_parameter('baud').value)
        self.timeout_s = float(self.get_parameter('timeout_s').value)
        self.max_linear = float(self.get_parameter('max_linear').value)
        self.max_angular = float(self.get_parameter('max_angular').value)

        self.last_cmd_time = self.get_clock().now()

        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.02)
            time.sleep(2.0)
            self.get_logger().info(f"Port série ouvert: {self.port} à {self.baud} bauds")
        except Exception as e:
            self.get_logger().error(f"Impossible d'ouvrir {self.port}: {e}")
            raise

        self.sub = self.create_subscription(Twist, '/cmd_vel', self.cmd_cb, 10)

        self.ticks_pub = self.create_publisher(Int32MultiArray, '/wheel_ticks', 10)

        self.watchdog_timer = self.create_timer(0.1, self.watchdog)
        self.read_timer = self.create_timer(0.02, self.read_serial)

        self.get_logger().info(
            f"Écoute /cmd_vel -> {self.port}. Publie /wheel_ticks. "
            f"Limites: linear={self.max_linear}, angular={self.max_angular}"
        )

    def clamp(self, value, limit):
        return max(-limit, min(limit, value))

    def send_line(self, line):
        try:
            self.ser.write(line.encode('ascii'))
        except Exception as e:
            self.get_logger().warn(f"Erreur écriture série: {e}")

    def cmd_cb(self, msg):
        linear_x = self.clamp(msg.linear.x, self.max_linear)
        angular_z = self.clamp(msg.angular.z, self.max_angular)

        line = f"CMD {linear_x:.3f} {angular_z:.3f}\n"
        self.send_line(line)
        self.last_cmd_time = self.get_clock().now()

    def watchdog(self):
        elapsed = (self.get_clock().now() - self.last_cmd_time).nanoseconds / 1e9

        if elapsed > self.timeout_s:
            self.send_line("CMD 0.000 0.000\n")
            self.last_cmd_time = self.get_clock().now()

    def read_serial(self):
        try:
            while self.ser.in_waiting:
                line = self.ser.readline().decode(errors='replace').strip()
                if not line:
                    continue

                if line.startswith("ENC "):
                    self.handle_encoder_line(line)
                elif line.startswith("Recu:") or "PWM moteur" in line or "Watchdog" in line:
                    self.get_logger().info(f"ESP32: {line}")
                else:
                    self.get_logger().debug(f"ESP32: {line}")

        except Exception as e:
            self.get_logger().warn(f"Erreur lecture série: {e}")

    def handle_encoder_line(self, line):
        parts = line.split()

        if len(parts) != 5:
            self.get_logger().warn(f"Ligne ENC invalide: {line}")
            return

        try:
            fl = int(parts[1])
            fr = int(parts[2])
            rr = int(parts[3])
            rl = int(parts[4])
        except ValueError:
            self.get_logger().warn(f"Valeurs ENC invalides: {line}")
            return

        msg = Int32MultiArray()
        msg.data = [fl, fr, rr, rl]
        self.ticks_pub.publish(msg)

    def destroy_node(self):
        try:
            self.ser.write(b"CMD 0.000 0.000\n")
            self.ser.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CmdVelSerialNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
