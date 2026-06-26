# Doublons opt RB2 - 2026-06-26

## Objectif

Ce document inventorie les dossiers opt du dépôt RB2 avant toute suppression ou réorganisation.

Le but est de documenter clairement les copies redondantes et les variantes connues, sans modifier le comportement du robot.

## Dossier canonique retenu

Le dossier canonique du dépôt est :

- opt/rb2

Raisons :

- il correspond au chemin de production Linux /opt/rb2;
- les services systemd de production pointent vers /opt/rb2;
- il contient les scripts principaux du panneau RB2;
- il contient maintenant la version production vérifiée de rb2_lidar_map_json.py copiée depuis le Pi5.

## Dossiers comparés

### opt/rb2

Statut :

- dossier canonique à conserver.

Contenu actuel :

- esp32_panel.py
- rb2_lidar_json.py
- rb2_lidar_map_json.py
- rb2_wifi_dual_loss_return.py

### opt-rb2

Statut :

- variante ancienne ou copie complète à traiter plus tard.

Contenu actuel :

- esp32_panel.py
- rb2_lidar_json.py
- rb2_lidar_map_json.py
- rb2_wifi_dual_loss_return.py

Remarque importante :

- opt-rb2/rb2_lidar_map_json.py est différent de la version production maintenant placée dans opt/rb2;
- cette version ne doit pas remplacer opt/rb2/rb2_lidar_map_json.py.

### opt_rb2

Statut :

- copie partielle ancienne à traiter plus tard.

Contenu actuel :

- esp32_panel.py

## Empreintes SHA256 connues

### esp32_panel.py

Identique dans :

- opt/rb2
- opt-rb2
- opt_rb2

SHA256 :

- 96D5728657CDE388D44338B0C9F1343C85C13208CAD7676726A0D44F1D3CCECD

### rb2_lidar_json.py

Identique dans :

- opt/rb2
- opt-rb2

SHA256 :

- 21F8A21CCDC5A32669A18E548FB0249DF23748860D8D463A7AC79188F4C7FFA3

### rb2_wifi_dual_loss_return.py

Identique dans :

- opt/rb2
- opt-rb2

SHA256 :

- DBF6FCC542C953F39587F364ED25C0207069464C621A96BA7970F045CB342E3E

### rb2_lidar_map_json.py - version production Pi5

Présente dans :

- opt/rb2
- production_snapshots/opt_rb2_20260626

SHA256 :

- 334200be21f0c3baeaca7a4a752cffce4d685a75fd9cb4068299b25c0ad42956

### rb2_lidar_map_json.py - variante opt-rb2

Présente dans :

- opt-rb2

SHA256 :

- 619BC93F4A46877A5A4860F144D8D948E1C76C31875EE31B75FC239949E7041C

## Conclusion

Le dépôt doit conserver opt/rb2 comme dossier principal.

Les dossiers opt-rb2 et opt_rb2 semblent redondants, mais ne doivent pas être supprimés sans validation finale.

La seule vraie différence importante observée est :

- opt-rb2/rb2_lidar_map_json.py est différent de la version production du Pi5.

## Décision provisoire

À conserver :

- opt/rb2
- production_snapshots/opt_rb2_20260626

Candidats à suppression future :

- opt-rb2
- opt_rb2

Condition avant suppression :

- relire ce document;
- vérifier que GitHub contient bien les commits de sauvegarde;
- confirmer que opt/rb2 contient tous les fichiers nécessaires;
- confirmer que le Pi5 fonctionne toujours avec /opt/rb2;
- ne jamais remplacer la version production de rb2_lidar_map_json.py par celle de opt-rb2.

## Règle de prudence

Aucune suppression ne doit être faite directement sur main.

Toute suppression éventuelle doit rester dans la branche :

- nettoyage-codex-20260626

Puis elle doit être testée, relue et poussée sur GitHub avant fusion.
