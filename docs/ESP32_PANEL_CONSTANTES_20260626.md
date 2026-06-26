\# Constantes sensibles de esp32\_panel.py - 2026-06-26



\## Objectif



Ce document inventorie les constantes sensibles du fichier :



\- opt/rb2/esp32\_panel.py



Aucune modification fonctionnelle n'a été faite dans le code.



Le but est de documenter les valeurs critiques avant tout nettoyage futur.





\*\*Rapport D’analyse Des Constantes\*\*



Fichier analysé uniquement : `opt/rb2/esp32\_panel.py`.  

Aucune modification effectuée.



\*\*Moteurs\*\*



| Constante | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---:|---|---|---|

| `DRIVE\_CMD\_RE` | `^d(-?\\d+),(-?\\d+)$` | Format accepté pour commandes moteur directes `dG,D` | critique | Casser `/cmd`, accepter/refuser de mauvaises commandes |

| `DRIVE\_MAX\_AGE\_MS` | `6000` | Âge maximal d’une commande moteur non-stop | critique | Commandes trop vieilles acceptées ou commandes valides rejetées |

| `DRIVE\_MAX\_FUTURE\_MS` | `5000` | Tolérance horloge navigateur/serveur | critique | Rejets faux positifs ou commandes incohérentes acceptées |

| `DRIVE\_LAST\_SEQ` | `-1` | État de séquence moteur | importante | Régression anti-commandes périmées |

| `DRIVE\_LAST\_TOKEN` | `""` | Identifie une session interface | importante | Mauvaise gestion après reload navigateur |

| `DRIVE\_LAST\_ACCEPT\_TIME` | `0.0` | Diagnostic dernière commande acceptée | secondaire | Diagnostics faux |

| `DRIVE\_LAST\_REJECT\_\*` | `0.0`, `""` | Diagnostic derniers rejets | secondaire | Diagnostics incomplets |

| `WHEEL\_DIAMETER\_MM` | `85.0` | Odométrie encodeurs | critique | Distances fausses |

| `TICKS\_PER\_REV` | `10529.0` | Conversion ticks → distance | critique | Odométrie fausse |

| `TRACK\_WIDTH\_MM` | `225.0` | Calcul angle/rotation | critique | Angles faux, retour trace dégradé |

| `MM\_PER\_TICK` | calculé | Conversion mécanique | critique | Dérive odométrie |



\*\*STOP\*\*



| Constante | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---:|---|---|---|

| `DRIVE\_LAST\_STOP\_TIME` | `0.0` | Diagnostic dernier STOP | importante | Statut sécurité faux |

| `currentDriveCmd` JS | `"d0,0"` | État moteur initial côté interface | critique | Interface peut démarrer dans un état dangereux |

| `RB2\_WIFI\_RETURN\_CMD` | `"d-20,-20"` | Commande retour Wi-Fi, stoppée par bursts `d0,0` | critique | Retour dans mauvaise direction/vitesse |

| `RB2\_WIFI\_RETURN\_SPEED\_LEFT` | `-20` | Simulation/validation LIDAR du recul | critique | Garde LIDAR incohérente |

| `RB2\_WIFI\_RETURN\_SPEED\_RIGHT` | `-20` | Simulation/validation LIDAR du recul | critique | Garde LIDAR incohérente |



\*\*LIDAR\*\*



| Constante | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---:|---|---|---|

| `TRACE\_FOLLOW\_LIDAR\_MAX\_AGE\_S` | `2.0` | Âge maximal du JSON LIDAR | critique | Utiliser des données périmées ou bloquer trop vite |

| `TRACE\_FOLLOW\_FRONT\_MIN\_CM` | `45.0`, puis `37.0` | Distance minimale avant | critique | Collision avant ou blocages abusifs |

| `TRACE\_FOLLOW\_BACK\_MIN\_CM` | `25.0`, puis `17.0` | Distance minimale arrière | critique | Collision arrière ou blocages abusifs |

| `RB2\_FRONT\_COLLISION\_CM` JS | `33.0` | Géométrie affichage LIDAR | importante | Affichage danger faux |

| `RB2\_BACK\_COLLISION\_CM` JS | `10.0` | Géométrie affichage arrière | importante | Affichage danger arrière faux |

