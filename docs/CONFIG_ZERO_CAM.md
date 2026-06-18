
## Synchronisation de l’heure Zero 2 W

Le Zero 2 W `rb2cam` n’a pas besoin d’accès Internet direct pour l’heure.

Configuration validée :

- Pi5 `rb2-ros` : serveur NTP sur `10.50.0.1`
- Zero 2 W `rb2cam` : client `systemd-timesyncd`
- Serveur configuré sur le Zero : `10.50.0.1`

Fichier sur le Zero :

/etc/systemd/timesyncd.conf.d/rb2-pi5.conf

Contenu :

[Time]
NTP=10.50.0.1
FallbackNTP=

Validation :

timedatectl timesync-status
timedatectl

Résultat attendu :

Server: 10.50.0.1
System clock synchronized: yes
NTP service: active
