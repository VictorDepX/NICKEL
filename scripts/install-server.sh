#!/usr/bin/env bash
# Instala o NICKEL numa VM sem GPU (Oracle Cloud Always Free, Ubuntu 24.04, ARM ou x86).
# O modelo roda fora, no RunPod Serverless. Guia completo: docs/deploy/oracle-runpod.md
# Uso: ./scripts/install-server.sh   (a partir da raiz do repositório)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

NODE_MAJOR=22
PLAYWRIGHT_VERSION=1.64.1

step() { printf '\n==> %s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1; }

set_env() {
  # set_env CHAVE VALOR — troca a linha CHAVE= no .env, ou acrescenta no fim.
  .venv/bin/python - "$1" "$2" <<'PY'
import pathlib, sys
key, value = sys.argv[1], sys.argv[2]
path = pathlib.Path(".env")
lines = path.read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if line.startswith(f"{key}="):
        lines[index] = f"{key}={value}"
        break
else:
    lines.append(f"{key}={value}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

step "Pacotes do sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-dev ffmpeg git curl ca-certificates syncthing

step "Node.js $NODE_MAJOR"
if ! need node || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | sudo -E bash -
  sudo apt-get install -y -qq nodejs
fi

step "Ambiente Python (.venv)"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e '.[server,dev]'

step "Chromium para a bridge (Playwright $PLAYWRIGHT_VERSION; funciona em ARM64)"
CHROMIUM_DIR="$ROOT/data/chromium"
mkdir -p "$CHROMIUM_DIR"
(
  cd "$CHROMIUM_DIR"
  [ -f package.json ] || npm init -y >/dev/null
  npm install --no-audit --no-fund "playwright@$PLAYWRIGHT_VERSION" >/dev/null
  npx playwright install --with-deps chromium
)
CHROME_PATH="$(cd "$CHROMIUM_DIR" && node -e "console.log(require('playwright').chromium.executablePath())")"
if [ ! -x "$CHROME_PATH" ]; then
  echo "Chromium não encontrado em $CHROME_PATH"
  exit 1
fi

step "Bridge do WhatsApp"
(cd whatsapp-bridge && PUPPETEER_SKIP_DOWNLOAD=1 npm install --no-audit --no-fund)

step "Voz do Piper (só para respostas em áudio no WhatsApp)"
mkdir -p models/piper
if [ ! -f models/piper/pt_BR-faber-medium.onnx ]; then
  (cd models/piper && "$ROOT/.venv/bin/python" -m piper.download_voices pt_BR-faber-medium) || \
    echo "Voz não baixada; respostas em áudio ficam indisponíveis (WA_VOICE_REPLIES=false)."
fi

step ".env de servidor"
if [ ! -f .env ]; then
  cp .env.example .env
  KEYS="$(.venv/bin/nickel keys)"
  set_env OAUTH_TOKEN_KEY "$(printf '%s\n' "$KEYS" | grep '^OAUTH_TOKEN_KEY=' | cut -d= -f2-)"
  set_env BRIDGE_TOKEN "$(printf '%s\n' "$KEYS" | grep '^BRIDGE_TOKEN=' | cut -d= -f2-)"
  set_env LLM_PROVIDER openai
  set_env LLM_BASE_URL "https://api.runpod.ai/v2/SEU_ENDPOINT_ID/openai/v1"
  set_env LLM_MODEL qwen3.6-27b
  set_env LLM_TIMEOUT_SECONDS 300
  set_env VOICE_ENABLED false
  set_env VOICE_NOTIFY false
  set_env STT_MODEL small
  set_env STT_DEVICE cpu
  set_env STT_COMPUTE_TYPE int8
  set_env OBSIDIAN_VAULT_PATH "$HOME/Editora"
  echo "Criado .env de servidor. Falta preencher LLM_BASE_URL, LLM_API_KEY, Google e Spotify."
fi
set_env CHROME_PATH "$CHROME_PATH"

step "Syncthing (sincroniza o vault com o PC)"
mkdir -p "$HOME/Editora"
loginctl enable-linger "$USER" 2>/dev/null || sudo loginctl enable-linger "$USER"
systemctl --user enable --now syncthing.service || echo "Inicie o Syncthing manualmente: systemctl --user start syncthing"

step "Verificação"
.venv/bin/nickel doctor || true

cat <<'MSG'

Próximos passos (detalhes em docs/deploy/oracle-runpod.md):
  1. Edite o .env: LLM_BASE_URL (ID do endpoint), LLM_API_KEY, Google e Spotify.
  2. Suba os serviços:      ./scripts/install-services.sh
  3. Pareie o WhatsApp:     journalctl --user -fu nickel-whatsapp   (escaneie o QR)
  4. No seu PC, abra o túnel e use a UI e o Syncthing:
       ssh -L 8000:127.0.0.1:8000 -L 8384:127.0.0.1:8384 ubuntu@IP_DA_VM
       UI: http://localhost:8000      Syncthing: http://localhost:8384
MSG
