# Bascule Wi-Fi de secours RB2 — correctifs 2026-08-29

## Chaîne de bascule (rappel)

| Niveau | Réseau | IP Pi5 | Qui le porte |
|--------|--------|--------|--------------|
| Normal | Wi-Fi local (WIFI-MAISON) | DHCP sur `wlan0` | box / AP maison |
| Normal | PA opérateur `RB2-ROS` | `10.42.0.1` sur `wlxXXXXXXXXXXXX` | dongle Alfa + `hostapd` sur le Pi5 |
| Secours | `RB2-ZERO-SECOURS` | `10.60.0.1` sur `wlan0` du Zero | `hostapd`/NM sur le Zero 2 W |

Il n'existe **pas** de PA à `10.40.0.1`. Le « PA du Pi5 » est `RB2-ROS` à `10.42.0.1`.

`rb2_zero_secours_auto.py` (sur le Zero) surveille les deux Wi-Fi du Pi5 par SSH
via le lien direct eth0 (`10.50.0.1` ↔ `10.50.0.20`, toujours actif). Si les
deux sont tombés pendant ~60 s → il lève `RB2-ZERO-SECOURS`. Depuis ce
correctif : si un Wi-Fi du Pi5 revient pendant ~60 s → il rabaisse le secours
et rebranche le Zero sur le réseau local.

## Ce qui était cassé (incident du 2026-08-29)

1. **`RB2-ROS` (10.42.0.1) muet et invisible.** Le dongle Alfa (`mt76x2u`,
   USB `2-2`) s'est ré-énuméré 2× vers 13:42, ~4 min après le boot (signature
   brownout USB, déjà vu le 2026-07-23). `hostapd` est resté « active
   (running) » accroché à l'ancienne instance, bloqué à `HT_SCAN` ;
   `rb2-ap-ip.service` étant un `oneshot`, `10.42.0.1` n'a jamais été remis.
   RB2-ROS est resté mort jusqu'à un `systemctl restart hostapd` manuel à 16:19.

2. **Le Zero ne revient jamais du secours.** `rb2_zero_secours_auto.py`
   n'avait aucune logique de retrait : une fois `RB2-ZERO-SECOURS` levé, il
   bouclait sur « maintien actif » indéfiniment et laissait
   `connection.autoconnect=no` en permanence sur `WIFI-MAISON-2.4G` — donc même un
   reboot ne rebranchait pas le Zero.

3. **Bouton « Restart retour Wi-Fi » trompeur.** Il ne relançait que
   `rb2-wifi-dual-loss-return.service`, c.-à-d. le watchdog de **recul
   automatique** du robot. Aucun effet sur `hostapd`, `wlan0` ou le PA secours.

## Correctifs livrés

### 1. `opt/rb2/rb2_ap_watchdog.py` + `systemd/rb2-ap-watchdog.service`

Chien de garde du PA `RB2-ROS`. Toutes les 15 s : vérifie que `hostapd` est
actif, que `iw dev wlxXXXXXXXXXXXX info` montre `ssid RB2-ROS` **et** un
`channel` (absents quand `hostapd` est orphelin), et que `10.42.0.1` est
présent. Après ~30 s d'anomalie → `restart rb2-ap-ip.service` puis
`restart hostapd.service`. Coupe-circuit : après 4 réparations rapprochées,
surveillance lente 10 min (cas dongle débranché).

### 2. `zero/rb2_zero_secours/rb2_zero_secours_auto.py` (patch)

- Nouvelle phase « PA secours actif » dans la boucle : si un Wi-Fi du Pi5 est
  revenu pendant `RESTORE_OK_CYCLES` (6 × 10 s), appelle `restore_local()`.
- `restore_local()` : `autoconnect=yes` sur `WIFI-MAISON-2.4G`, coupe
  `RB2-ZERO-OUVERT`, remonte le Wi-Fi local (repli `nmcli dev connect wlan0`).
- Nouvelle option `--restore` (retour forcé, pour la page de secours).
- La boucle ne fait plus de `sleep(60)` aveugle : elle réévalue l'état du Pi5
  à chaque cycle, secours actif ou non.

### 3. `zero/rb2_zero_secours/rb2_zero_secours_web.py` (patch)

- Nouveau bouton **RÉTABLIR Wi-Fi Pi5 (RB2-ROS)** : SSH Pi5 →
  `restart rb2-ap-ip.service` + `restart hostapd.service`.
