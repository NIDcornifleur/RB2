# Services systemd RB2 - 2026-06-26

## Objectif

Ce document inventorie les services systemd présents dans le dépôt RB2.

Le but est de savoir :

- quels services existent;
- quelle commande chaque service lance;
- quels scripts sont présents dans le dépôt;
- quels scripts manquent encore;
- quels services sont critiques pour le fonctionnement de RB2.

Aucun comportement du robot n'est modifié par ce document.

## Services trouvés

Le dossier systemd contient 13 services :

- rb2-ap-ip.service
- rb2-bringup.service
- rb2-esp32-panel.service
- rb2-imu-json.service
- rb2-lidar-json.service
- rb2-lidar-map-json.service
- rb2-lidar-ros.service
- rb2-shutdown-zero-before-pi5.service
- rb2-slam.service
- rb2-usb-camera.service
- rb2-web-teleop.service
- rb2-wifi-dual-loss-return.service
- rb2-wlan0-powersave-off.service

Un override est aussi présent :

- systemd/rb2-bringup.service.d/override.conf

## Services très critiques

### rb2-esp32-panel.service

Commande :

- /usr/bin/python3 /opt/rb2/esp32_panel.py

Script dans le dépôt :

- opt/rb2/esp32_panel.py

Rôle :

- panneau web RB2;
- page /terrain;
- commandes /cmd;
- STOP;
- caméra;
- LIDAR;
- SLAM;
- arrêt système;
- communication ESP32.

Statut :

- très critique;
- à ne pas modifier sans test réel.

### rb2-wifi-dual-loss-return.service

Commande :

- /usr/bin/python3 /opt/rb2/rb2_wifi_dual_loss_return.py

Script dans le dépôt :

- opt/rb2/rb2_wifi_dual_loss_return.py

Rôle :

- surveillance perte Wi-Fi opérateur;
- retour de sécurité;
- dépendance avec /cmd, /stop, LIDAR et état opérateur.

Statut :

- très critique;
- à ne pas modifier sans test réel.

### rb2-lidar-json.service

Commande :

- /opt/rb2/rb2_lidar_json.py après chargement ROS 2

Script dans le dépôt :

- opt/rb2/rb2_lidar_json.py

Rôle :

- production de l'état LIDAR JSON;
- utilisé par le panneau web et certaines sécurités.

Statut :

- critique.

### rb2-lidar-map-json.service

Commande :

- /opt/rb2/rb2_lidar_map_json.py après chargement ROS 2

Script dans le dépôt :

- opt/rb2/rb2_lidar_map_json.py

Rôle :

- production de /tmp/rb2_lidar_map.json;
- affichage carte LIDAR dans /terrain.

Statut :

- critique;
- la version production Pi5 a été importée dans opt/rb2.

### rb2-bringup.service

Commande :

- /home/rj/rb2_scripts/start_rb2_bringup.sh

Script dans le dépôt :

- absent

Rôle :

- démarrage du bringup ROS 2;
- probablement LIDAR, IMU, odométrie et TF selon la configuration.

Statut :

- très critique;
- script à récupérer depuis le Pi5.

### rb2-shutdown-zero-before-pi5.service

Commande :

- ExecStart=/bin/true
- ExecStop=/usr/local/sbin/rb2-shutdown-zero-before-pi5.sh

Script équivalent dans le dépôt :

- usr-local-sbin/rb2-shutdown-zero-before-pi5.sh

Rôle :

- arrêt propre du Raspberry Pi Zero 2 W avant extinction du Pi5.

Statut :

- critique pour arrêt propre.

## Services importants

### rb2-ap-ip.service

Commande :

- /usr/sbin/ip addr add 10.42.0.1/24 dev wlxXXXXXXXXXXXX

Script dans le dépôt :

- aucun script, commande système directe.

Rôle :

- configuration IP du point d'accès RB2.

Statut :

- important pour le mode terrain AP.

### rb2-wlan0-powersave-off.service

Commande :

- /sbin/iw dev wlan0 set power_save off

Script dans le dépôt :

- aucun script, commande système directe.

Rôle :

- désactivation de l'économie d'énergie Wi-Fi;
- utile pour stabilité réseau.

Statut :

- important.

### rb2-slam.service

Commande :

- /home/rj/rb2_scripts/start_rb2_slam.sh

Script dans le dépôt :

- absent

Rôle :

- démarrage SLAM manuel.

Statut :

- important;
- script à récupérer depuis le Pi5.

### rb2-imu-json.service

Commande :

- python3 /opt/rb2/rb2_imu_json.py après chargement ROS 2

Script dans le dépôt :

- absent

Rôle :

- production JSON liée à l'IMU.

Statut :

- important ou ancien;
- à vérifier sur le Pi5.

### rb2-usb-camera.service

Commande :

- /usr/bin/python3 /opt/rb2/rb2_usb_camera.py

Script dans le dépôt :

- absent

Rôle :

- caméra USB, possiblement ancien ou incomplet dans le dépôt actuel.

Statut :

- à clarifier.

## Services à clarifier

### rb2-lidar-ros.service

Commande :

- /home/rj/rb2_scripts/start_rb2_bringup.sh

Script dans le dépôt :

- absent

Remarque :

- utilise la même commande que rb2-bringup.service;
- pourrait être un ancien service, un doublon ou une variante.

Statut :

- à clarifier avant suppression.

### rb2-web-teleop.service

Commande :

- /home/rj/rb2_web/start_rb2_web_teleop.sh

Script dans le dépôt :

- absent

Rôle probable :

- interface web ROS 2 séparée ou ancienne.

Statut :

- à clarifier avant suppression.

## Override systemd

### rb2-bringup.service.d/override.conf

Contenu observé :

- TimeoutStopSec=10
- KillMode=control-group
- KillSignal=SIGINT
- SendSIGKILL=yes

Rôle :

- contrôle l'arrêt propre du bringup ROS 2.

Statut :

- à conserver;
- ne pas modifier sans raison claire.

## Scripts absents du dépôt

Les chemins suivants sont référencés par les services, mais les scripts ne sont pas présents dans le dépôt actuel :

- /home/rj/rb2_scripts/start_rb2_bringup.sh
- /home/rj/rb2_scripts/start_rb2_slam.sh
- /home/rj/rb2_web/start_rb2_web_teleop.sh
- /opt/rb2/rb2_imu_json.py
- /opt/rb2/rb2_usb_camera.py

## Décision provisoire

Le dépôt doit être enrichi avec les scripts réellement présents en production sur le Pi5, mais seulement après vérification.

Priorité de récupération :

1. /home/rj/rb2_scripts/start_rb2_bringup.sh
2. /home/rj/rb2_scripts/start_rb2_slam.sh
3. /opt/rb2/rb2_imu_json.py
4. /opt/rb2/rb2_usb_camera.py
5. /home/rj/rb2_web/start_rb2_web_teleop.sh

## Règle de prudence

Ne pas supprimer de service systemd tant que les commandes suivantes n'ont pas été vérifiées sur le Pi5 :

- systemctl is-enabled NOM_DU_SERVICE
- systemctl is-active NOM_DU_SERVICE
- systemctl status NOM_DU_SERVICE --no-pager
- ls -l du script appelé

Le dépôt doit d'abord devenir complet et documenté avant de retirer les services anciens ou doublons.
