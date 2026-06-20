# Validation RB2 — Retour WiFi phase 2A

Date : 2026-06-20

## Fonction validée

Le système Retour WiFi phase 2A est fonctionnel.

## Principe

Le retour WiFi est maintenant armé par défaut.

Le bouton dans la barre du haut indique l'état :

- bleu : Retour WiFi prêt;
- rouge : RETOUR en cours ou retour automatique déjà effectué.

Le bouton ne sert pas à déclencher le retour pendant une perte WiFi. Le retour est déclenché localement par le Pi5 lorsque le heartbeat opérateur disparaît.

## Détection

La page /terrain envoie un heartbeat régulier au Pi5.

Si le heartbeat disparaît plus longtemps que le seuil configuré, RB2 considère que le lien opérateur est perdu.

## Action automatique

En cas de perte heartbeat :

- STOP immédiat;
- recul lent limité avec la commande d-20,-20;
- STOP entre les impulsions;
- arrêt si le heartbeat revient;
- arrêt si la sécurité LIDAR arrière bloque;
- bouton rouge RETOUR pour indiquer qu'un retour a eu lieu.

## Sécurité

Le retour automatique est volontairement limité.

Le système utilise les sécurités déjà présentes :

- STOP d0,0;
- rafale STOP;
- vérification LIDAR arrière;
- arrêt dès que le signal opérateur revient.

## Interface

Le bouton Retour WiFi est placé dans la barre du haut.

L'espacement de la barre du haut a été ajusté afin que le texte État RB2 reste visible.

## État validé

- bouton Retour WiFi fonctionnel;
- retour automatique testé et fonctionnel;
- affichage bleu/rouge fonctionnel;
- barre du haut corrigée;
- aucun déplacement d'image/carte LIDAR causé par le bouton.
