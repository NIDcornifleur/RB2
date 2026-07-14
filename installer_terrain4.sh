#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ACTIVE="/opt/rb2/esp32_panel.py"
SERVICE="rb2-esp32-panel.service"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="${ACTIVE}.avant-terrain4-${STAMP}"
INSTALLED=0

rollback() {
  local rc=$?
  trap - EXIT
  if [[ $rc -ne 0 && $INSTALLED -eq 1 && -f "$BACKUP" ]]; then
    echo "Échec de l'installation; restauration de $BACKUP"
    sudo cp -a "$BACKUP" "$ACTIVE"
    sudo systemctl restart "$SERVICE" || true
  fi
  exit "$rc"
}

trap rollback EXIT

test -f "$SOURCE_DIR/opt/rb2/esp32_panel.py"
test -f "$SOURCE_DIR/opt/rb2/terrain4.html"
test -f "$ACTIVE"

echo "===== VALIDATION AVANT INSTALLATION ====="
python3 -m py_compile "$SOURCE_DIR/opt/rb2/esp32_panel.py"
grep -q '@app.route("/terrain4")' "$SOURCE_DIR/opt/rb2/esp32_panel.py"
grep -q '<title>RB2 — Terrain4</title>' "$SOURCE_DIR/opt/rb2/terrain4.html"

echo
echo "===== SAUVEGARDE ====="
sudo cp -a "$ACTIVE" "$BACKUP"
echo "$BACKUP"
INSTALLED=1

echo
echo "===== INSTALLATION ====="
sudo install -o root -g root -m 0755 \
  "$SOURCE_DIR/opt/rb2/esp32_panel.py" \
  "$ACTIVE"
sudo install -o root -g root -m 0644 \
  "$SOURCE_DIR/opt/rb2/terrain4.html" \
  /opt/rb2/terrain4.html

sudo python3 -m py_compile "$ACTIVE"

echo
echo "===== REDÉMARRAGE DU PANNEAU ====="
sudo systemctl restart "$SERVICE"
sleep 3
sudo systemctl --no-pager --full status "$SERVICE"

echo
echo "===== VÉRIFICATION DE TERRAIN4 ====="
HEADERS="$(curl -fsS --max-time 5 -D - -o /tmp/rb2-terrain4-check.html http://127.0.0.1:5051/terrain4)"
grep -qi '^X-RB2-Page: terrain4-standalone' <<<"$HEADERS"
grep -q '<title>RB2 — Terrain4</title>' /tmp/rb2-terrain4-check.html
echo "Terrain4 autonome répond correctement sur http://127.0.0.1:5051/terrain4"

INSTALLED=0
trap - EXIT

echo
echo "Installation terminée. Ouvrir : http://10.42.0.1:5051/terrain4"