- Nouveau bouton **COUPER secours Zero + rebrancher réseau local** :
  `sudo -n python3 rb2_zero_secours_auto.py --restore` en local.
- « Restart retour Wi-Fi » renommé **« Restart watchdog RECUL (ne rétablit
  PAS le Wi-Fi) »**, avec commentaire explicatif.
- Liens et test pointent sur `/terrain4` (et non `/terrain`).

### Sudoers

- `sudoers/rb2-zero-secours.pi5.sudoers` : + `restart rb2-ap-ip.service` et
  `restart hostapd.service`.
- `sudoers/rb2-zero-secours.zero.sudoers` : + `python3 …/rb2_zero_secours_auto.py --restore`.

## Déploiement (terminal de l'opérateur, sudo interactif)

> **Déjà effectué le 2026-08-29** — voir « État du déploiement » plus bas.
> Ces commandes restent la référence pour une réinstallation propre.

### Sur le Pi5 (`rb2-ros`)

```bash
cd ~/RB2-RomBot2
git fetch && git checkout fix-secours-wifi-bascule-retour

# chien de garde PA
sudo install -o root -g root -m 0755 opt/rb2/rb2_ap_watchdog.py /opt/rb2/rb2_ap_watchdog.py
sudo install -o root -g root -m 0644 systemd/rb2-ap-watchdog.service /etc/systemd/system/rb2-ap-watchdog.service
sudo systemctl daemon-reload
sudo systemctl enable --now rb2-ap-watchdog.service
journalctl -u rb2-ap-watchdog.service -f   # doit dire « démarré » puis rester silencieux si le PA est sain

# sudoers page de secours (édition validée)
sudo visudo -f /etc/sudoers.d/rb2-zero-secours   # recopier sudoers/rb2-zero-secours.pi5.sudoers
```

**Historique du déploiement du chien de garde** : faute d'accès `sudo` non
interactif dans la session, il a d'abord été installé sans le `sudo install`
ci-dessus — script dans `~/rb2_scripts/rb2_ap_watchdog.py`, unité
`~/rb2_scripts/rb2-ap-watchdog.service` rattachée par `sudo systemctl link`
+ `enable --now`. Il a corrigé une panne réelle dès le démarrage (dongle
ré-énuméré à 16:55, hostapd orphelin, RB2-ROS muet jusqu'à la réparation à
18:00). **Migration propre vers `/opt/rb2` effectuée le 2026-08-29 au soir**
(voir « État du déploiement » ci-dessous) — le chemin provisoire
`~/rb2_scripts` n'est plus utilisé.

### Sur le Zero (`rb2cam`, ou par SSH depuis le Pi5 : `ssh rj@10.50.0.20`)

```bash
cd ~/RB2-RomBot2 && git fetch && git checkout fix-secours-wifi-bascule-retour   # si le dépôt est cloné là
# sinon copier les 2 fichiers depuis le Pi5 :
#   scp rj@10.50.0.1:RB2-RomBot2/zero/rb2_zero_secours/rb2_zero_secours_*.py ~/rb2_zero_secours/

cp ~/rb2_zero_secours/rb2_zero_secours_auto.py ~/rb2_zero_secours/rb2_zero_secours_auto.py.bak_$(date +%Y%m%d-%H%M%S)
cp ~/rb2_zero_secours/rb2_zero_secours_web.py  ~/rb2_zero_secours/rb2_zero_secours_web.py.bak_$(date +%Y%m%d-%H%M%S)
install -m 0644 zero/rb2_zero_secours/rb2_zero_secours_auto.py ~/rb2_zero_secours/rb2_zero_secours_auto.py
install -m 0755 zero/rb2_zero_secours/rb2_zero_secours_web.py  ~/rb2_zero_secours/rb2_zero_secours_web.py
python3 -m py_compile ~/rb2_zero_secours/rb2_zero_secours_auto.py ~/rb2_zero_secours/rb2_zero_secours_web.py

sudo visudo -f /etc/sudoers.d/rb2-zero-secours-local   # recopier sudoers/rb2-zero-secours.zero.sudoers

sudo systemctl restart rb2-zero-secours-auto.service rb2-zero-secours-web.service
journalctl -u rb2-zero-secours-auto.service -f
```

