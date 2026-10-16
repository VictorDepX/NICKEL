#!/usr/bin/env bash
# Cria serviços systemd de usuário para o NICKEL e a bridge do WhatsApp.
# Funciona no desktop (sobem no login) e em servidor (sobem no boot, via linger).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR" "$HOME/.local/bin"

env_value() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

BRIDGE_TOKEN="$(env_value BRIDGE_TOKEN)"
if [ -z "$BRIDGE_TOKEN" ]; then
  echo "BRIDGE_TOKEN vazio no .env. Rode: .venv/bin/nickel keys"
  exit 1
fi
CHROME_PATH="$(env_value CHROME_PATH)"
PORT="$(env_value NICKEL_PORT)"
PORT="${PORT:-8000}"

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

{
  cat <<EOF
[Unit]
Description=NICKEL bridge do WhatsApp (open-wa)
After=nickel.service

[Service]
WorkingDirectory=$ROOT/whatsapp-bridge
Environment=NICKEL_URL=http://127.0.0.1:$PORT
Environment=BRIDGE_TOKEN=$BRIDGE_TOKEN
Environment=WA_MODE=self
Environment=WA_SESSION_DIR=$ROOT/data/wa-session
EOF
  [ -n "$CHROME_PATH" ] && echo "Environment=CHROME_PATH=$CHROME_PATH"
  cat <<EOF
ExecStart=$(command -v node) src/index.mjs
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
} > "$UNIT_DIR/nickel-whatsapp.service"
chmod 600 "$UNIT_DIR/nickel-whatsapp.service"

cat > "$HOME/.local/bin/nickel-listen" <<EOF
#!/usr/bin/env bash
cd "$ROOT" && exec "$ROOT/.venv/bin/nickel" listen
EOF
chmod +x "$HOME/.local/bin/nickel-listen"

# Servidor: mantém os serviços de usuário rodando sem sessão aberta (sobem no boot).
loginctl enable-linger "$USER" 2>/dev/null || sudo loginctl enable-linger "$USER"

# Desktop: voz e notificações precisam do áudio e da sessão gráfica do usuário.
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now nickel.service nickel-whatsapp.service
echo "Serviços ativos. Logs: journalctl --user -fu nickel   |   journalctl --user -fu nickel-whatsapp"
echo "Atalho de voz (desktop): aponte um atalho global para $HOME/.local/bin/nickel-listen"
