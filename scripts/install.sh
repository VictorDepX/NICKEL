#!/usr/bin/env bash
# Instalação do NICKEL v2 numa máquina Linux com GPU NVIDIA.
# Uso: ./scripts/install.sh            (a partir da raiz do repositório)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

step() { printf '\n==> %s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1; }

step "Pacotes do sistema (ffmpeg, áudio, notificações)"
if need apt-get; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv python3-dev ffmpeg libportaudio2 libnotify-bin pulseaudio-utils curl
elif need dnf; then
  sudo dnf install -y python3-devel ffmpeg portaudio libnotify pulseaudio-utils curl
elif need pacman; then
  sudo pacman -S --needed --noconfirm python ffmpeg portaudio libnotify libpulse curl
else
  echo "Gerenciador de pacotes não reconhecido: instale ffmpeg, portaudio, libnotify e pulseaudio-utils."
fi

step "Ollama"
if ! need ollama; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
MODEL="$(grep -E '^LLM_MODEL=' .env 2>/dev/null | cut -d= -f2 || true)"
MODEL="${MODEL:-qwen3.6:27b}"
ollama pull "$MODEL"

step "Ambiente Python (.venv)"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e '.[all,dev]'

step "Voz do Piper (pt_BR-faber-medium)"
mkdir -p models/piper
if [ ! -f models/piper/pt_BR-faber-medium.onnx ]; then
  (cd models/piper && "$ROOT/.venv/bin/python" -m piper.download_voices pt_BR-faber-medium)
fi

step "Bridge do WhatsApp (Node >= 20)"
if ! need node || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  echo "Instale o Node.js 20+ (https://nodejs.org) e rode: cd whatsapp-bridge && npm install"
else
  (cd whatsapp-bridge && npm install --no-audit --no-fund)
fi

step ".env"
if [ ! -f .env ]; then
  cp .env.example .env
  KEYS="$(.venv/bin/nickel keys)"
  OAUTH="$(printf '%s\n' "$KEYS" | grep '^OAUTH_TOKEN_KEY=' | cut -d= -f2-)"
  BRIDGE="$(printf '%s\n' "$KEYS" | grep '^BRIDGE_TOKEN=' | cut -d= -f2-)"
  sed -i "s|^OAUTH_TOKEN_KEY=.*|OAUTH_TOKEN_KEY=$OAUTH|; s|^BRIDGE_TOKEN=.*|BRIDGE_TOKEN=$BRIDGE|" .env
  echo "Criado .env com chaves novas. Revise OBSIDIAN_VAULT_PATH, Google e Spotify."
fi

step "Verificação"
.venv/bin/nickel doctor || true

cat <<'MSG'

Próximos passos:
  1. Revise o .env (vault, Google, Spotify).
  2. Serviços de usuário:   ./scripts/install-services.sh
  3. Parear o WhatsApp:     journalctl --user -fu nickel-whatsapp   (escaneie o QR)
  4. Atalho de voz:         configure um atalho global para "$HOME/.local/bin/nickel-listen"
  5. UI local:              http://127.0.0.1:8000
MSG
