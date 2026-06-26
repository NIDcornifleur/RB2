# Dépendances de esp32_panel.py - 2026-06-26

## Objectif

Ce document inventorie les chemins absolus et dépendances externes du fichier :

- opt/rb2/esp32_panel.py

Aucune modification fonctionnelle n'a été faite dans le code.

Le but est de documenter les dépendances critiques avant tout nettoyage futur.

## Dépendances critiques principales

Les dépendances les plus critiques identifiées sont :

- /opt/rb2/esp32_panel.py
- module Python rb2_esp32
- /tmp/rb2_lidar.json
- /tmp/rb2_lidar_map.json
- /tmp/rb2_wheel_ticks.json
- /opt/ros/jazzy/setup.bash
- /home/rj/rb2_ros2_ws/install/setup.bash
- /usr/local/sbin/rb2-slam-start-bg
- /usr/local/sbin/rb2-wifi-mode
- 10.50.0.20:8080
- ssh rj@10.50.0.20
- sudo -n
- rb2-slam.service

## Fichiers sous /opt/rb2

| Chemin | Rôle | Criticité | État dans le dépôt |
|---|---|---|---|
| /opt/rb2/esp32_panel.py | Panneau Flask principal RB2 | critique | présent : opt/rb2/esp32_panel.py |
| /opt/rb2/rb2_lidar_json.py | Pont LIDAR JSON | critique | présent |
| /opt/rb2/rb2_lidar_map_json.py | Carte LIDAR JSON | importante | présent, version production Pi5 |
| /opt/rb2/rb2_wifi_dual_loss_return.py | Watchdog retour Wi-Fi externe | critique | présent |
| /opt/rb2/rb2_imu_json.py | Pont IMU JSON | importante | présent |
| /opt/rb2/rb2_usb_camera.py | Caméra USB | à clarifier | présent |
| /opt/rb2/traces | Dossier traces | importante | dossier runtime absent du dépôt |
| /opt/rb2/rb2_esp32.py | Module Python ESP32 | critique | à vérifier, probablement absent du dépôt |

## Point critique : rb2_esp32.py

Le fichier esp32_panel.py dépend du module Python :

- rb2_esp32

Ce module semble nécessaire pour :

- créer l'instance RB2ESP32();
- envoyer les commandes à l'ESP32;
- gérer /cmd;
- gérer STOP;
- lire les encodeurs;
- contrôler les relais, moteurs et pan/tilt selon l'architecture du panneau.

Décision :

- vérifier immédiatement si /opt/rb2/rb2_esp32.py existe sur le Pi5;
- si oui, le récupérer dans opt/rb2/rb2_esp32.py du dépôt;
- ne pas modifier ce fichier avant documentation et comparaison.

## Fichiers runtime sous /tmp

Ces fichiers sont produits ou lus au fonctionnement. Ils ne doivent pas être versionnés comme fichiers statiques.

| Chemin | Rôle | Criticité |
|---|---|---|
| /tmp/rb2_lidar.json | Distances LIDAR utilisées par sécurité et trace | critique |
| /tmp/rb2_lidar_map.json | Données carte LIDAR | importante |
| /tmp/rb2_wheel_ticks.json | Ticks roues pour ROS/odométrie | importante |
| /tmp/rb2_trace_passive.pid | PID trace passive | importante |
| /tmp/rb2_trace_encoder_error.log | Log erreurs encodeurs | secondaire |
| /tmp/rb2_trace_drive_error.log | Log erreurs trace conduite | secondaire |
| /tmp/rb2_wifi_return.log | Journal retour Wi-Fi interne | secondaire |
| /tmp/rb2_last_map_png.txt | Dernière carte SLAM PNG | secondaire |

## Fichiers et dossiers sous /home/rj

| Chemin | Rôle | Criticité | État dans le dépôt |
|---|---|---|---|
| /home/rj/rb2_ros2_ws/install/setup.bash | Workspace ROS 2 installé | critique | non versionné, dépend machine |
| /home/rj/rb2_maps | Cartes SLAM sauvegardées | importante | cartes copiées séparément |
| /home/rj/rb2_scripts/start_rb2_bringup.sh | Démarrage bringup ROS 2 | critique | présent : home-rj/rb2_scripts/start_rb2_bringup.sh |
| /home/rj/rb2_scripts/start_rb2_slam.sh | Démarrage SLAM | importante | présent : home-rj/rb2_scripts/start_rb2_slam.sh |
| /home/rj/rb2_scripts/rb2_save_map_direct.py | Helper généré par /slam_save_map | importante | généré runtime |
| /home/rj/rb2_web/start_rb2_web_teleop.sh | Web teleop séparé | à clarifier | présent : home-rj/rb2_web/start_rb2_web_teleop.sh |

