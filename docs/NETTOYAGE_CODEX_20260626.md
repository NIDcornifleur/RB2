# Nettoyage Codex 2026-06-26

## Objectif

Ce document résume l'état du dépôt RB2 / RomBot2 avant le nettoyage avec Codex.

Il sert de point de repère pour éviter les modifications dangereuses. Il ne propose pas de refactoring global et ne change aucun comportement.

## État de sécurité

Branche de travail :

- nettoyage-codex-20260626

Tags de référence :

- rb2-fonctionnel-avant-codex-20260624
- stable-rb2-2026-06-18

Règle principale :

- ne jamais modifier le code fonctionnel sans lire le diff et tester RB2 ensuite.

## Fichiers et dossiers principaux

- README.md : résumé général du projet.
- esp32/ : firmware ESP32 pour moteurs, encodeurs, pan/tilt et watchdog.
- opt/rb2/ : scripts principaux côté Raspberry Pi.
- opt-rb2/ : variante ou copie partielle à vérifier.
- opt_rb2/ : autre variante ou copie partielle à vérifier.
- ros2/src/ : paquets ROS 2.
- systemd/ : services de production.
- docs/ : documentation de validation et de nettoyage.

## Fichier le plus sensible

Le fichier le plus sensible semble être :

- opt/rb2/esp32_panel.py

Il regroupe plusieurs responsabilités :

- interface web;
- page /terrain;
- commandes /cmd;
- STOP;
- caméra;
- LIDAR;
- retour WiFi;
- SLAM;
- arrêt système.

Ce fichier ne doit pas être refactorisé globalement.

## Zones à ne pas modifier sans validation réelle

- protocole /cmd JSON;
- commandes moteurs;
- STOP;
- watchdog moteur ESP32;
- limites pan/tilt;
- seuils LIDAR;
- retour WiFi;
- services systemd;
- scripts de démarrage;
- logique SLAM validée;
- flux caméra Zero.

## Nettoyage recommandé

Ordre prudent :

1. Documentation seulement.
2. Inventaire des dossiers doublons.
3. Inventaire des services systemd.
4. Petites corrections de commentaires.
5. Petites fonctions utilitaires seulement si le diff est évident.
6. Tests réels sur RB2 après chaque changement.

## Règle de travail

Une modification à la fois.

Après chaque modification, vérifier :

- git status
- git diff

Puis seulement si tout est clair :

- git add .
- git commit avec un message clair

## Note

Ce document est volontairement conservateur. RB2 fonctionne; le but du nettoyage est d'améliorer la lisibilité et la maintenance sans casser le comportement validé.

## Comparaison SHA256 des dossiers opt

Date : 2026-06-26

Comparaison effectuée sur le dépôt local Windows dans la branche nettoyage-codex-20260626.

### Résultat

Les fichiers suivants sont identiques bit pour bit entre leurs copies respectives :

- esp32_panel.py
  - opt/rb2
  - opt-rb2
  - opt_rb2
  - SHA256 : 96D5728657CDE388D44338B0C9F1343C85C13208CAD7676726A0D44F1D3CCECD

- rb2_lidar_json.py
  - opt/rb2
  - opt-rb2
  - SHA256 : 21F8A21CCDC5A32669A18E548FB0249DF23748860D8D463A7AC79188F4C7FFA3

- rb2_wifi_dual_loss_return.py
  - opt/rb2
  - opt-rb2
  - SHA256 : DBF6FCC542C953F39587F364ED25C0207069464C621A96BA7970F045CB342E3E

### Fichier unique

Le fichier suivant est présent seulement dans opt-rb2 :

- rb2_lidar_map_json.py
  - SHA256 : 619BC93F4A46877A5A4860F144D8D948E1C76C31875EE31B75FC239949E7041C

### Conclusion provisoire

opt/rb2 semble être le dossier canonique de production, car les services systemd pointent normalement vers /opt/rb2.

Cependant, le dépôt contient une incohérence : rb2_lidar_map_json.py est absent de opt/rb2, mais présent dans opt-rb2.

Avant toute suppression de dossier, il faut vérifier sur le Pi5 si /opt/rb2/rb2_lidar_map_json.py existe réellement en production.

Aucun dossier ne doit être supprimé avant cette vérification.

## Vérification production Pi5 : rb2_lidar_map_json.py

Date : 2026-06-26

Le fichier de production suivant existe sur le Pi5 :

- /opt/rb2/rb2_lidar_map_json.py

Empreinte SHA256 relevée sur le Pi5 :

- 334200be21f0c3baeaca7a4a752cffce4d685a75fd9cb4068299b25c0ad42956

Cette empreinte est différente de celle du fichier présent dans le dépôt PC sous opt-rb2 :

- 619BC93F4A46877A5A4860F144D8D948E1C76C31875EE31B75FC239949E7041C

Conclusion :

- le fichier opt-rb2/rb2_lidar_map_json.py du dépôt PC n'est pas la même version que le fichier actif en production sur le Pi5;
- il ne faut pas remplacer le fichier du Pi5 par la version opt-rb2 du dépôt;
- une copie de preuve de la version production a été ajoutée sous production_snapshots/opt_rb2_20260626/rb2_lidar_map_json.py.
