# Routes Flask de esp32_panel.py - 2026-06-26

## Objectif

Ce document inventorie les routes Flask déclarées dans :

- opt/rb2/esp32_panel.py

Aucune modification fonctionnelle n'a été faite dans le code.

Le but est de documenter les points d'entrée du panneau RB2 avant tout nettoyage futur.

## Commandes et sécurité

| Route | Fonction | Méthodes | Rôle probable | Criticité | Ne pas modifier sans test réel |
|---|---|---|---|---|---|
| `/cmd` | `command` | POST | Envoi commandes ESP32, moteurs, pan/tilt, relais | critique | protocole JSON, `cmd`, séquences, timestamps, commandes moteur |
| `/stop` | `stop` | GET, POST | STOP immédiat via ESP32 | critique | comportement STOP, `d0,0`, `esp32.stop()` |
| `/drive_time` | `drive_time` | GET | Synchronisation temps navigateur/serveur pour commandes périmables | critique | calcul `server_ms`, `max_age_ms` |
| `/drive_safety_status` | `drive_safety_status` | GET | Diagnostic sécurité commandes moteur | importante | état séquences, rejets, derniers STOP |
| `/encoders` | `encoders` | GET | Lecture encodeurs et odométrie locale | importante | inversion FR/RR, format JSON, écriture ticks |

## Trace, rejeu et retour

| Route | Fonction | Méthodes | Rôle probable | Criticité | Ne pas modifier sans test réel |
|---|---|---|---|---|---|
| `/trace_follow_preview` | `trace_follow_preview` | GET | Prévisualisation suivi trace | importante | parsing traces, seuils LIDAR, odométrie |
| `/trace_follow_status` | `trace_follow_status` | GET | État du suivi/rejeu actif | importante | format JSON attendu par UI |
| `/trace_follow_start` | `trace_follow_start` | POST | Démarrage suivi trace | critique | thread, STOP, LIDAR, commandes moteur |
| `/trace_follow_stop` | `trace_follow_stop` | GET, POST | Arrêt suivi/rejeu | critique | STOP burst, état thread |
| `/trace_return_preview` | `trace_return_preview` | GET | Prévisualisation retour trace inverse | importante | inversion commandes, calcul segments |
| `/trace_return_start` | `trace_return_start` | POST | Démarrage retour trace inverse | critique | moteur, STOP, LIDAR |
| `/trace_return_forward_preview` | `trace_return_forward_preview` | GET | Prévisualisation retour avant avec demi-tour | importante | demi-tour, odométrie, LIDAR |
| `/trace_return_forward_start` | `trace_return_forward_start` | POST | Démarrage retour avant | critique | commande demi-tour, STOP, LIDAR |
| `/trace_status` | `trace_status` | GET | État trace passive | importante | fichiers trace, PID |
| `/trace_start` | `trace_start` | POST | Démarrage trace passive | importante | chemins trace, processus |
| `/trace_stop` | `trace_stop` | POST | Arrêt trace passive | importante | PID, fichiers trace |
| `/trace_mark` | `trace_mark` | POST | Marqueur dans trace | secondaire | format trace |
| `/photo_mark` | `photo_mark` | POST | Marqueur photo lié à trace | secondaire | association photo/trace |

## Caméra

| Route | Fonction | Méthodes | Rôle probable | Criticité | Ne pas modifier sans test réel |
|---|---|---|---|---|---|
| `/zero_cam_stream.mjpg` | `zero_cam_stream` | GET | Proxy flux MJPEG Zero 2 W | importante | URL `10.50.0.20`, streaming |
| `/zero_cam_status` | `zero_cam_status` | GET | Statut caméra Zero | importante | format JSON proxy |
| `/zero_photo` | `zero_photo` | POST | Déclenche photo Zero | importante | endpoint Zero |
| `/zero_video_toggle` | `zero_video_toggle` | POST | Démarre/arrête vidéo Zero | importante | endpoint Zero |
| `/zero_video_status` | `zero_video_status` | GET | État vidéo Zero | secondaire | format JSON |
| `/zero_captures_list` | `zero_captures_list` | GET | Liste captures Zero | secondaire | endpoint captures |
| `/zero_captures_file/<kind>/<path:filename>` | `zero_captures_file` | GET | Téléchargement photo/vidéo | secondaire | validation `kind`, échappement filename |
| `/zero_captures_zip` | `zero_captures_zip` | POST | Archive captures Zero | secondaire | JSON transmis au Zero |
| `/zero_captures_delete` | `zero_captures_delete` | POST | Suppression captures Zero | importante | suppression distante |
| `/captures` | `captures_page` | GET | Page captures | secondaire | HTML/JS |
| `/zero_cam_restart` | `zero_cam_restart` | POST | Redémarrage caméra Zero | importante | commande distante/service Zero |