| `RB2\_MARGIN\_DANGER\_CM` JS | `5.0` | Marge danger UI LIDAR | importante | Mauvais niveau visuel |

| `RB2\_MARGIN\_WARN\_CM` JS | `15.0` | Marge avertissement UI LIDAR | importante | Mauvais niveau visuel |



Valeurs clairement issues d’essais terrain : `TRACE\_FOLLOW\_FRONT\_MIN\_CM = 37.0`, `TRACE\_FOLLOW\_BACK\_MIN\_CM = 17.0`, `RB2\_FRONT\_COLLISION\_CM = 33.0`, `RB2\_BACK\_COLLISION\_CM = 10.0`.



\*\*Trace / Rejeu / Retour\*\*



| Constante | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---:|---|---|---|

| `TRACE\_DIR` | `/opt/rb2/traces` | Dossier traces | importante | Traces introuvables |

| `TRACE\_PID\_FILE` | `/tmp/rb2\_trace\_passive.pid` | PID trace passive | importante | Détection trace fausse |

| `TRACE\_MAIN\_RE` | regex trace `.csv` | Reconnaissance trace principale | importante | Mauvais fichier choisi |

| `TRACE\_DRIVE\_RE` | regex `\_drive.csv` | Reconnaissance trace conduite | importante | Rejeu impossible |

| `TRACE\_RECORD\_ENCODERS` | `True` | Enrichit traces avec encodeurs | importante | Rejeu réel dégradé |

| `TRACE\_ENCODER\_READ\_WAIT\_S` | `0.16` | Attente lecture encodeurs | importante | Ticks manqués ou latence |

| `TRACE\_FOLLOW\_MAX\_SPEED` | `15`, puis `100` | Limite vitesse rejeu | critique | Rejeu trop lent ou trop agressif |

| `TRACE\_FOLLOW\_KEEPALIVE\_S` | `0.25`, puis `0.18` | Fréquence maintien commandes | critique | Robot saccadé ou commandes trop fréquentes |

| `TRACE\_FOLLOW\_ODOM\_SAMPLE\_S` | `0.14`, puis `0.20` | Fréquence lecture odométrie | importante | Suivi imprécis |

| `TRACE\_FOLLOW\_SEGMENT\_MIN\_MOVE\_CM` | `1.0`, puis `0.0` | Filtrage petits segments | importante | Trace simplifiée ou trop dense |

| `TRACE\_FOLLOW\_SEGMENT\_MIN\_ANGLE\_DEG` | `3.0`, puis `0.0` | Filtrage petits angles | importante | Rejeu incomplet ou trop dense |

| `TRACE\_FOLLOW\_SEGMENT\_MAX\_S` | `15.0`, puis `60.0` | Durée max segment | critique | Timeout prématuré ou segment trop long |

| `TRACE\_FOLLOW\_TARGET\_TOL\_CM` | `1.5` | Tolérance distance cible | importante | Rejeu trop strict/laxiste |

| `TRACE\_FOLLOW\_TARGET\_TOL\_DEG` | `3.0` | Tolérance angle cible | importante | Rotation imprécise |

| `TRACE\_RETURN\_FORWARD\_TURN\_LEFT` | `20` | Commande gauche demi-tour retour avant | critique | Mauvais demi-tour |

| `TRACE\_RETURN\_FORWARD\_TURN\_RIGHT` | `-20` | Commande droite demi-tour retour avant | critique | Mauvais demi-tour |

| `TRACE\_RETURN\_FORWARD\_PHYSICAL\_TURN\_DEG` | `180.0` | Intention physique demi-tour | importante | UI/preview faux |

| `TRACE\_RETURN\_FORWARD\_TURN\_TARGET\_DEG` | `500.0` | Cible odométrique demi-tour | critique | Sous/sur-rotation |

| `TRACE\_RETURN\_FORWARD\_TURN\_TOL\_DEG` | `8.0` | Tolérance demi-tour | importante | Arrêt trop tôt/trop tard |

| `TRACE\_RETURN\_FORWARD\_TURN\_TIMEOUT\_S` | `60.0` | Timeout demi-tour | critique | Demi-tour interrompu ou trop long |



Valeurs issues d’essais terrain : cible `500.0`, timeout `60.0`, vitesse `20/-20`, seuils V10 autour de `TRACE\_FOLLOW\_\*`.



