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
- `/status` mostra base_url, turnos em memória e estado de pending_action
- `/confirm` confirma a ação pendente
- `/cancel` cancela a ação pendente
- `/reset` zera o histórico

## Persistência local

A sessão é salva em `.nickel_session.json` com:
- `history` (turnos user/assistant)
- `pending_action`

## Visual retro

A interface usa caixas ANSI no terminal para simular um painel retro e facilitar o acompanhamento da conversa.