## Terrain et LIDAR

| Route | Fonction | Méthodes | Rôle probable | Criticité | Ne pas modifier sans test réel |
|---|---|---|---|---|---|
| `/terrain` | `terrain_page` | GET | Interface terrain principale | critique | HTML/CSS/JS, commandes, STOP |
| `/terrain_status` | `terrain_status` | GET | État global terrain | critique | LIDAR, IMU, caméra, UI |
| `/lidar` | `lidar_status` | GET | Statut LIDAR JSON simple | critique | `/tmp/rb2_lidar.json`, seuils |
| `/lidar_map` | `lidar_map_status` / override final | GET | Carte LIDAR et clearance | critique | format JSON, override final, distances |
| `/lidar_drive` | `lidar_drive_page` | GET | Page observation LIDAR | importante | HTML/JS LIDAR |
| `/imu_json` | `imu_json_status` | GET | Statut IMU JSON | importante | fichier `/tmp`, format UI |

## SLAM

| Route | Fonction | Méthodes | Rôle probable | Criticité | Ne pas modifier sans test réel |
|---|---|---|---|---|---|
| `/slam_status` | `slam_status` | GET | État service SLAM et `/map` | importante | systemd, ROS 2 lifecycle |
| `/slam_start` | `slam_start` | POST | Démarrage SLAM en arrière-plan | critique | sudo, `/usr/local/sbin/rb2-slam-start-bg` |
| `/slam_stop` | `slam_stop` | POST | Arrêt `rb2-slam.service` | importante | systemd |
| `/slam_save_map` | `slam_save_map` | POST | Sauvegarde carte `/map` | importante | écrit helper, cartes, ROS 2 |
| `/slam_download_png` | `slam_download_png` | GET | Téléchargement dernière carte PNG | secondaire | chemins cartes, markers |

## Réseau et retour Wi-Fi

| Route | Fonction | Méthodes | Rôle probable | Criticité | Ne pas modifier sans test réel |
|---|---|---|---|---|---|
| `/operator_heartbeat` | `operator_heartbeat` | GET, POST | Heartbeat opérateur terrain | critique | retour Wi-Fi, client IP |
| `/wifi_return_status` | `wifi_return_status` | GET | Statut retour Wi-Fi | critique | états retour, activité conduite |
| `/wifi_return_ack` | `wifi_return_ack` | GET, POST | Acquittement retour Wi-Fi | importante | remise à zéro états |
| `/wifi_return_arm` | `wifi_return_arm` | POST | Armement retour Wi-Fi | critique | sécurité retour |
| `/rb2_network/status` | `rb2_network_status` | GET | Statut Wi-Fi local | importante | `wlan0`, UI |
| `/rb2_network/terrain` | `rb2_network_terrain` | POST | Mode réseau terrain | importante | script `/usr/local/sbin/rb2-wifi-mode` |
| `/rb2_network/bureau` | `rb2_network_bureau` | POST | Mode réseau bureau | importante | script réseau |
| `/rb2_network/toggle` | `rb2_network_toggle` | POST | Bascule Wi-Fi local | importante | ne pas toucher AP RB2 |

## Arrêt système

| Route | Fonction | Méthodes | Rôle probable | Criticité | Ne pas modifier sans test réel |
|---|---|---|---|---|---|
| `/system_shutdown_all` | `system_shutdown_all` | POST | Arrêt complet Zero 2 W puis Pi 5 | critique | SSH Zero, shutdown Pi5, thread arrière-plan |

## Autres routes

| Route | Fonction | Méthodes | Rôle probable | Criticité | Ne pas modifier sans test réel |
|---|---|---|---|---|---|
| `/` | `index` | GET | Page d'accueil/panneau simple | secondaire | liens/UI |
| `/light` | `light_control` | GET, POST | Contrôle lumière/relais | importante | GPIO/relais |
| `/relay2` | `relay2_control` | GET, POST | Contrôle relais 2 | importante | GPIO/relais |
| `/relay_light` | `relay_light_proxy` | GET, POST | Proxy lumière/relais depuis UI | importante | compatibilité UI |
| `/relay2_proxy` | `relay2_proxy` | GET, POST | Proxy relais 2 | importante | compatibilité UI |

## Conclusion

Les routes les plus critiques sont :

- `/cmd`
- `/stop`
- `/terrain`
- `/terrain_status`
- `/lidar`
- `/lidar_map`
- `/trace_follow_start`
- `/trace_return_start`
- `/operator_heartbeat`
- `/wifi_return_status`
- `/wifi_return_arm`
- `/system_shutdown_all`

Aucune de ces routes ne doit être modifiée sans test réel sur RB2.

Avant tout nettoyage futur de `esp32_panel.py`, cette table doit être consultée.