\*\*Retour Wi-Fi\*\*



| Constante | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---:|---|---|---|

| `RB2\_OPERATOR\_LAST\_HEARTBEAT` | `0.0` | Dernier signal opérateur | critique | Retour déclenché ou bloqué à tort |

| `RB2\_OPERATOR\_CLIENT\_IP` | `""` | IP opérateur | importante | Test client faux |

| `RB2\_OPERATOR\_CLIENT\_LAST\_SEEN` | `0.0` | Dernier client vu | secondaire | Diagnostic faux |

| `RB2\_WIFI\_RETURN\_READY` | `True` | Retour Wi-Fi prêt | critique | Armement différent |

| `RB2\_WIFI\_RETURN\_ACTIVE` | `False` | État retour actif | critique | Double retour ou état bloqué |

| `RB2\_WIFI\_RETURN\_DONE` | `False` | État retour déjà fait | importante | UI/ack faux |

| `RB2\_WIFI\_RETURN\_LOST` | `False` | Signal perdu | critique | Retour déclenché à tort |

| `RB2\_WIFI\_RETURN\_LOSS\_AFTER\_S` | `999999.0` | Déclenchement interne désactivé | critique | Peut réactiver retour interne ancien |

| `RB2\_WIFI\_RETURN\_PULSE\_S` | `2.0` | Durée impulsion recul | critique | Recul trop long/court |

| `RB2\_WIFI\_RETURN\_MAX\_PULSES` | `5` | Nombre max impulsions | critique | Distance retour modifiée |

| `RB2\_WIFI\_RETURN\_RECENT\_DRIVE\_WINDOW\_S` | `900.0` | Fenêtre conduite récente | critique | Retour autorisé/refusé à tort |

| `RB2\_WIFI\_RETURN\_CMD` | `"d-20,-20"` | Commande recul | critique | Direction/vitesse retour |

| `RB2\_WIFI\_RETURN\_SPEED\_LEFT/RIGHT` | `-20`, `-20` | Garde LIDAR pour recul | critique | Sécurité incohérente |



Valeur à noter : `RB2\_WIFI\_RETURN\_LOSS\_AFTER\_S = 999999.0` indique que le retour Wi-Fi interne est désactivé/remplacé par le service externe. Ne pas “corriger” cette valeur sans comprendre l’architecture actuelle.



\*\*Caméra\*\*



| Constante | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---|---|---|---|

| `ZERO\_CAM\_STREAM\_URL` | `http://10.50.0.20:8080/stream.mjpg` | Flux caméra Zero | importante | Flux cassé |

| `ZERO\_CAM\_STATUS\_URL` | `http://10.50.0.20:8080/status` | Statut caméra | importante | Statut cassé |

| `ZERO\_CAM\_PHOTO\_URL` | `http://10.50.0.20:8080/photo` | Capture photo | importante | Photo impossible |

| `ZERO\_CAM\_VIDEO\_TOGGLE\_URL` | `http://10.50.0.20:8080/video\_toggle` | Vidéo on/off | importante | Vidéo cassée |

| `ZERO\_CAM\_VIDEO\_STATUS\_URL` | `http://10.50.0.20:8080/video\_status` | État vidéo | secondaire | UI fausse |

| `ZERO\_CAM\_CAPTURES\_LIST\_URL` | `http://10.50.0.20:8080/captures/list` | Liste captures | secondaire | Galerie cassée |

| `ZERO\_CAM\_CAPTURES\_FILE\_BASE` | `http://10.50.0.20:8080/captures/file` | Téléchargement fichiers | secondaire | Téléchargement cassé |

| `ZERO\_CAM\_CAPTURES\_ZIP\_URL` | `http://10.50.0.20:8080/captures/zip` | Archive captures | secondaire | Export cassé |

| `ZERO\_CAM\_CAPTURES\_DELETE\_URL` | `http://10.50.0.20:8080/captures/delete` | Suppression captures | importante | Suppression distante cassée/dangereuse |



\*\*SLAM\*\*



| Constante / valeur | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---|---|---|---|

| setup ROS | `/opt/ros/jazzy/setup.bash` | Environnement ROS | importante | Commandes ROS impossibles |

