# Validation RB2 — Mode terrain AP seulement

Date : 2026-06-20

## État validé

Essai terrain effectué sur l'AP RB2 seulement. Résultat stable et concluant.

Configuration terrain validée :

- Page Terrain utilisée par l'AP RB2 : http://10.42.0.1:5051/terrain
- AP RB2 actif sur l'interface USB Wi-Fi : wlxXXXXXXXXXXXX
- Adresse AP RB2 : 10.42.0.1
- Wi-Fi local maison wlan0 désactivé en mode terrain
- Caméra Zero 2 W reliée par Ethernet direct
- Pi5 eth0 : 10.50.0.1
- Zero 2 W caméra : 10.50.0.20
- Ping Pi5 vers Zero 2 W autour de 0.8 à 1.0 ms, sans perte

## Modification interface

Ajout d'un bouton unique compact sur la page Terrain :

- Vert = Wi-Fi local wlan0 ON
- Rouge = Wi-Fi local wlan0 OFF
- Le bouton ne doit contrôler que wlan0
- Le bouton ne doit jamais toucher à l'AP RB2 wlxXXXXXXXXXXXX

## Règle opérationnelle

Pour les essais terrain, utiliser le mode AP seulement :

- wlan0 OFF
- AP RB2 actif
- caméra par Ethernet direct
- accès opérateur par http://10.42.0.1:5051/terrain

Cette configuration est considérée comme l'état stable à sauvegarder.
