# RB2 Terrain4 — page autonome légère

`/terrain4` est une page HTML autonome (`opt/rb2/terrain4.html`), servie par
une route Flask dédiée dans `opt/rb2/esp32_panel.py` qui ne dépend ni de
`/terrain`, ni de `/terrain2`, ni de `/terrain3` et ne reçoit aucune de leurs
injections JavaScript historiques.

Contenu : caméra + carte LIDAR (zoom −/+), pavé de conduite, vitesse,
pan/tilt, lumières/relais 2, arrêt RB2. SLAM, TRACE et RETOUR demeurent
exclusivement dans `/lidar_drive2`.

## Charge réseau prévue

- une seule connexion caméra MJPEG;
- `/lidar_map` interrogée toutes les 2 secondes, une requête à la fois;
- `/rb2_network/status` environ toutes les 20 secondes (mêlé au cycle LIDAR);
- initialisation séquentielle au chargement (pas de rafale de requêtes).

## Historique des correctifs

**13 juillet 2026 — création.** Page neuve créée pour remplacer `/terrain3`,
abandonné car trop redondant : ses injections historiques ralentissaient les
communications Wi‑Fi et causaient des lags importants.

**14 juillet 2026 — correctif v2.1 (réseau).** Délais de requête trop courts
(2,2 s / 2,6 s / 1,2 s) sous lag Wi‑Fi : rallongés à 6-8 s, carte LIDAR
actualisée toutes les 2 s au lieu de 1,2 s, relecture de l'état GPIO réel
avant chaque bascule lumière/relais, resynchronisation automatique si la
réponse d'une commande se perd.

**14 juillet 2026 — correctif `fetchJson` (bug bloquant).** `fetchJson()`
référençait une variable `started` jamais déclarée dans son étendue ; chaque
appel levait une `ReferenceError` juste après avoir reçu une réponse HTTP
pourtant valide (200). Toutes les fonctions passant par `fetchJson` — lumière,
relais 2, carte LIDAR, statut vidéo — affichaient donc systématiquement une
erreur, même quand le serveur répondait correctement et rapidement. Seule la
conduite (`/cmd`, via `sendDrive`, qui déclare son propre `started` local)
fonctionnait. Corrigé en déclarant `const started = performance.now();` en
tête de `fetchJson`.

**14 juillet 2026 — mise en page.** Boutons LUMIÈRES / RELAIS 2 déplacés dans
l'en-tête, entre le titre et le pastille « Lien ». Bouton ARRÊTER RB2 (renommé
« ARRET RB2 », plus compact) déplacé dans l'en-tête, à gauche de LUMIÈRES —
il était auparavant en bas du panneau latéral, hors écran. Sous-titre
remplacé par « Roméo St-Cyr, juillet 2026 » (même style que le titre).

**14 juillet 2026 — calibration vitesse.** Les boutons 25/50/75/100 %
envoyaient `d15/d17/d19/d20` (valeurs historiques de `/terrain2`, plafonnées à
20 % du PWM disponible) : le libellé « 100 % » ne correspondait donc pas à la
vitesse maximale réelle. Passés à `d25/d50/d75/d100`, pourcentages de PWM
réels et proportionnels à la vitesse maximale mesurée du moteur (100 % ≈
37 rpm).

## Installation / mise à jour

Installation complète (première fois, ou restauration), avec redémarrage du
service :

```bash
cd RB2-RomBot2
chmod +x installer_terrain4.sh
./installer_terrain4.sh
```

Mise à jour de `terrain4.html` seul (cas courant), sans redémarrage :

```bash
cd RB2-RomBot2
chmod +x mettre_a_jour_terrain4_v2.sh
./mettre_a_jour_terrain4_v2.sh
```

Les deux scripts sauvegardent l'ancienne version avant d'écrire, vérifient la
page réellement retournée par Flask, et restaurent automatiquement en cas
d'échec. Dans le navigateur, toujours faire `Ctrl+F5` ensuite sur
`http://10.42.0.1:5051/terrain4`.

## Vérification au bureau

Avec seulement `/terrain4` et une session SSH ouvertes :

```bash
ping -c 30 10.42.0.147

sudo journalctl -b -u rb2-esp32-panel.service --since "-5 minutes" --no-pager |
sed -n 's/.*"GET \([^ ?]*\).*/\1/p' |
sort | uniq -c | sort -nr | head -30
```

La page ne doit produire aucun appel à `/trace_follow_status`,
`/wifi_return_status` répétitif hors intervalle normal, ou `SLAM`/`TRACE`.

## Premier essai terrain

1. Ouvrir `/terrain4` depuis l'AP `RB2-ROS`.
2. Utiliser le bouton **Wi‑Fi local ON** pour couper `wlan0`; l'AP reste actif.
3. Faire un ping continu vers `10.42.0.1`.
4. Tester d'abord STOP, puis moteurs à 25 %, caméra et pan-tilt.
5. Refaire le test à 10 mètres en ligne de vue avant une inspection réelle.

## Restauration manuelle

Reprendre le chemin de sauvegarde affiché par le script utilisé :

```bash
sudo cp -a /opt/rb2/esp32_panel.py.avant-terrain4-AAAAMMJJ-HHMMSS \
  /opt/rb2/esp32_panel.py
sudo systemctl restart rb2-esp32-panel.service
```

ou, pour `terrain4.html` seul :

```bash
sudo cp -a /opt/rb2/terrain4.html.avant-correctif-v21-AAAAMMJJ-HHMMSS \
  /opt/rb2/terrain4.html
```
