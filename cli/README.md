# Nickel CLI

Interface de console para conversar com o Nickel via backend FastAPI.

## Requisitos

- Python 3.11+
- requests

## Executar

```bash
export NICKEL_API_BASE_URL="http://localhost:8000"
python -m cli.main
```

## Comandos

- `/help` lista comandos
- `/exit` encerra
- `/clear` limpa a tela
- `/confirm` confirma a ação pendente
- `/cancel` cancela a ação pendente
- `/status` mostra base_url, session_id e estado de pending_action

## Persistência local

A sessão é salva em `.nickel_session.json` com `session_id` e `pending_action`.
