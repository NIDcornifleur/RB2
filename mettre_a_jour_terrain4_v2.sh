#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SOURCE_DIR/opt/rb2/terrain4.html"
ACTIVE="/opt/rb2/terrain4.html"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="${ACTIVE}.avant-correctif-v21-${STAMP}"
BACKED_UP=0

rollback() {
  local rc=$?
  trap - EXIT
  if [[ $rc -ne 0 && $BACKED_UP -eq 1 && -f "$BACKUP" ]]; then
    echo "Échec de la mise à jour; restauration de $BACKUP"
    sudo cp -a "$BACKUP" "$ACTIVE"
  fi
  exit "$rc"
}

trap rollback EXIT

echo "===== VALIDATION ====="
test -f "$SOURCE"
test -f "$ACTIVE"
grep -q 'id="lidarCanvas"' "$SOURCE"
grep -q 'fetchJson("/lidar_map"' "$SOURCE"
grep -q 'fetchJson("/lidar_map", {}, 7000)' "$SOURCE"
grep -q 'état relu sur RB2' "$SOURCE"
grep -q 'id="shutdownBtn"' "$SOURCE"
if grep -qE 'Télémétrie minimale|IMU / Encodeurs|Journal local' "$SOURCE"; then
  echo "La page contient encore un bloc qui devait être retiré." >&2
  exit 1
fi

echo
echo "===== SAUVEGARDE ====="
sudo cp -a "$ACTIVE" "$BACKUP"
BACKED_UP=1
echo "$BACKUP"

echo
echo "===== MISE À JOUR DE TERRAIN4 ====="
sudo install -o root -g root -m 0644 "$SOURCE" "$ACTIVE"

echo
echo "===== VÉRIFICATION HTTP ====="
curl -fsS --max-time 5 http://127.0.0.1:5051/terrain4 \
  -o /tmp/rb2-terrain4-v2-check.html
grep -q 'id="lidarCanvas"' /tmp/rb2-terrain4-v2-check.html
grep -q 'id="shutdownBtn"' /tmp/rb2-terrain4-v2-check.html
if grep -qE 'Télémétrie minimale|IMU / Encodeurs|Journal local' \
  /tmp/rb2-terrain4-v2-check.html; then
  echo "Le serveur ne retourne pas la nouvelle version." >&2
  exit 1
fi

BACKED_UP=0
trap - EXIT

echo "Terrain4 v2.1 est installée. Aucun redémarrage requis."
echo "Actualiser avec Ctrl+F5 : http://10.42.0.1:5051/terrain4"
