# Validation RB2 — bouton Restart Camera OK

Date : 2026-06-20

## État validé

Le bouton Restart Camera a été ajouté dans la barre du haut de la page /terrain, près des boutons ARRÊT RB2, LIDAR et CAMÉRA.

Le bouton redémarre seulement le service caméra du Raspberry Pi Zero 2 W.

## Fonctionnement

Route web ajoutée :

- /zero_cam_restart

Script appelé côté Pi5 :

- /usr/local/sbin/rb2-zero-cam-restart

Service redémarré côté Zero 2 W :

- rb2-zero-cam.service

Adresse caméra Zero :

- 10.50.0.20:8080

## Validation

Le script :

- vérifie que le Zero 2 W répond au ping;
- lance le redémarrage de rb2-zero-cam.service par SSH;
- attend le retour de /status;
- attend le retour de /stream.mjpg;
- retourne OK seulement lorsque la caméra répond de nouveau.

## Résultat terrain

Après gel de l'image caméra, l'image est revenue sans redémarrage complet du RB2.

Le bouton Restart Camera fonctionne.

## Points importants

Ce bouton ne redémarre pas :

- le Pi5;
- le SLAM;
- les moteurs;
- l'AP RB2;
- le robot complet.

Il redémarre uniquement le service caméra du Zero 2 W.
