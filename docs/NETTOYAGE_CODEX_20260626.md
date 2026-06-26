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
