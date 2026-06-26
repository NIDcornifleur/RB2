# Analyse esp32_panel.py - 2026-06-26

## Objectif

Ce document cartographie le fichier :

- opt/rb2/esp32_panel.py

Aucune modification fonctionnelle n'a été faite dans ce fichier.

Le but est de comprendre sa structure avant tout nettoyage de code.

## Vue générale

esp32_panel.py est le fichier central du panneau RB2 côté Raspberry Pi 5.

Il regroupe plusieurs responsabilités :

- serveur Flask;
- contrôle ESP32;
- interface /terrain;
- commandes moteurs;
- STOP;
- encodeurs et odométrie;
- LIDAR;
- traces, rejeu et retour;
- caméra Zero;
- SLAM;
- retour Wi-Fi;
- arrêt complet RB2;
- injection HTML, CSS et JavaScript.

Ce fichier est très sensible. Il ne doit pas être refactorisé globalement.

## Grandes sections fonctionnelles

### Début du fichier

Rôle général :

- imports;
- création Flask;
- instance RB2ESP32;
- sécurité commandes moteur;
- journalisation des commandes;
- fonction critique rb2_safe_drive_send.

### Suivi trace, LIDAR et odométrie

Rôle général :

- suivi de trace;
- lecture LIDAR de sécurité;
- limitation vitesse;
- odométrie depuis encodeurs;
- STOP burst pour trace et rejeu.

### HTML principal et logique JavaScript

Rôle général :

- relais;
- lumières;
- interface web principale;
- logique de conduite;
- pan/tilt;
- encodeurs;
- calcul odométrie côté interface.

### Routes Flask de base

Routes principales :

- /cmd
- /stop
- /encoders
- /drive_safety_status
- /light
- /relay2
- /drive_time
- /imu_json
- /lidar

### Terrain, LIDAR et caméra

Rôle général :

- page /terrain;
- statut terrain;
- carte LIDAR;
- flux caméra;
- captures photo et vidéo;
- page /lidar_drive.

### ROS 2 et SLAM

Rôle général :

- commandes ROS 2;
- démarrage SLAM;
- arrêt SLAM;
- sauvegarde de carte;
- téléchargement PNG.

### Réseau, retour Wi-Fi et arrêt système

Rôle général :

- heartbeat opérateur;
- statut retour Wi-Fi;
- bascule réseau terrain/bureau;
- arrêt complet Zero 2 W puis Pi5.

## Routes Flask importantes

### Commandes et sécurité

- /cmd
- /stop
- /drive_safety_status
- /encoders

### Trace et rejeu

- /trace_start
- /trace_stop
- /trace_status
- /trace_mark
- /photo_mark
- /trace_follow_preview
- /trace_follow_status
- /trace_follow_start
- /trace_follow_stop
- /trace_return_preview
- /trace_return_start
- /trace_return_forward_preview
- /trace_return_forward_start

### Caméra Zero

- /zero_cam_stream.mjpg
- /zero_cam_status
- /zero_photo
- /zero_video_toggle
- /zero_video_status
- /zero_captures_list
- /zero_captures_file/<kind>/<path:filename>
- /zero_captures_zip
- /zero_captures_delete
- /captueres
- /zero_cam_restart

Note :

- vérifier l'orthographe réelle de toutes les routes avant toute modification.

### Terrain et LIDAR

- /terrain
- /terrain_status
- /lidar_map
- /lidar_drive

### SLAM

- /slam_status
- /slam_start
- /slam_stop
- /slam_save_map
- /slam_download_png

### Retour Wi-Fi et réseau

- /operator_heartbeat
- /wifi_return_status
- /wifi_return_ack
- /wifi_return_arm
- /rb2_network/status
- /rb2_network/terrain
- /rb2_network/bureau
- /rb2_network/toggle

### Arrêt système

- /system_shutdown_all

## Zones très critiques

Les éléments suivants ne doivent pas être modifiés sans validation réelle sur RB2 :

- /cmd
- /stop
- rb2_safe_drive_send
- rb2_is_stop_drive
- rb2_trace_follow_send_stop_burst
- rb2_trace_follow_request_stop
- rb2_trace_follow_lidar_allows
- constantes TRACE_FOLLOW_*
- constantes RB2_WIFI_RETURN_*
- commandes d0,0
- commandes d-20,-20
- routes Flask existantes
- HTML, CSS et JavaScript terrain
- pan/tilt JavaScript
- SLAM start, stop et save
- system_shutdown_all
- rb2_lidar_map_status_with_clearance

