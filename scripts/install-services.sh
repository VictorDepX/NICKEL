#!/usr/bin/env bash
# Cria serviços systemd de usuário (sobem no login) e o atalho `nickel-listen`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR" "$HOME/.local/bin"

BRIDGE_TOKEN="$(grep -E '^BRIDGE_TOKEN=' "$ROOT/.env" | tail -1 | cut -d= -f2-)"
if [ -z "$BRIDGE_TOKEN" ]; then
  echo "BRIDGE_TOKEN vazio no .env. Rode: .venv/bin/nickel keys"
  exit 1
fi

cat > "$UNIT_DIR/nickel.service" <<EOF
[Unit]
Description=NICKEL (API, UI, lembretes, voz)
After=network-online.target

[Service]
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/nickel serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

cat > "$UNIT_DIR/nickel-whatsapp.service" <<EOF
[Unit]
Description=NICKEL bridge do WhatsApp (open-wa)
After=nickel.service

[Service]
WorkingDirectory=$ROOT/whatsapp-bridge
Environment=NICKEL_URL=http://127.0.0.1:8000
Environment=BRIDGE_TOKEN=$BRIDGE_TOKEN
Environment=WA_MODE=self
Environment=WA_SESSION_DIR=$ROOT/data/wa-session
ExecStart=$(command -v node) src/index.mjs
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
chmod 600 "$UNIT_DIR/nickel-whatsapp.service"

cat > "$HOME/.local/bin/nickel-listen" <<EOF
#!/usr/bin/env bash
cd "$ROOT" && exec "$ROOT/.venv/bin/nickel" listen
EOF
chmod +x "$HOME/.local/bin/nickel-listen"

# Voz e notificações precisam do áudio e da sessão gráfica do usuário
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now nickel.service nickel-whatsapp.service
echo "Serviços ativos. Logs: journalctl --user -fu nickel   |   journalctl --user -fu nickel-whatsapp"
echo "Atalho de voz: aponte um atalho global do GNOME/KDE para $HOME/.local/bin/nickel-listen"
