\# Point d'arrêt nettoyage Codex RB2 - 2026-06-26



\## Branche



\- nettoyage-codex-20260626



\## Objectif du nettoyage



Nettoyage prudent du dépôt RB2 sans modification fonctionnelle volontaire du robot.



Objectifs atteints :



\- clarifier la structure du dépôt;

\- documenter les fichiers sensibles;

\- récupérer les dépendances de production manquantes;

\- supprimer les copies redondantes;

\- vérifier la syntaxe Python;

\- protéger le dépôt contre les fichiers temporaires;

\- éviter tout refactoring risqué.



\## Dossier canonique



Le dossier canonique est maintenant :



\- opt/rb2



Les dossiers redondants suivants ont été supprimés :



\- opt-rb2

\- opt\_rb2



\## Fichiers de production ajoutés ou confirmés



Fichiers importants présents dans opt/rb2 :



\- esp32\_panel.py

\- rb2\_esp32.py

\- rb2\_lidar\_json.py

\- rb2\_lidar\_map\_json.py

\- rb2\_imu\_json.py

\- rb2\_usb\_camera.py

\- rb2\_wifi\_dual\_loss\_return.py



Scripts de production ajoutés ou confirmés :



\- home-rj/rb2\_scripts/start\_rb2\_bringup.sh

\- home-rj/rb2\_scripts/start\_rb2\_slam.sh

\- home-rj/rb2\_web/start\_rb2\_web\_teleop.sh

\- system\_files/rb2-slam-start-bg

\- system\_files/rb2-wifi-mode

\- system\_files/rb2-zero-cam-restart

\- usr-local-sbin/rb2-shutdown-zero-before-pi5.sh



\## Documentation créée ou enrichie



Documents importants :



\- docs/NETTOYAGE\_CODEX\_20260626.md

\- docs/DOUBLONS\_OPT\_20260626.md

\- docs/SERVICES\_SYSTEMD\_20260626.md

\- docs/RAPPORT\_NETTOYAGE\_STRUCTUREL\_20260626.md

\- docs/ESP32\_PANEL\_ANALYSE\_20260626.md

\- docs/ESP32\_PANEL\_ROUTES\_20260626.md

\- docs/ESP32\_PANEL\_CONSTANTES\_20260626.md

\- docs/ESP32\_PANEL\_DEPENDANCES\_20260626.md

\- docs/RB2\_ESP32\_MODULE\_20260626.md

\- docs/VERIFICATIONS\_CODE\_20260626.md

\- docs/ESP32\_PANEL\_MICRO\_CORRECTIONS\_20260626.md



\## Vérifications effectuées



Les scripts Python principaux ont été vérifiés avec :



\- python -m py\_compile



Résultat :



\- aucune erreur bloquante;

\- avertissement regex JavaScript traité ou vérifié;

\- aucun fichier \_\_pycache\_\_ conservé;

\- git status propre après vérifications.



\## .gitignore



Le fichier .gitignore a été affiné.



Décision importante :



\- retirer l'exclusion trop large \*.json;

\- ignorer seulement les JSON runtime RB2 connus;

\- conserver les fichiers de configuration JSON futurs visibles par Git.



\## Zones à ne pas toucher sans test réel



Ne pas nettoyer mécaniquement :



\- /cmd

\- /stop

\- rb2\_safe\_drive\_send

\- commandes moteur dG,D

\- STOP d0,0

\- logique LIDAR

\- logique SLAM

\- retour Wi-Fi

\- trace/rejeu

\- pan/tilt

\- blocs HTML/JS injectés en fin de fichier

\- constantes V10/V22 redéfinies

\- fonctions trace/rejeu redéfinies



\## Décision de prudence



Le nettoyage structurel est suffisant pour cette phase.



Aucun refactoring de esp32\_panel.py ne doit être fait sans :



1\. une branche séparée;

2\. une modification unique;

3\. un diff minimal;

4\. un test syntaxique;

5\. un test réel sur RB2;

6\. une sauvegarde Git avant et après.



\## Prochaine phase recommandée



Avant toute nouvelle modification de code :



\- tester RB2 réel à partir de cette branche ou après fusion contrôlée;

\- vérifier /terrain;

\- vérifier caméra;

\- vérifier STOP;

\- vérifier commandes manuelles;

\- vérifier LIDAR;

\- vérifier IMU;

\- vérifier pan/tilt;

\- vérifier bouton Wi-Fi local;

\- vérifier retour Wi-Fi seulement si conditions sécuritaires.



Conclusion :



Ce point constitue un arrêt propre du nettoyage Codex prudent.

