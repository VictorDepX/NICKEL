# NICKEL

Boilerplate do Nickel com FastAPI e OAuth Google (Gmail + Calendar).

## Requisitos

- Python 3.11+

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Variáveis de ambiente

```bash
export GOOGLE_CLIENT_ID="..."
export GOOGLE_CLIENT_SECRET="..."
export GOOGLE_REDIRECT_URI="http://localhost:8000/auth/google/callback"
export GOOGLE_SCOPES="https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.compose,https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/calendar.events"
export OAUTH_TOKEN_KEY="cole_uma_chave_fernet"
export LLM_BASE_URL="https://api.groq.com/openai/v1"
export LLM_API_KEY="gsk_..."
export LLM_MODEL="llama-3.1-8b-instant"
export LLM_TIMEOUT_SECONDS="60"
export TOKEN_STORE_PATH="./data/token_store.json"
export PENDING_ACTIONS_PATH="./data/pending_actions.json"
export NOTES_STORE_PATH="./data/notes.json"
export TASKS_STORE_PATH="./data/tasks.json"
export MEMORY_STORE_PATH="./data/memory.json"
export AUDIT_STORE_PATH="./data/audit.json"
export SPOTIFY_ACCESS_TOKEN="..."
export SPOTIFY_DEVICE_ID="..."
export SPOTIFY_BASE_URL="https://api.spotify.com/v1"
```


## LLM via GroqCloud (sem hospedagem local)

Crie uma API key no GroqCloud e configure:

```bash
export LLM_BASE_URL="https://api.groq.com/openai/v1"
export LLM_API_KEY="gsk_..."
export LLM_MODEL="llama-3.1-8b-instant"
```

Com essa configuração o NICKEL consome a API do GroqCloud, sem necessidade de rodar modelo local.

## Executar

```bash
make start
```

Esse comando sobe a API e já abre a CLI conectada em `http://localhost:8000` para teste imediato.

Se quiser subir separado:

```bash
make api   # só API
make cli   # só CLI
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

## Memória (opt-in)

- Proponha memória em `/memory/ask` com `{ "key": "...", "value": "..." }`.
- Confirme memória em `/memory/confirm` com `{ "memory_id": "...", "confirmed": true }`.
- Liste memórias em `GET /memory`.

## Auditoria

- Liste eventos em `GET /audit`.

## Notes (write)

- Crie nota em `/tools/notes/create` (com confirmação).

## Tasks

- Crie tarefa em `/tools/tasks/create` (com confirmação).
- Liste tarefas em `/tools/tasks/list`.

## Spotify

- Toque algo em `/tools/spotify/play`.
- Pause em `/tools/spotify/pause`.
- Próxima faixa em `/tools/spotify/skip`.

## Confirmação de ações (write)

- Tools de escrita criam um `pending_action`.
- Confirme com `POST /confirm` enviando `action_id` e `confirmed: true`.
- Cancele com `POST /cancel` enviando `action_id` e `confirmed: true`.

## Gerar chave OAUTH_TOKEN_KEY

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode("utf-8"))
PY
```

## Testes

```bash
pytest
```
