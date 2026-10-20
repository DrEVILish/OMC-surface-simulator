#!/bin/bash
# Install the PRO web surfaces on the OMC host. Run from the repository directory:
#   deploy/install.sh            (needs www/panel.svg and www/controls.json from gen-surface.py;
#                                 the PRO2 / PRO2C / PRO X from deploy/gen-surfaces.sh, in www/models/)
# The PRO1 is the default page; the header's model selector (or ?model=pro2|pro2c|prox) opens the
# others that www/models/index.json lists.
set -e
cd "$(dirname "$0")/.."
apt-get install -y nginx python3-websockets >/dev/null
install -d /var/www/omc-surface-simulator /opt/omc-surface-simulator
install -m 644 www/index.html www/surface.css www/surface.js www/vegas.js www/panel.svg www/controls.json /var/www/omc-surface-simulator/
# the other models: each one's generated panel.svg + controls.json, and the list for the selector
rm -rf /var/www/omc-surface-simulator/models
install -d /var/www/omc-surface-simulator/models
models=()
for d in www/models/*/; do
  m=$(basename "$d")
  [ -f "$d/panel.svg" ] && [ -f "$d/controls.json" ] || continue
  install -d "/var/www/omc-surface-simulator/models/$m"
  install -m 644 "$d/panel.svg" "$d/controls.json" "/var/www/omc-surface-simulator/models/$m/"
  models+=("\"$m\"")
done
(IFS=,; echo "[${models[*]}]") > /var/www/omc-surface-simulator/models/index.json
chmod 644 /var/www/omc-surface-simulator/models/index.json
install -m 755 bridge.py /opt/omc-surface-simulator/bridge.py
# the old names (pro1-surface site and web root) go when upgrading
rm -f /etc/nginx/sites-enabled/pro1-surface /etc/nginx/sites-available/pro1-surface
rm -rf /var/www/pro1-surface
install -m 644 deploy/nginx-omc-surface-simulator.conf /etc/nginx/sites-available/omc-surface-simulator
ln -sf /etc/nginx/sites-available/omc-surface-simulator /etc/nginx/sites-enabled/omc-surface-simulator
rm -f /etc/nginx/sites-enabled/default
# the old unit name (pro1-bridge) goes when upgrading
systemctl disable --now pro1-bridge 2>/dev/null || true
rm -f /etc/systemd/system/pro1-bridge.service
install -m 644 deploy/omc-surface-simulator-bridge.service /etc/systemd/system/omc-surface-simulator-bridge.service
systemctl daemon-reload
systemctl enable --now omc-surface-simulator-bridge
systemctl restart omc-surface-simulator-bridge
nginx -t && systemctl reload nginx
echo "OMC-surface-simulator: http://$(hostname -I | awk '{print $1}')/  (other models: $(cat /var/www/omc-surface-simulator/models/index.json))"
