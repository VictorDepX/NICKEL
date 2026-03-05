# NICKEL v1.0

Assistente pessoal orientado a ferramentas, com API FastAPI e CLI, integrado a Google Workspace (Gmail + Calendar), Spotify, memória opt-in, auditoria e fluxo de confirmações para ações sensíveis.

## Visão geral

O NICKEL foi projetado para separar **planejamento** e **execução** de ações:
- Planeja com LLM (`/chat/plan`)
- Executa ação explicitamente (`/chat/execute`) ou via fluxo compatível (`/chat`)
- Exige confirmação para operações de escrita críticas (`/confirm` e `/cancel`)

## Principais recursos

- **Google Workspace**
  - Gmail: pesquisa, leitura, rascunho e envio
  - Calendar: listagem, criação e alteração de eventos
- **Spotify**
  - Play, pause e skip
  - OAuth dedicado do Spotify + fallback por token manual
- **Memória opt-in** (`/memory/ask`, `/memory/confirm`, `GET /memory`)
- **Auditoria** (`GET /audit`)
- **Persistência local** de tokens, ações pendentes, notas, tarefas, memória e trilha de auditoria

## Requisitos

- Python 3.11+

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuração de ambiente

> **Importante:** nunca commite credenciais reais. Use valores de exemplo no `.env` e segredos reais apenas no ambiente de execução.

```bash
# Google OAuth
export GOOGLE_CLIENT_ID="your_google_client_id"
export GOOGLE_CLIENT_SECRET="your_google_client_secret"
export GOOGLE_REDIRECT_URI="http://localhost:8000/auth/google/callback"
export GOOGLE_SCOPES="https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.compose,https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/calendar.events"

# Chave para criptografia de tokens OAuth no armazenamento local
export OAUTH_TOKEN_KEY="your_fernet_key"

# LLM provider
export LLM_BASE_URL="https://api.groq.com/openai/v1"
export LLM_API_KEY="your_llm_api_key"
export LLM_MODEL="llama-3.1-8b-instant"
export LLM_TIMEOUT_SECONDS="60"

# Persistência local
export TOKEN_STORE_PATH="./data/token_store.json"
export PENDING_ACTIONS_PATH="./data/pending_actions.json"
export NOTES_STORE_PATH="./data/notes.json"
export TASKS_STORE_PATH="./data/tasks.json"
export MEMORY_STORE_PATH="./data/memory.json"
export AUDIT_STORE_PATH="./data/audit.json"

# Spotify OAuth
export SPOTIFY_CLIENT_ID="your_spotify_client_id"
export SPOTIFY_CLIENT_SECRET="your_spotify_client_secret"
export SPOTIFY_REDIRECT_URI="http://localhost:8000/auth/spotify/callback"
export SPOTIFY_SCOPES="user-read-playback-state,user-modify-playback-state,user-read-currently-playing"

# Spotify opcional (modo manual/fallback)
export SPOTIFY_ACCESS_TOKEN="optional_spotify_access_token"
export SPOTIFY_DEVICE_ID="optional_device_id"
export SPOTIFY_BASE_URL="https://api.spotify.com/v1"
```

### Gerando `OAUTH_TOKEN_KEY`

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode("utf-8"))
PY
```

## Execução

### API + CLI (modo rápido)

```bash
make start
```

## Teste conversacional pela CLI

```bash
export NICKEL_API_BASE_URL="http://localhost:8000"
python -m cli.main
```

A CLI mantém histórico local para conversas multi-turno e suporta confirmações com `/confirm` e `/cancel`.

## OAuth Google

- Inicie o fluxo em `/auth/google/start`.
- Complete o fluxo em `/auth/google/callback?code=...&state=...`.

## Calendar (read-only)

- Liste eventos em `/tools/calendar/list_events`.

## Email (read-only)

- Pesquise emails em `/tools/email/search`.
- Leia emails em `/tools/email/read`.

## Email (write)

- Crie rascunho em `/tools/email/draft` (sem confirmação).
- Envie email em `/tools/email/send` (com confirmação).

## Chat (LLM)

- Compatibilidade: continue usando `POST /chat` com `{ "message": "..." }`.
- Novo planejamento: `POST /chat/plan` retorna plano estruturado com `response`, `action`, `confidence`, `requires_confirmation` e **não executa tool**.
- Nova execução: `POST /chat/execute` executa uma ação já planejada (ou responde normalmente quando `action` é `null`).
- Fluxo unificado: internamente, `/chat` usa `plan -> execute`.
- Para manter contexto entre turnos, envie também `history`, por exemplo `{ "message": "...", "history": [{"role":"user","content":"..."},{"role":"assistant","content":"..."}] }`.
- Benefícios do split plan/execute: depuração mais simples, UI mais previsível e menor acoplamento com o provider de LLM.
### Execução separada

```bash
make api   # API em http://localhost:8000
make cli   # CLI conectada à API
```

## Fluxos OAuth

### Google
- Iniciar: `GET /auth/google/start`
- Callback: `GET /auth/google/callback?code=...&state=...`

### Spotify
- Iniciar: `GET /auth/spotify/start`
- Callback: `GET /auth/spotify/callback?code=...&state=...`
- Alternativa: usar `SPOTIFY_ACCESS_TOKEN` manualmente

## Endpoints de ferramentas

### Calendar
- `POST /tools/calendar/list_events`
- `POST /tools/calendar/create_event` *(requer confirmação)*
- `POST /tools/calendar/modify_event` *(requer confirmação)*

### Email
- `POST /tools/email/search`
- `POST /tools/email/read`
- `POST /tools/email/draft`
- `POST /tools/email/send` *(requer confirmação)*

### Spotify
- `POST /tools/spotify/play`
- `POST /tools/spotify/pause`
- `POST /tools/spotify/skip`

### Notes / Tasks
- `POST /tools/notes/create` *(requer confirmação)*
- `POST /tools/tasks/create` *(requer confirmação)*
- `POST /tools/tasks/list`

## Chat

- Compatível: `POST /chat`
- Planejamento sem execução: `POST /chat/plan`
- Execução explícita: `POST /chat/execute`
- Suporte a histórico via `history` no payload

## Confirmação de ações

Ações de escrita sensíveis não executam imediatamente:
1. API cria `pending_action`
2. Cliente confirma via `POST /confirm` com `action_id` e `confirmed: true`
3. Ou cancela via `POST /cancel`

## Observabilidade

- **Memória opt-in:** `/memory/ask`, `/memory/confirm`, `GET /memory`
- **Auditoria:** `GET /audit`

## Testes

```bash
pytest
```

---

## Versão

Este README descreve o **NICKEL v1.0**.
