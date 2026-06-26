# Rapport de nettoyage structurel RB2 - 2026-06-26

## Objectif

Ce rapport résume la première phase de nettoyage du dépôt RB2 avec Codex.

Cette phase visait à rendre le dépôt plus clair, plus complet et plus restaurable, sans modifier le comportement fonctionnel du robot.

## Branche de travail

Branche utilisée :

- nettoyage-codex-20260626

La branche a été poussée vers GitHub.

## Point de retour stable

Point de référence avant nettoyage :

- rb2-fonctionnel-avant-codex-20260624

Ce tag reste le point de retour principal en cas de problème.

## Nettoyage effectué

### Dossier canonique opt/rb2

Le dossier retenu comme dossier principal est :

- opt/rb2

Raison :

- il correspond au chemin de production Linux /opt/rb2;
- les services systemd pointent vers /opt/rb2;
- il contient maintenant les scripts réellement utilisés en production.

### Dossiers redondants supprimés de la branche

Les anciens dossiers suivants ont été retirés de la branche de nettoyage :

- opt-rb2
- opt_rb2

Ces suppressions ne touchent pas au Pi5. Elles ne concernent que le dépôt Git dans la branche de nettoyage.

### Scripts de production ajoutés au dépôt

Les scripts suivants ont été récupérés depuis le Pi5 et ajoutés au dépôt :

- opt/rb2/rb2_lidar_map_json.py
- opt/rb2/rb2_imu_json.py
- opt/rb2/rb2_usb_camera.py
- home-rj/rb2_scripts/start_rb2_bringup.sh
- home-rj/rb2_scripts/start_rb2_slam.sh
- home-rj/rb2_web/start_rb2_web_teleop.sh

### Services systemd documentés

Les services systemd ont été inventoriés dans :

- docs/SERVICES_SYSTEMD_20260626.md

Les services réellement actifs sur le Pi5 ont été vérifiés.

### Documentation ajoutée

Documents ajoutés ou mis à jour :

- docs/NETTOYAGE_CODEX_20260626.md
- docs/DOUBLONS_OPT_20260626.md
- docs/SERVICES_SYSTEMD_20260626.md
- README.md

### Permissions exécutables corrigées

Les scripts Linux ont été marqués exécutables dans Git lorsque nécessaire.

Cela permet une restauration plus fidèle sur un système Linux.

## Ce qui n'a pas été modifié

Aucun changement volontaire de comportement n'a été fait dans cette phase.

N'ont pas été modifiés fonctionnellement :

- protocole /cmd;
- commandes moteurs;
- STOP;
- pan/tilt;
- seuils LIDAR;
- retour Wi-Fi;
- firmware ESP32;
- logique SLAM;
- logique caméra;
- services systemd actifs sur le Pi5.

## État actuel du dépôt

Le dépôt est maintenant plus cohérent :

- opt/rb2 est le dossier canonique;
- les scripts de production essentiels sont versionnés;
- les doublons opt ont été retirés de la branche;
- les services systemd sont documentés;
- le README reflète mieux la structure actuelle.

## Risques restants

Le fichier suivant reste très sensible :

- opt/rb2/esp32_panel.py

Il contient plusieurs responsabilités critiques :

- panneau web;
- page /terrain;
- /cmd;
- STOP;
- caméra;
- LIDAR;
- retour Wi-Fi;
- SLAM;
- arrêt système.

Il ne doit pas être refactorisé globalement.

## Prochaine phase recommandée

Avant de modifier du code Python, il est recommandé de faire une validation minimale sur RB2 :

- page /terrain accessible;
- caméra visible;
- STOP fonctionnel;
- avance/recul fonctionnels;
- pan/tilt fonctionnel;
- LIDAR affiché;
- services systemd actifs;
- aucun service en échec.

Ensuite seulement, un nettoyage très limité du code pourra être envisagé.

## Conclusion

La phase de nettoyage structurel est terminée.

Le dépôt est plus propre et mieux aligné avec la production, sans modification volontaire du comportement du robot.
