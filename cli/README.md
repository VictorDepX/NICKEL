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


## Exemplos de conversa

### Tool desconectada

```text
> Leia meus e-mails não lidos
╔ NICKEL ═══════════════════════════════════════════════════════════════════════╗
║ Posso consultar seu Gmail quando a conexão estiver pronta.                   ║
╚═══════════════════════════════════════════════════════════════════════════════╝
╔ CONEXÃO PENDENTE ═════════════════════════════════════════════════════════════╗
║ Não consegui acessar seu Gmail agora. Posso te passar o link para conectar   ║
║ a conta.                                                                     ║
║                                                                              ║
║ Link de conexão:                                                             ║
║ https://example.com/oauth                                                    ║
╚═══════════════════════════════════════════════════════════════════════════════╝
╔ PRÓXIMO PASSO ════════════════════════════════════════════════════════════════╗
║ Abra o link acima para conectar a conta e depois tente novamente o pedido.   ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

### Pedido ambíguo

```text
> Organize meus e-mails do João
╔ NICKEL ═══════════════════════════════════════════════════════════════════════╗
║ Você quer arquivar, responder ou apagar os e-mails do João?                  ║
╚═══════════════════════════════════════════════════════════════════════════════╝
╔ INCERTEZA ════════════════════════════════════════════════════════════════════╗
║ Não tenho certeza suficiente para executar isso sozinho.                     ║
╚═══════════════════════════════════════════════════════════════════════════════╝
╔ PRÓXIMO PASSO ════════════════════════════════════════════════════════════════╗
║ Você quer arquivar, responder ou apagar os e-mails do João?                  ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

### Ação sensível com confirmação

```text
> Envie o e-mail para o financeiro agora
╔ NICKEL ═══════════════════════════════════════════════════════════════════════╗
║ Posso enviar esse e-mail para o financeiro.                                  ║
╚═══════════════════════════════════════════════════════════════════════════════╝
╔ CONFIRMAÇÃO ══════════════════════════════════════════════════════════════════╗
║ Ação pendente: email.send                                                    ║
║ id: act-123                                                                  ║
║ Use /confirm para executar ou /cancel para descartar.                        ║
╚═══════════════════════════════════════════════════════════════════════════════╝
╔ PRÓXIMO PASSO ════════════════════════════════════════════════════════════════╗
║ Se estiver tudo certo, responda com /confirm ou use /cancel para abortar.    ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```
