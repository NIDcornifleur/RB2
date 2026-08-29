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

**Déploiement effectif 2026-08-29** : faute d'accès `sudo` non interactif dans
la session, le service a été installé sans le `sudo install` ci-dessus —
script copié dans `~/rb2_scripts/rb2_ap_watchdog.py`, unité
`~/rb2_scripts/rb2-ap-watchdog.service` (même contenu, `ExecStart` adapté)
rattachée par `sudo systemctl link` + `enable --now`. Il tourne et a corrigé
une panne réelle dès le démarrage (dongle ré-énuméré à 16:55, hostapd
orphelin, RB2-ROS muet jusqu'à la réparation à 18:00). Migration propre vers
`/opt/rb2` quand `sudo` interactif est dispo :

```bash
sudo systemctl disable --now rb2-ap-watchdog.service
sudo rm /etc/systemd/system/rb2-ap-watchdog.service        # supprime le symlink
sudo install -o root -g root -m 0755 opt/rb2/rb2_ap_watchdog.py /opt/rb2/rb2_ap_watchdog.py
sudo install -o root -g root -m 0644 systemd/rb2-ap-watchdog.service /etc/systemd/system/rb2-ap-watchdog.service
rm ~/rb2_scripts/rb2_ap_watchdog.py ~/rb2_scripts/rb2-ap-watchdog.service
sudo systemctl daemon-reload && sudo systemctl enable --now rb2-ap-watchdog.service
```

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

1. terrain4 → bouton Wi-Fi local → OFF. Couper aussi `RB2-ROS`
   (`sudo systemctl stop hostapd`).
2. ~60 s plus tard : `RB2-ZERO-SECOURS` / `10.60.0.1` apparaît.
3. `sudo systemctl start hostapd` (ou bouton « RÉTABLIR Wi-Fi Pi5 »).
4. ~60 s plus tard : `journalctl -u rb2-zero-secours-auto` logue
   « Retour au Wi-Fi local du Zero demande » ; le Zero repasse sur
   `WIFI-MAISON-2.4G`, `10.60.0.1` disparaît.
5. Vérifier `nmcli -g connection.autoconnect con show WIFI-MAISON-2.4G` = `yes`.
