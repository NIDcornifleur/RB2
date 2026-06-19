from setuptools import find_packages, setup

package_name = 'rb2_base'

setup(
    name=package_name,
    version='0.0.2',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rj',
    maintainer_email='rj@rb2.local',
    description='RB2 base control and odometry nodes',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'cmd_vel_serial_node = rb2_base.cmd_vel_serial_node:main',
            'odometry_node = rb2_base.odometry_node:main',
            'wheel_ticks_json_node = rb2_base.wheel_ticks_json_node:main',
        ],
    },
)
