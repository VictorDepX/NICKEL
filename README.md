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
