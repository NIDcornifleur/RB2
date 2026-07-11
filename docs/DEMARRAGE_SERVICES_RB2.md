# Démarrage des services RB2

## Services opérationnels

`rb2-bringup.service` constitue le bringup ROS principal du RB2.

Les services opérationnels à conserver sont :

- `rb2-bringup.service`
- `rb2-imu-json.service`
- `rb2-lidar-json.service`
- `rb2-lidar-map-json.service`
- `rb2-esp32-panel.service`

Les pages opérationnelles sont :

- `/terrain3`
- `/lidar_drive2`
- `/secours`

Les anciennes routes `/terrain`, `/terrain2` et `/lidar_drive` doivent être conservées pour le moment à cause de leurs dépendances internes.

## Mécanismes de récupération retirés ou neutralisés

`rb2-lidar-watchdog.service` et `rb2_lidar_watchdog.py` ont été retirés du dépôt. Ils provoquaient des redémarrages perturbateurs des ponts JSON LIDAR, puis de `rb2-bringup.service`, lorsque les fichiers JSON semblaient périmés.

`rb2-lidar-panel-autorecover.service` et `rb2_lidar_panel_autorecover.sh` ont été trouvés sur le Raspberry Pi actif, mais sont absents du dépôt.

Sur le Raspberry Pi actif :

- l'autorecover doit rester masqué;
- le watchdog doit rester désactivé;
- aucun mécanisme automatique ne doit redémarrer `rb2-bringup.service` sans diagnostic explicite;
- la récupération actuelle doit rester manuelle.

## Vérification manuelle

Vérifier les services opérationnels :

```sh
systemctl is-active \
  rb2-bringup.service \
  rb2-imu-json.service \
  rb2-lidar-json.service \
  rb2-lidar-map-json.service \
  rb2-esp32-panel.service
```

Vérifier que les mécanismes indésirables ne sont pas actifs :

```sh
systemctl is-active \
  rb2-lidar-panel-autorecover.service \
  rb2-lidar-watchdog.service 2>/dev/null || true
```

Vérifier qu'aucun processus correspondant ne fonctionne :

```sh
pgrep -af 'rb2_lidar_panel_autorecover|rb2_lidar_watchdog' \
  || echo "Aucun processus indésirable"
```

Vérifier l'actualisation des fichiers JSON :

```sh
stat -c '%n | %y | %s octets' \
  /tmp/rb2_lidar.json \
  /tmp/rb2_lidar_map.json \
  /tmp/rb2_imu.json
```
