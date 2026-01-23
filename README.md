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
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_API_KEY="..."
export LLM_MODEL="gpt-4o-mini"
export LLM_TIMEOUT_SECONDS="30"
export TOKEN_STORE_PATH="./data/token_store.json"
export PENDING_ACTIONS_PATH="./data/pending_actions.json"
export NOTES_STORE_PATH="./data/notes.json"
export SPOTIFY_ACCESS_TOKEN="..."
export SPOTIFY_DEVICE_ID="..."
export SPOTIFY_BASE_URL="https://api.spotify.com/v1"
```

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

- Envie mensagens para `/chat` com `{ "message": "..." }`.

## Notes (write)

- Crie nota em `/tools/notes/create` (com confirmação).

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