## État du déploiement (vérifié en direct le 2026-08-29 au soir)

Les trois correctifs **sont déployés et tournent**, fichiers octet pour octet
identiques au tip de la branche `fix-secours-wifi-bascule-retour`.

| Élément | Hôte | État |
|---------|------|------|
| `rb2_ap_watchdog.py` | Pi5 | `/opt/rb2/rb2_ap_watchdog.py` (migré hors de `~/rb2_scripts`), sha256 = branche |
| `rb2-ap-watchdog.service` | Pi5 | `/etc/systemd/system/`, `enabled`, actif ; a logué « PA stable » à 18:05 |
| `rb2_zero_secours_auto.py` | Zero | `~/rb2_zero_secours/`, backup `.bak_20260829-175606`, service relancé 17:57 |
| `rb2_zero_secours_web.py` | Zero | idem ; 3 boutons en place, liens `/terrain4` |
| sudoers `--restore` | Zero | `/etc/sudoers.d/rb2-zero-secours-local` présent (`sudo -n -l` OK) |
| sudoers `rb2-ap-ip` / `hostapd` | Pi5 | fichier `rb2-zero-secours` non vérifié, mais **inutile** : `sudo -n systemctl` est déjà NOPASSWD global sur le Pi5, donc le bouton « RÉTABLIR Wi-Fi Pi5 » fonctionne quand même |

**Reste à faire** :

1. Ouvrir la PR `fix-secours-wifi-bascule-retour` → `main` et fusionner
   (branche poussée, non fusionnée).
2. **Test de bascule réel** (section suivante) — le retour automatique du
   secours et les deux nouveaux boutons sont déployés mais jamais testés en
   conditions réelles ; à faire avec l'opérateur présent.

## Remise en état immédiate (avant déploiement)

```bash
# Pi5 : RB2-ROS
sudo systemctl restart rb2-ap-ip.service && sudo systemctl restart hostapd.service
iw dev wlxXXXXXXXXXXXX info | grep -E 'ssid|channel'   # doit lister les deux
ip -br addr show wlxXXXXXXXXXXXX                        # doit montrer 10.42.0.1

# Zero : sortir du secours (depuis le Zero)
nmcli con modify WIFI-MAISON-2.4G connection.autoconnect yes
nmcli con down RB2-ZERO-OUVERT
nmcli con up WIFI-MAISON-2.4G
```

## Test de non-régression

À faire avec l'opérateur présent (bascule perturbatrice). Le chien de garde
PA du Pi5 (`rb2-ap-watchdog.service`) répare `hostapd` en ~30 s — pour tester
la bascule secours il faut donc aussi **masquer le chien de garde** le temps
du test, sinon il rétablit `RB2-ROS` avant les 60 s :
`sudo systemctl stop rb2-ap-watchdog.service`.

1. terrain4 → bouton Wi-Fi local → OFF (ou `nmcli con down` sur `wlan0` du
   Pi5). Couper aussi `RB2-ROS` : `sudo systemctl stop hostapd` sur le Pi5.
2. ~60 s plus tard (6 échecs × 10 s, ~60–75 s en pratique avec la latence
   SSH) : `journalctl -u rb2-zero-secours-auto`
   sur le Zero logue « RB2-ZERO-SECOURS actif » ; `10.60.0.1` répond.
3. Rétablir : `sudo systemctl start hostapd` sur le Pi5, **ou** le bouton
   « RÉTABLIR Wi-Fi Pi5 (RB2-ROS) » de la page de secours
   (`http://10.60.0.1:8088`).
4. ~60 s plus tard (6 cycles OK) : le log passe par
   « Wi-Fi Pi5 retabli pendant le secours: N/6 » puis
   « Retour au Wi-Fi local du Zero demande » et « WIFI-MAISON-2.4G reconnecte » ;
   `10.60.0.1` disparaît, le Zero est de retour sur le réseau local.
5. Vérifier `nmcli -g connection.autoconnect con show WIFI-MAISON-2.4G` = `yes`
   et `... con show RB2-ZERO-OUVERT` = `no`.
6. Tester le bouton « COUPER secours Zero + rebrancher réseau local » :
   relever le secours (`--force`), cliquer le bouton, vérifier le retour
   immédiat au réseau local.
7. Réactiver le chien de garde : `sudo systemctl start rb2-ap-watchdog.service`.
