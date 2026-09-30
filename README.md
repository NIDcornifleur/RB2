# RB2 / RomBot2

Dépôt de restauration et de maintenance du robot RB2.

RB2 est un robot d'inspection d'espaces restreints basé sur un Raspberry Pi 5, ROS 2, un ESP32 pour les moteurs, le pan-tilt et les encodeurs, un LIDAR LD19 et une caméra Zero 2 W.

## État actuel

Cette branche de nettoyage conserve l'état de production nettoyé du dépôt.

- `opt/rb2` est le dossier canonique pour les scripts de production RB2.
- Les anciennes copies `opt-rb2` et `opt_rb2` ont été retirées de la branche de nettoyage.
- Les scripts de production manquants ont été récupérés depuis le Pi5.
- Les services systemd sont conservés dans `systemd/`.
- Le firmware ESP32 est conservé dans `esp32/`.
- Le workspace ROS 2 est conservé dans `ros2/`.

## Points d'entrée principaux

- Interface terrain : `/terrain4` (page autonome légère, recommandée — voir `docs/TERRAIN4.md`)
- LIDAR / conduite : `/lidar_drive2` (SLAM, carte, TRACE, RETOUR)
- Panneau ESP32 : `opt/rb2/esp32_panel.py`
- Page terrain autonome : `opt/rb2/terrain4.html`
- LIDAR JSON : `opt/rb2/rb2_lidar_json.py`
- LIDAR carte JSON : `opt/rb2/rb2_lidar_map_json.py`
- IMU JSON : `opt/rb2/rb2_imu_json.py`
- Caméra USB : `opt/rb2/rb2_usb_camera.py`
- Retour Wi-Fi : `opt/rb2/rb2_wifi_dual_loss_return.py`
- Firmware ESP32 : `esp32/RB2_ESP32_WROOM_Moteurs_PanTilt_Encodeurs.ino`

## Documentation

Documents importants dans `docs/` :

- `SERVICES_SYSTEMD_20260626.md` : inventaire des services systemd et des scripts appelés.
- `DOUBLONS_OPT_20260626.md` : documentation des anciens dossiers `opt-rb2` et `opt_rb2`.
- `NETTOYAGE_CODEX_20260626.md` : notes de nettoyage prudent du dépôt.
- `VALIDATION_2026-06-20_*` : validations terrain et état stable.
- `CONFIG_ZERO_CAM.md` : configuration caméra Zero.
- `TERRAIN4.md` : page terrain autonome `/terrain4`, historique des correctifs et scripts d'installation.

## Maintenance

Avant toute modification, vérifier les documents dans `docs/` et conserver les comportements critiques :

- commandes moteur et protocole `/cmd`;
- comportement STOP;
- limites pan/tilt;
- seuils LIDAR;
- services systemd;
- scripts de production sous `opt/rb2`.

## Règle de prudence

Ne pas modifier directement `main` pour les travaux de nettoyage.

Travailler sur une branche dédiée, vérifier le diff, tester RB2, puis pousser vers GitHub.

## Copie publique

Ce dépôt est la copie publique du projet. Les valeurs propres à l'installation d'origine ont été remplacées et doivent être adaptées avant d'installer le code sur un autre robot :

- `WIFI-MAISON-2.4G` / `WIFI-MAISON-5G` : nom du réseau Wi-Fi local ;
- `wlxXXXXXXXXXXXX` : nom d'interface de la clé Wi-Fi du point d'accès `RB2-ROS` ;
- `*****` : mots de passe Wi-Fi et OTA dans le firmware ESP32.

Le pilote du LIDAR (`ros2/src/ldlidar_ros2`) est un sous-module : cloner avec `git clone --recurse-submodules`.

## Licence

Code publié sous licence MIT (voir `LICENSE`).
