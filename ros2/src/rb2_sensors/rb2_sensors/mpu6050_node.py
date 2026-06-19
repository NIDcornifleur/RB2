#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RB2 - Noeud ROS 2 IMU MPU6050 / compatible InvenSense.

Version robuste pour RB2 :
- accepte WHO_AM_I 0x68 et 0x70;
- ne meurt pas au premier Errno 121;
- réessaie l'initialisation I2C tant que le capteur ne répond pas correctement;
- publie /imu seulement quand une lecture complète est valide;
- conserve gyro_z dans msg.angular_velocity.z pour futur demi-tour 180°;
- journalise sans inonder les logs.

Note :
0x70 est fréquent sur certains modules compatibles/variantes. Ce n'est pas traité
comme fatal si les registres d'accélération/gyro répondent correctement.
"""

import math
import time
from typing import Optional

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import Header

import smbus


MPU_ADDR = 0x68

WHO_AM_I = 0x75
PWR_MGMT_1 = 0x6B
SMPLRT_DIV = 0x19
CONFIG = 0x1A
GYRO_CONFIG = 0x1B
ACCEL_CONFIG = 0x1C
ACCEL_XOUT_H = 0x3B
GYRO_XOUT_H = 0x43

# Réglages conservateurs : +/- 2 g, +/- 250 deg/s
ACCEL_SCALE = 16384.0
GYRO_SCALE = 131.0

# Identifiants acceptés pour RB2.
# 0x68 = MPU6050 classique.
# 0x70 = variante/compatible observée sur le module de RB2.
ACCEPTED_WHO_AM_I = {0x68, 0x70}


class MPU6050Node(Node):
    def __init__(self):
        super().__init__("rb2_mpu6050")

        self.declare_parameter("bus", 1)
        self.declare_parameter("address", MPU_ADDR)
        self.declare_parameter("frame_id", "imu_link")
        self.declare_parameter("rate_hz", 50.0)
        self.declare_parameter("init_retry_s", 1.0)

        self.bus_id = int(self.get_parameter("bus").value)
        self.address = int(self.get_parameter("address").value)
        self.frame_id = str(self.get_parameter("frame_id").value)
        self.rate_hz = float(self.get_parameter("rate_hz").value)
        self.init_retry_s = float(self.get_parameter("init_retry_s").value)

        self.bus: Optional[smbus.SMBus] = None
        self.sensor_ready = False
        self.last_init_attempt = 0.0
        self.last_warn_time = 0.0
        self.last_ok_log_time = 0.0
        self.who_am_i = None

        self.pub = self.create_publisher(Imu, "/imu", 10)

        period = 1.0 / max(1.0, self.rate_hz)
        self.timer = self.create_timer(period, self.publish_imu)

        self.get_logger().info(
            f"RB2 IMU node robuste démarré: bus={self.bus_id}, "
            f"adresse=0x{self.address:02X}, frame_id={self.frame_id}, rate={self.rate_hz:.1f} Hz"
        )

        # Première tentative immédiate. Si elle échoue, le timer réessaiera.
        self.try_init_sensor(force=True)

    def warn_throttled(self, message: str, period_s: float = 5.0):
        now = time.time()
        if now - self.last_warn_time >= period_s:
            self.get_logger().warn(message)
            self.last_warn_time = now

    def open_bus(self):
        if self.bus is None:
            self.bus = smbus.SMBus(self.bus_id)

    def i2c_read_byte_retry(self, reg: int, attempts: int = 5, delay_s: float = 0.03) -> int:
        last_error = None
        for _ in range(attempts):
            try:
                self.open_bus()
                return self.bus.read_byte_data(self.address, reg)
            except Exception as e:
                last_error = e
                time.sleep(delay_s)
        raise last_error

    def i2c_write_byte_retry(self, reg: int, value: int, attempts: int = 5, delay_s: float = 0.05):
        last_error = None
        for _ in range(attempts):
            try:
                self.open_bus()
                self.bus.write_byte_data(self.address, reg, value)
                return
            except Exception as e:
                last_error = e
                time.sleep(delay_s)
        raise last_error

    def try_init_sensor(self, force: bool = False) -> bool:
        now = time.time()
        if not force and now - self.last_init_attempt < self.init_retry_s:
            return self.sensor_ready

        self.last_init_attempt = now

        try:
            self.open_bus()

            who = self.i2c_read_byte_retry(WHO_AM_I, attempts=5)
            self.who_am_i = who

            if who not in ACCEPTED_WHO_AM_I:
                self.warn_throttled(
                    f"WHO_AM_I inattendu: 0x{who:02X}. "
                    f"Acceptés: {', '.join('0x%02X' % x for x in sorted(ACCEPTED_WHO_AM_I))}. "
                    "Essai de lecture quand même."
                )

            # Réveil et configuration minimale. Chaque écriture est réessayée.
            self.i2c_write_byte_retry(PWR_MGMT_1, 0x00, attempts=8)
            time.sleep(0.10)

            # Filtre passe-bas raisonnable, échantillonnage modéré, plages par défaut.
            self.i2c_write_byte_retry(SMPLRT_DIV, 0x07, attempts=5)   # 1 kHz / (1+7) = 125 Hz interne
            self.i2c_write_byte_retry(CONFIG, 0x03, attempts=5)       # DLPF modéré
            self.i2c_write_byte_retry(GYRO_CONFIG, 0x00, attempts=5)  # +/- 250 deg/s
            self.i2c_write_byte_retry(ACCEL_CONFIG, 0x00, attempts=5) # +/- 2 g

            # Lecture de validation. Si ceci passe, le capteur est utilisable.
            _ = self.read_word_2c(ACCEL_XOUT_H)
            _ = self.read_word_2c(GYRO_XOUT_H)

            if not self.sensor_ready:
                self.get_logger().info(
                    f"IMU prête: adresse=0x{self.address:02X}, WHO_AM_I=0x{who:02X}"
                )

            self.sensor_ready = True
            return True

        except Exception as e:
            self.sensor_ready = False
            self.warn_throttled(
                f"IMU non prête sur I2C bus {self.bus_id}, adresse 0x{self.address:02X}: {e}. "
                "Nouvelle tentative automatique."
            )

            # Fermer et rouvrir au prochain essai peut aider après Errno 121.
            try:
                if self.bus is not None:
                    self.bus.close()
            except Exception:
                pass
            self.bus = None
            return False

    def read_word_2c(self, reg: int) -> int:
        high = self.i2c_read_byte_retry(reg, attempts=3, delay_s=0.01)
        low = self.i2c_read_byte_retry(reg + 1, attempts=3, delay_s=0.01)
        value = (high << 8) | low

        if value >= 0x8000:
            value = -((65535 - value) + 1)

        return value

    def publish_imu(self):
        if not self.sensor_ready:
            self.try_init_sensor()
            return

        try:
            ax_raw = self.read_word_2c(ACCEL_XOUT_H)
            ay_raw = self.read_word_2c(ACCEL_XOUT_H + 2)
            az_raw = self.read_word_2c(ACCEL_XOUT_H + 4)

            gx_raw = self.read_word_2c(GYRO_XOUT_H)
            gy_raw = self.read_word_2c(GYRO_XOUT_H + 2)
            gz_raw = self.read_word_2c(GYRO_XOUT_H + 4)

            ax = (ax_raw / ACCEL_SCALE) * 9.80665
            ay = (ay_raw / ACCEL_SCALE) * 9.80665
            az = (az_raw / ACCEL_SCALE) * 9.80665

            gx = math.radians(gx_raw / GYRO_SCALE)
            gy = math.radians(gy_raw / GYRO_SCALE)
            gz = math.radians(gz_raw / GYRO_SCALE)

            msg = Imu()
            msg.header = Header()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = self.frame_id

            # Orientation non calculée ici.
            msg.orientation_covariance[0] = -1.0

            msg.angular_velocity.x = gx
            msg.angular_velocity.y = gy
            msg.angular_velocity.z = gz

            msg.linear_acceleration.x = ax
            msg.linear_acceleration.y = ay
            msg.linear_acceleration.z = az

            msg.angular_velocity_covariance[0] = 0.02
            msg.angular_velocity_covariance[4] = 0.02
            msg.angular_velocity_covariance[8] = 0.02

            msg.linear_acceleration_covariance[0] = 0.1
            msg.linear_acceleration_covariance[4] = 0.1
            msg.linear_acceleration_covariance[8] = 0.1

            self.pub.publish(msg)

            now = time.time()
            if now - self.last_ok_log_time > 60.0:
                self.get_logger().info(
                    f"IMU publie /imu: WHO_AM_I=0x{(self.who_am_i or 0):02X}, "
                    f"gz={gz:.4f} rad/s"
                )
                self.last_ok_log_time = now

        except Exception as e:
            self.sensor_ready = False
            self.warn_throttled(f"Erreur lecture IMU: {e}. Réinitialisation automatique.")
            try:
                if self.bus is not None:
                    self.bus.close()
            except Exception:
                pass
            self.bus = None


def main(args=None):
    rclpy.init(args=args)
    node = MPU6050Node()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        try:
            node.get_logger().error(f"Erreur fatale rb2_mpu6050: {e}")
        except Exception:
            pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
