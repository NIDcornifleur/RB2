# RB2 / RomBot2

Robot d’inspection d’espaces restreints créé par Roméo St-Cyr.

## État stable sauvegardé

- Raspberry Pi 5 principal sous Ubuntu / ROS 2
- Interface web `/terrain`
- ESP32 pour moteurs, encodeurs, pan-tilt et relais
- LIDAR LD19 via ROS 2 `/scan`
- Zero 2 W caméra relié au Pi5 par Ethernet direct
- Pi5 eth0 : `10.50.0.1`
- Zero 2 W eth0 : `10.50.0.20`
- Caméra Zero : `http://10.50.0.20:8080`
- Flux caméra relayé : `/zero_cam_stream.mjpg`
- Page terrain : `/terrain`
- Page LIDAR : `/lidar_drive`

## Services principaux

- `rb2-esp32-panel.service`
- `rb2-bringup.service`
- `rb2-lidar-json.service`
- `rb2-lidar-map-json.service`

## Notes

Ce dépôt sert à conserver l’état stable du projet RB2 et à faciliter les futures modifications avec GitHub/Codex.
