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
export LLM_BASE_URL="http://localhost:11434/v1"
export LLM_API_KEY="ollama"
export LLM_MODEL="qwen2.5:7b-instruct"
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


## LLM local (Qwen via Ollama)

```bash
# Instale o Ollama: https://ollama.com/download
ollama pull qwen2.5:7b-instruct
ollama serve
```

Com o Ollama ativo, o NICKEL usa `LLM_BASE_URL=http://localhost:11434/v1` e o modelo `qwen2.5:7b-instruct`.

## Executar

```bash
uvicorn app.main:app --reload
```

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

- Envie mensagens para `/chat` com `{ "message": "..." }` para conversa normal.
- Para manter contexto entre turnos, envie também `history`, por exemplo `{ "message": "...", "history": [{"role":"user","content":"..."},{"role":"assistant","content":"..."}] }`.
- Use a interface web em `/ui` (ela mantém o histórico automaticamente).

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
