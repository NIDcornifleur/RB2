# Validation RB2 — SLAM manuel fonctionnel

Date : 2026-06-20

## État validé

Le SLAM manuel avec slam_toolbox a été démarré, configuré et activé avec succès.

État confirmé :

- slam_toolbox : active [3]
- /scan présent
- /imu présent
- /odom présent
- /map présent
- /map_metadata présent
- /pose présent
- sauvegarde de carte réussie avec map_saver_cli

## Cartes sauvegardées

Cartes générées et sauvegardées :

- rb2_map_20260620_121536.pgm
- rb2_map_20260620_121536.yaml
- rb2_map_20260620_121737.pgm
- rb2_map_20260620_121737.yaml

La carte rb2_map_20260620_121737 a été reçue comme une carte de 94 x 59 cellules à 0.05 m/pixel, soit environ 4.70 m x 2.95 m.

## Correction importante

Ajout du pont encodeurs vers ROS :

- esp32_panel.py écrit maintenant /tmp/rb2_wheel_ticks.json
- format : {"ok": true, "stamp": time.time(), "data": [FL, FR, RR, RL]}
- ajout d'un heartbeat pour garder le stamp frais même quand les roues sont immobiles
- objectif : maintenir /wheel_ticks et /odom actifs pour le SLAM

## Chaîne validée

ESP32 encodeurs
→ esp32_panel.py
→ /tmp/rb2_wheel_ticks.json
→ rb2_wheel_ticks_json_node
→ /wheel_ticks
→ rb2_odometry
→ /odom
→ slam_toolbox
→ /map
→ sauvegarde carte

## État réseau utilisé

La configuration terrain AP-only reste la configuration recommandée :

- AP RB2 : 10.42.0.1
- page Terrain : http://10.42.0.1:5051/terrain
- caméra Zero 2 W par Ethernet : 10.50.0.20
- Wi-Fi local wlan0 coupé en mode terrain
