from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    ldlidar_launch = os.path.join(
        get_package_share_directory('rb2_bringup'),
        'launch',
        'rb2_lidar.launch.py'
    )

    lidar = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(ldlidar_launch)
    )

    imu = Node(
        package='rb2_sensors',
        executable='mpu6050_node',
        name='rb2_mpu6050',
        output='screen',
        parameters=[
            {'bus': 1},
            {'address': 0x68},
            {'frame_id': 'imu_link'},
            {'rate_hz': 50.0},
        ]
    )

    base_link_to_imu_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_link_to_imu_link',
        arguments=[
            '0', '0', '0.10',
            '0', '0', '0',
            'base_link', 'imu_link'
        ]
    )

    esp32_cmd_vel = Node(
        package='rb2_base',
        executable='cmd_vel_serial_node',
        name='rb2_cmd_vel_serial',
        output='screen',
        parameters=[
            {'port': '/dev/esp32'},
            {'baud': 115200},
            {'timeout_s': 0.5},
            {'max_linear': 0.30},
            {'max_angular': 1.50},
        ]
    )

    odometry = Node(
        package='rb2_base',
        executable='odometry_node',
        name='rb2_odometry',
        output='screen',
        parameters=[
            {'wheel_diameter_m': 0.085},
            {'track_width_m': 0.225},
            {'ticks_per_rev': 10529.0},
            {'odom_frame': 'odom'},
            {'base_frame': 'base_link'},
            {'publish_tf': True},
        ]
    )


    wheel_ticks_json = Node(
        package='rb2_base',
        executable='wheel_ticks_json_node',
        name='rb2_wheel_ticks_json',
        output='screen',
        parameters=[
            {'json_file': '/tmp/rb2_wheel_ticks.json'},
            {'rate_hz': 10.0},
            {'max_age_s': 2.0},
        ]
    )

    return LaunchDescription([
        lidar,
        imu,
        base_link_to_imu_tf,
        # esp32_cmd_vel,  # Désactivé : mode web direct ESP32
        wheel_ticks_json,
        odometry,
    ])