## Scripts sous /usr/local/sbin

| Chemin | Rôle | Criticité | État dans le dépôt |
|---|---|---|---|
| /usr/local/sbin/rb2-slam-start-bg | Démarrage SLAM en arrière-plan | critique | présent : system_files/rb2-slam-start-bg |
| /usr/local/sbin/rb2-wifi-mode | Changement mode Wi-Fi terrain/bureau | importante | présent : system_files/rb2-wifi-mode |
| /usr/local/sbin/rb2-zero-cam-restart | Redémarrage caméra Zero | importante | présent : system_files/rb2-zero-cam-restart |
| /usr/local/sbin/rb2-shutdown-zero-before-pi5.sh | Arrêt Zero avant Pi5 | critique | présent : usr-local-sbin/rb2-shutdown-zero-before-pi5.sh |

## Services systemd

Services liés directement ou indirectement :

- rb2-esp32-panel.service
- rb2-bringup.service
- rb2-lidar-json.service
- rb2-lidar-map-json.service
- rb2-imu-json.service
- rb2-usb-camera.service
- rb2-wifi-dual-loss-return.service
- rb2-slam.service

Les services sont documentés dans :

- docs/SERVICES_SYSTEMD_20260626.md

## Dépendances ROS 2

| Ressource | Rôle | Criticité |
|---|---|---|
| /opt/ros/jazzy/setup.bash | Environnement ROS 2 Jazzy | critique |
| /home/rj/rb2_ros2_ws/install/setup.bash | Workspace RB2 installé | critique |
| ros2 lifecycle get /slam_toolbox | État lifecycle SLAM | importante |
| ros2 topic list | Vérification topics ROS | importante |
| /slam_toolbox | Noeud SLAM | importante |
| /map | Topic carte SLAM | importante |
| rclpy | Helper sauvegarde carte | importante |
| nav_msgs.msg.OccupancyGrid | Sauvegarde carte | importante |

## Dépendances réseau

| Ressource | Rôle | Criticité |
|---|---|---|
| 10.50.0.20 | IP Zero 2 W caméra | critique |
| 10.50.0.20:8080 | Service caméra Zero | importante |
| wlan0 | Wi-Fi local Pi5 | importante |
| wlxXXXXXXXXXXXX | Interface AP RB2 | critique pour terrain |
| ssh rj@10.50.0.20 | Arrêt distant du Zero | critique |
| ping | Test client opérateur | importante |
| nmcli | Statut NetworkManager | secondaire |
| ip | Statut interface réseau | secondaire |

## Dépendances caméra Zero

Endpoints utilisés :

- http://10.50.0.20:8080/stream.mjpg
- http://10.50.0.20:8080/status
- http://10.50.0.20:8080/photo
- http://10.50.0.20:8080/video_toggle
- http://10.50.0.20:8080/video_status
- http://10.50.0.20:8080/captures/list
- http://10.50.0.20:8080/captures/file
- http://10.50.0.20:8080/captures/zip
- http://10.50.0.20:8080/captures/delete

Risque :

- toute modification des URLs ou du format JSON peut casser l'interface terrain.

## Dépendances sudo et système

| Ressource | Rôle | Criticité |
|---|---|---|
| sudo -n | Commandes non interactives depuis Flask | critique |
| systemctl | Contrôle services | importante |
| shutdown | Arrêt Pi5 et Zero | critique |
| bash -lc | Chargement environnements ROS | importante |
| ssh | Arrêt distant Zero | critique |
| ip | État réseau | secondaire |
| nmcli | État NetworkManager | secondaire |
| ping | Test lien client | importante |

## Conclusion

esp32_panel.py dépend d'un ensemble de fichiers, services, chemins, adresses IP et commandes système.

Le point le plus important découvert ici est la dépendance au module Python rb2_esp32.

Avant tout nettoyage de code, il faut vérifier et récupérer si nécessaire :

- /opt/rb2/rb2_esp32.py

Aucun nettoyage de esp32_panel.py ne doit commencer tant que cette dépendance centrale n'est pas documentée et versionnée.
