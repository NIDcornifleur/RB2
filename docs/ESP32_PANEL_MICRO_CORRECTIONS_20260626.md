\# Micro-corrections candidates esp32\_panel.py - 2026-06-26



\## Objectif



Ce document classe les micro-corrections potentielles repérées dans :



\- opt/rb2/esp32\_panel.py



Aucune modification fonctionnelle n'est recommandée pour l'instant.



\## État Git au moment de l'analyse



\- Branche : nettoyage-codex-20260626

\- git status : propre

\- Aucun fichier modifié



\## Correction déjà vérifiée



La ligne JavaScript de validation des commandes moteur est maintenant sous forme échappée dans le fichier Python :



\- return /^d-?\\\\d+,-?\\\\d+$/.test(String(command || ""));



Cette forme évite le SyntaxWarning Python lié à \\d tout en conservant le sens voulu de la regex JavaScript générée.



\## Candidates classées



| Candidate | Risque | Décision |

|---|---|---|

| Regex JavaScript avec \\d | faible | déjà vérifiée / ne plus toucher |

| Texte visible avec double espace dans "Créé par Roméo St-Cyr en  juin 2026" | faible | peut attendre |

| Import urllib.error potentiellement inutilisé | faible | ne pas toucher |

| Constantes TRACE\_FOLLOW redéfinies | moyen | documenter seulement |

| Fonctions trace/rejeu redéfinies V10/V22 | élevé | ne pas toucher |

| Constantes JavaScript pan/tilt répétées | moyen | documenter seulement |

| currentDriveCmd = "d0,0" répété | moyen | ne pas toucher |

| Commentaires historiques V7/V10/V22 | faible | documenter seulement |

| Messages console avec noms internes anciens | faible | ne pas toucher |

| Blocs HTML/JS injectés en fin de fichier | moyen | documenter seulement |



\## Décisions de prudence



Ne pas modifier pour l'instant :



\- /cmd

\- /stop

\- rb2\_safe\_drive\_send

\- commandes moteur dG,D

\- STOP d0,0

\- logique LIDAR

\- logique SLAM

\- retour Wi-Fi

\- traces/rejeu

\- pan/tilt

\- injections HTML/JS tardives

\- constantes V10/V22 redéfinies



\## Conclusion



Le fichier esp32\_panel.py contient plusieurs zones historiques et redéfinies, mais elles semblent liées aux validations terrain successives.



Le nettoyage mécanique est trop risqué.



Décision :



\- conserver le code tel quel;

\- documenter les zones sensibles;

\- ne faire aucune suppression de doublon sans test réel sur RB2;

\- poursuivre le nettoyage seulement dans les documents ou fichiers non critiques.

