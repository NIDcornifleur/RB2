#!/bin/bash
# RB2 - Arrêter le Zero 2 W caméra avant l'arrêt du Pi 5
# Important : SSH est lancé comme utilisateur rj, pas comme root.

ZERO_IP="10.42.0.20"
ZERO_HOST="rj@10.42.0.20"
LOG="/var/log/rb2-shutdown-zero.log"

SSH_RJ="/usr/bin/sudo -u rj -H /usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=accept-new"

{
  echo
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') : arrêt Zero demandé avant arrêt Pi 5 ====="

  if ping -c 1 -W 2 "$ZERO_IP" >/dev/null 2>&1; then
    echo "Zero 2 W joignable. Tentative d'arrêt via SSH utilisateur rj..."

    echo "--- Essai : /usr/bin/systemctl poweroff ---"
    if $SSH_RJ "$ZERO_HOST" "sudo -n /usr/bin/systemctl poweroff"; then
      echo "OK : commande envoyée via /usr/bin/systemctl poweroff"
      sleep 4
      echo "Fin script arrêt Zero."
      exit 0
    else
      echo "Échec : /usr/bin/systemctl poweroff"
    fi

    echo "--- Essai : /bin/systemctl poweroff ---"
    if $SSH_RJ "$ZERO_HOST" "sudo -n /bin/systemctl poweroff"; then
      echo "OK : commande envoyée via /bin/systemctl poweroff"
      sleep 4
      echo "Fin script arrêt Zero."
      exit 0
    else
      echo "Échec : /bin/systemctl poweroff"
    fi

    echo "--- Essai : /usr/sbin/shutdown -h now ---"
    if $SSH_RJ "$ZERO_HOST" "sudo -n /usr/sbin/shutdown -h now"; then
      echo "OK : commande envoyée via /usr/sbin/shutdown -h now"
      sleep 4
      echo "Fin script arrêt Zero."
      exit 0
    else
      echo "Échec : /usr/sbin/shutdown -h now"
    fi

    echo "--- Essai : /sbin/shutdown -h now ---"
    if $SSH_RJ "$ZERO_HOST" "sudo -n /sbin/shutdown -h now"; then
      echo "OK : commande envoyée via /sbin/shutdown -h now"
      sleep 4
      echo "Fin script arrêt Zero."
      exit 0
    else
      echo "Échec : /sbin/shutdown -h now"
    fi

    echo "ERREUR : impossible d'envoyer l'arrêt au Zero"

  else
    echo "Zero 2 W non joignable. Arrêt Pi 5 poursuivi."
  fi

  echo "Fin script arrêt Zero."
} >> "$LOG" 2>&1

exit 0