| workspace ROS | `/home/rj/rb2\_ros2\_ws/install/setup.bash` | Workspace RB2 | importante | Noeuds/paquets introuvables |

| service SLAM | `rb2-slam.service` | Service systemd SLAM | importante | Démarrage/arrêt SLAM cassé |

| script start SLAM | `/usr/local/sbin/rb2-slam-start-bg` | Démarrage arrière-plan | critique | Bouton SLAM cassé |

| `map\_dir` | `/home/rj/rb2\_maps` | Sauvegarde cartes | importante | Cartes introuvables |

| `script\_dir` | `/home/rj/rb2\_scripts` | Helper sauvegarde carte | importante | Sauvegarde impossible |

| helper | `rb2\_save\_map\_direct.py` | Script généré pour `/map` | importante | Sauvegarde directe cassée |



\*\*Réseau\*\*



| Constante | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---|---|---|---|

| `\_RB2\_WIFI\_SCRIPT` | `/usr/local/sbin/rb2-wifi-mode` | Script mode Wi-Fi | importante | Bouton réseau cassé |

| `\_RB2\_LOCAL\_WIFI\_IF` | `wlan0` | Interface Wi-Fi locale | importante | Mauvaise interface modifiée |

| actions acceptées | `terrain`, `bureau`, `status` | Modes réseau autorisés | importante | Action non prévue possible |

| IP Zero | `10.50.0.20` | Caméra/arrêt Zero | critique | Caméra/arrêt distant cassés |



\*\*Chemins Fichiers\*\*



| Constante / chemin | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---|---|---|---|

| `TRACE\_DIR` | `/opt/rb2/traces` | Dossier traces | importante | Traces perdues |

| `TRACE\_PID\_FILE` | `/tmp/rb2\_trace\_passive.pid` | PID trace passive | importante | État trace faux |

| `\_RB2\_WHEEL\_TICKS\_JSON\_FILE` | `/tmp/rb2\_wheel\_ticks.json` | Pont ticks vers ROS | importante | Odométrie ROS cassée |

| LIDAR summary | `/tmp/rb2\_lidar.json` | Distances LIDAR | critique | Sécurité LIDAR cassée |

| LIDAR map | `/tmp/rb2\_lidar\_map.json` | Carte LIDAR | importante | Affichage LIDAR cassé |

| Wi-Fi log | `/tmp/rb2\_wifi\_return.log` | Journal retour Wi-Fi | secondaire | Diagnostic perdu |

| maps | `/home/rj/rb2\_maps` | Cartes SLAM | importante | Sauvegardes perdues |

| scripts | `/home/rj/rb2\_scripts` | Helpers/scripts terrain | importante | SLAM save cassé |



\*\*Temporisations\*\*



| Constante / valeur | Valeur | Rôle probable | Criticité | Risque si modifiée |

|---|---:|---|---|---|

| `DRIVE\_MAX\_AGE\_MS` | `6000 ms` | Péremption commandes moteur | critique | Requêtes anciennes acceptées |

| `DRIVE\_MAX\_FUTURE\_MS` | `5000 ms` | Tolérance horloge | critique | Rejets abusifs |

| `TRACE\_ENCODER\_READ\_WAIT\_S` | `0.16 s` | Attente encodeurs | importante | Données manquées |

| `TRACE\_FOLLOW\_KEEPALIVE\_S` | `0.25`, puis `0.18 s` | Répétition commande trace | critique | Robot saccadé ou trop sollicité |

| `TRACE\_FOLLOW\_ODOM\_SAMPLE\_S` | `0.14`, puis `0.20 s` | Échantillonnage odométrie | importante | Rejeu imprécis |

| `TRACE\_FOLLOW\_SEGMENT\_MAX\_S` | `15`, puis `60 s` | Timeout segment | critique | Arrêts prématurés |

| `TRACE\_RETURN\_FORWARD\_TURN\_TIMEOUT\_S` | `60 s` | Timeout demi-tour retour avant | critique | Demi-tour interrompu |

| `RB2\_WIFI\_RETURN\_PULSE\_S` | `2.0 s` | Durée impulsion retour Wi-Fi | critique | Recul trop long/court |

| `RB2\_WIFI\_RETURN\_RECENT\_DRIVE\_WINDOW\_S` | `900 s` | Fenêtre conduite récente | critique | Retour autorisé/refusé à tort |

