#!/usr/bin/env python3
import math

import rclpy
from rclpy.node import Node

from std_msgs.msg import Int32MultiArray, Empty
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


class RB2OdometryNode(Node):
    def __init__(self):
        super().__init__('rb2_odometry')

        self.declare_parameter('wheel_diameter_m', 0.085)
        self.declare_parameter('track_width_m', 0.225)
        self.declare_parameter('ticks_per_rev', 10529.0)
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_link')
        self.declare_parameter('publish_tf', True)

        self.wheel_diameter = float(self.get_parameter('wheel_diameter_m').value)
        self.track_width = float(self.get_parameter('track_width_m').value)
        self.ticks_per_rev = float(self.get_parameter('ticks_per_rev').value)
        self.odom_frame = str(self.get_parameter('odom_frame').value)
        self.base_frame = str(self.get_parameter('base_frame').value)
        self.publish_tf = bool(self.get_parameter('publish_tf').value)

        self.wheel_circumference = math.pi * self.wheel_diameter
        self.m_per_tick = self.wheel_circumference / self.ticks_per_rev

        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0

        self.last_ticks = None
        self.last_time = None

        self.odom_pub = self.create_publisher(Odometry, '/odom', 20)
        self.tf_broadcaster = TransformBroadcaster(self)

        self.sub = self.create_subscription(
            Int32MultiArray,
            '/wheel_ticks',
            self.ticks_callback,
            20
        )

        self.reset_sub = self.create_subscription(
            Empty,
            '/reset_odom',
            self.reset_callback,
            10
        )

        self.get_logger().info(
            f"RB2 odometry started: wheel_diameter={self.wheel_diameter:.3f} m, "
            f"track_width={self.track_width:.3f} m, ticks_per_rev={self.ticks_per_rev:.1f}, "
            f"m_per_tick={self.m_per_tick:.8f}"
        )

    def reset_callback(self, msg):
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0
        self.last_ticks = None
        self.last_time = None
        now = self.get_clock().now()
        self.publish_odom(now, 0.0, 0.0)
        self.get_logger().info("Odométrie remise à zéro par /reset_odom")

    def ticks_callback(self, msg):
        if len(msg.data) < 4:
            self.get_logger().warn(f"/wheel_ticks invalide: {msg.data}")
            return

        fl, fr, rr, rl = [int(v) for v in msg.data[:4]]
        now = self.get_clock().now()

        if self.last_ticks is None:
            self.last_ticks = (fl, fr, rr, rl)
            self.last_time = now
            self.publish_odom(now, 0.0, 0.0)
            return

        last_fl, last_fr, last_rr, last_rl = self.last_ticks

        d_fl = fl - last_fl
        d_fr = fr - last_fr
        d_rr = rr - last_rr
        d_rl = rl - last_rl

        self.last_ticks = (fl, fr, rr, rl)

        dt = (now - self.last_time).nanoseconds / 1e9
        self.last_time = now

        if dt <= 0.0:
            return

        left_ticks = (d_fl + d_rl) / 2.0
        right_ticks = (d_fr + d_rr) / 2.0

        left_dist = left_ticks * self.m_per_tick
        right_dist = right_ticks * self.m_per_tick

        center_dist = (left_dist + right_dist) / 2.0
        dtheta = (right_dist - left_dist) / self.track_width

        theta_mid = self.theta + dtheta / 2.0

        self.x += center_dist * math.cos(theta_mid)
        self.y += center_dist * math.sin(theta_mid)
        self.theta += dtheta
        self.theta = math.atan2(math.sin(self.theta), math.cos(self.theta))

        linear_velocity = center_dist / dt
        angular_velocity = dtheta / dt

        self.publish_odom(now, linear_velocity, angular_velocity)

    def publish_odom(self, stamp, linear_velocity, angular_velocity):
        qz = math.sin(self.theta / 2.0)
        qw = math.cos(self.theta / 2.0)

        odom = Odometry()
        odom.header.stamp = stamp.to_msg()
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame

        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.position.z = 0.0

        odom.pose.pose.orientation.x = 0.0
        odom.pose.pose.orientation.y = 0.0
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw

        odom.twist.twist.linear.x = linear_velocity
        odom.twist.twist.linear.y = 0.0
        odom.twist.twist.angular.z = angular_velocity

        odom.pose.covariance[0] = 0.02
        odom.pose.covariance[7] = 0.02
        odom.pose.covariance[35] = 0.05

        odom.twist.covariance[0] = 0.05
        odom.twist.covariance[35] = 0.10

        self.odom_pub.publish(odom)

        if self.publish_tf:
            tf = TransformStamped()
            tf.header.stamp = stamp.to_msg()
            tf.header.frame_id = self.odom_frame
            tf.child_frame_id = self.base_frame

            tf.transform.translation.x = self.x
            tf.transform.translation.y = self.y
            tf.transform.translation.z = 0.0

            tf.transform.rotation.x = 0.0
            tf.transform.rotation.y = 0.0
            tf.transform.rotation.z = qz
            tf.transform.rotation.w = qw

            self.tf_broadcaster.sendTransform(tf)


def main(args=None):
    rclpy.init(args=args)
    node = RB2OdometryNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