## Moteurs

Fonctions et routes importantes :

- rb2_parse_drive_command
- rb2_is_stop_drive
- rb2_safe_drive_send
- command
- drive_time
- drive_safety_status

La fonction rb2_safe_drive_send est critique.

Elle gère notamment :

- format moteur dG,D;
- détection d0,0;
- séquence drive_seq;
- token client;
- timestamp navigateur et serveur;
- rejet des commandes périmées;
- garde LIDAR avant envoi moteur;
- mémorisation de la dernière commande moteur;
- envoi série non bloquant à l'ESP32.

## STOP

Le STOP est l'une des zones les plus dangereuses à modifier.

Points sensibles :

- d0,0 doit rester accepté;
- /stop appelle esp32.stop();
- le STOP opérateur doit arrêter le suivi trace;
- les retours trace et Wi-Fi utilisent des bursts STOP.

## LIDAR

Le LIDAR intervient dans :

- sécurité moteur;
- suivi trace;
- retour trace;
- retour avant;
- retour Wi-Fi;
- affichage terrain;
- page /lidar_drive;
- route /lidar_map.

Constantes sensibles :

- TRACE_FOLLOW_FRONT_MIN_CM
- TRACE_FOLLOW_BACK_MIN_CM
- TRACE_FOLLOW_LIDAR_MAX_AGE_S

Attention :

- certaines constantes semblent redéfinies plus loin dans le fichier;
- ne pas nettoyer ces redéfinitions sans confirmer quelle valeur est active à l'exécution.

## Caméra

La caméra Zero dépend de routes proxy Flask et d'une adresse réseau critique :

- http://10.50.0.20:8080

Risque principal :

- casser les endpoints attendus par /terrain.

## Pan/Tilt

Le pan/tilt est piloté notamment par les commandes ESP32 :

- p...
- t...

Les limites existent côté interface, mais aussi côté firmware ESP32.

Ne pas modifier les limites pan/tilt dans esp32_panel.py sans validation mécanique réelle.

## Retour Wi-Fi

Le fichier contient encore une logique interne de retour Wi-Fi.

Constantes sensibles :

- RB2_WIFI_RETURN_LOSS_AFTER_S
- RB2_WIFI_RETURN_PULSE_S
- RB2_WIFI_RETURN_MAX_PULSES
- RB2_WIFI_RETURN_RECENT_DRIVE_WINDOW_S
- RB2_WIFI_RETURN_CMD

Note :

- le retour Wi-Fi interne semble désactivé ou remplacé par rb2-wifi-dual-loss-return;
- les routes et états restent présents;
- ne pas supprimer sans test réel.

## SLAM

Le SLAM dépend notamment de :

- /opt/ros/jazzy/setup.bash
- /home/rj/rb2_ros2_ws/install/setup.bash
- rb2-slam.service
- /home/rj/rb2_maps
- /home/rj/rb2_scripts

Zone sensible :

- mélange Flask, systemd, ROS 2 et écriture de fichiers.

## Arrêt système

Route critique :

- /system_shutdown_all

Comportement général :

- tentative d'arrêt du Zero 2 W par SSH;
- délai d'attente;
- arrêt du Pi5.

Ne pas modifier sans test réel.

## Nettoyage permis plus tard

Nettoyages possibles, mais seulement de façon limitée :

- documentation externe;
- table des routes Flask;
- table des constantes sensibles;
- table des chemins absolus;
- table des dépendances externes;
- documentation du retour Wi-Fi interne versus service externe;
- documentation des injections HTML/JS de fin de fichier.

## Nettoyage interdit pour l'instant

Ne pas faire pour l'instant :

- refactoring global;
- découpage du fichier;
- renommage de fonctions;
- changement des routes;
- changement de constantes;
- suppression de blocs;
- modification HTML/CSS/JS terrain;
- modification STOP;
- modification /cmd.

## Conclusion

esp32_panel.py fonctionne comme un panneau central historique, construit par ajouts successifs.

La prochaine étape prudente n'est pas de modifier ce fichier, mais de mieux documenter ses routes, ses constantes sensibles et ses dépendances.

Aucune modification directe ne doit être faite sans test réel sur RB2.