| `DRIVE\_REPEAT\_MS` JS | `250 ms` | Répétition commandes UI ancienne | critique | Commandes moteur trop fréquentes/rares |

| `ENCODER\_REPEAT\_MS` JS | `2000 ms` | Rafraîchissement encodeurs | secondaire | UI lente/charge accrue |

| timeouts caméra | `2`, `3`, `6`, `10`, `20 s` | Proxy Zero | importante | UI bloquée ou trop sensible |



\*\*Constantes Redéfinies Plus Loin\*\*



Redéfinitions importantes :



| Nom | Première valeur | Valeur plus loin | Commentaire |

|---|---:|---:|---|

| `TRACE\_FOLLOW\_MAX\_SPEED` | `15` | `100` | V10 : plus de plafonnement artificiel |

| `TRACE\_FOLLOW\_FRONT\_MIN\_CM` | `45.0` | `37.0` | Seuil terrain avant |

| `TRACE\_FOLLOW\_BACK\_MIN\_CM` | `25.0` | `17.0` | Seuil terrain arrière |

| `TRACE\_FOLLOW\_KEEPALIVE\_S` | `0.25` | `0.18` | Maintien commande plus ferme |

| `TRACE\_FOLLOW\_ODOM\_SAMPLE\_S` | `0.14` | `0.20` | Échantillonnage revu |

| `TRACE\_FOLLOW\_SEGMENT\_MIN\_MOVE\_CM` | `1.0` | `0.0` | Rejeu exact opérateur |

| `TRACE\_FOLLOW\_SEGMENT\_MIN\_ANGLE\_DEG` | `3.0` | `0.0` | Rejeu exact opérateur |

| `TRACE\_FOLLOW\_SEGMENT\_MAX\_S` | `15.0` | `60.0` | Segments plus longs |



Redéfinitions côté JavaScript/HTML :



| Constante JS | Emplacements | Commentaire |

|---|---|---|

| `TILT\_MIN`, `TILT\_MAX` | deux blocs HTML/JS | Valeurs pan/tilt répétées |

| `PAN\_NORMAL\_MIN`, `PAN\_NORMAL\_MAX` | deux blocs HTML/JS | Limites pan répétées |

| `PAN\_HIGH\_TILT\_MIN`, `PAN\_HIGH\_TILT\_MAX` | deux blocs HTML/JS | Limites pan selon tilt répétées |

| `TILT\_RESTRICT\_START` | deux blocs HTML/JS | Seuil restriction pan |

| `currentDriveCmd = "d0,0"` | deux blocs HTML/JS | État moteur initial répété |

| `pan = 95`, `tilt = 90` | deux blocs HTML/JS | Valeurs initiales UI répétées |



\*\*Valeurs Semblant Issues D’essais Terrain\*\*



À considérer comme calibrées terrain :



```text

TRACE\_FOLLOW\_FRONT\_MIN\_CM = 37.0

TRACE\_FOLLOW\_BACK\_MIN\_CM = 17.0

TRACE\_FOLLOW\_MAX\_SPEED = 100

TRACE\_FOLLOW\_KEEPALIVE\_S = 0.18

TRACE\_FOLLOW\_SEGMENT\_MAX\_S = 60.0

TRACE\_RETURN\_FORWARD\_TURN\_TARGET\_DEG = 500.0

TRACE\_RETURN\_FORWARD\_TURN\_TIMEOUT\_S = 60.0

RB2\_FRONT\_COLLISION\_CM = 33.0

RB2\_BACK\_COLLISION\_CM = 10.0

RB2\_MARGIN\_DANGER\_CM = 5.0

RB2\_MARGIN\_WARN\_CM = 15.0

WHEEL\_DIAMETER\_MM = 85.0

TICKS\_PER\_REV = 10529.0

TRACK\_WIDTH\_MM = 225.0

```



Conclusion : les constantes les plus dangereuses sont celles des commandes moteur, STOP, LIDAR, trace/rejeu, retour avant et retour Wi-Fi. Les redéfinitions `TRACE\_FOLLOW\_\*` sont particulièrement sensibles : elles semblent représenter une évolution validée sur le terrain, pas du simple doublon à nettoyer.

