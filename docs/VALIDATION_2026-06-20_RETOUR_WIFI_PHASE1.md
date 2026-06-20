# Validation RB2 — Retour WiFi phase 1

Date : 2026-06-20

## Fonction validée

Un bouton Retour WiFi a été ajouté dans le bloc du haut de la page /terrain.

## Comportement

- Bouton bleu : Retour WiFi désarmé
- Bouton rouge : RETOUR armé
- Le navigateur envoie un heartbeat opérateur à RB2
- RB2 peut détecter la présence ou la perte du lien opérateur
- Phase actuelle : détection seulement

## Sécurité

Aucun mouvement automatique n'est encore activé.

Le bouton ne commande pas les moteurs. Il arme seulement la surveillance de perte de lien.

## Routes ajoutées

- /operator_heartbeat
- /wifi_return_arm
- /wifi_return_status

## Prochaine étape

Phase 2 à venir :

- STOP immédiat si heartbeat perdu
- recul lent limité
- arrêt dès que le heartbeat revient
- arrêt si danger LIDAR
