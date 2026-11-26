<!-- Gerado por `nickel audit docs` a partir de nickel/core/events.py. Não edite à mão. -->

# Catálogo de eventos de auditoria

Cada ação relevante do NICKEL grava um evento em `AuditLog` (`kind`, `name`, `status`, `detail`).
Esta página lista os tipos (`kind`), seus estados, os campos de `detail` e o módulo que os emite.

## Tipos de evento

| kind | descrição | estados | campos | fonte |
| --- | --- | --- | --- | --- |
| `confirmation` | Ciclo de confirmação de ações sensíveis. | `requested`, `confirmed`, `cancelled`, `dropped` | `id`, `channel` | `nickel/core/agent.py` |
| `llm` | Chamadas ao modelo de linguagem. | `start`, `done`, `error` | `step`, `model`, `backend`, `requested_backend`, `think`, `duration_ms`, `prompt_tokens`, `completion_tokens`, `tokens_per_second`, `tool_calls`, `detail` | `nickel/core/agent.py` |
| `oauth` | Conexão de contas externas via OAuth (Google, Spotify). | `connected` | - | `nickel/app.py` |
| `outbound` | Envio de mensagens proativas por um canal. | `ok`, `undelivered` | `text` | `nickel/core/outbound.py` |
| `prompt` | Montagem do prompt enviado ao modelo. | `built` | `messages`, `history`, `tools`, `system_chars`, `est_tokens` | `nickel/core/agent.py` |
| `reasoning` | Raciocínio do modelo (parcial e final) e o início da resposta. | `progress`, `answering`, `final` | `step`, `chars`, `tokens_est`, `headline`, `tail`, `content_chars`, `text`, `conclusion`, `tools_mentioned` | `nickel/core/reasoning.py` |
| `route` | Resolução da rota (workspace/skill) de um turno. | `resolved` | `command`, `workspace`, `switched`, `auto` | `nickel/core/agent.py` |
| `system` | Ciclo de vida e saúde do sistema. | `startup`, `shutdown`, `health` | `version`, `llm`, `workspace_count`, `whatsapp`, `google`, `spotify`, `obsidian`, `voice` | `nickel/app.py` |
| `tool` | Execução de ferramentas pelo agente. | `start`, `ok`, `error` | `arguments`, `summary`, `detail` | `nickel/core/agent.py` |
| `tts` | Fala (síntese e reprodução) de uma resposta: GUI, voz, botão Ouvir e nota de voz do WhatsApp; `skipped` = nota de voz pulada porque já havia uma fala. | `start`, `done`, `error`, `skipped` | `source`, `chars`, `provider`, `voice`, `interrupted`, `detail` | `nickel/services.py` |
| `turn` | Ciclo completo de um turno de conversa. | `start`, `done`, `error` | `channel`, `workspace`, `chars`, `duration_ms`, `steps`, `reply_chars`, `detail` | `nickel/core/agent.py` |
| `voice` | Estados do pipeline de voz. | `listening`, `transcribing`, `thinking`, `speaking`, `idle`, `error` | `chars`, `detail` | `nickel/channels/voice.py` |
| `whatsapp` | Mensagens recebidas e respondidas pelo canal WhatsApp. | `received`, `replied`, `error` | `type`, `id`, `chars`, `voice`, `detail` | `nickel/channels/whatsapp.py` |

## Fases da interface

O monitor deduz a fase atual a partir do último evento que muda de fase.

| kind | status | fase |
| --- | --- | --- |
| `confirmation` | `requested` | Aguardando confirmação (`confirming`) |
| `llm` | `error` | Erro (`error`) |
| `llm` | `start` | Pensando (`thinking`) |
| `prompt` | `built` | Pensando (`thinking`) |
| `reasoning` | `answering` | Respondendo (`answering`) |
| `reasoning` | `progress` | Pensando (`thinking`) |
| `route` | `resolved` | Montando prompt (`prompting`) |
| `tool` | `error` | Pensando (`thinking`) |
| `tool` | `ok` | Pensando (`thinking`) |
| `tool` | `start` | Executando ferramenta (`tool`) |
| `tts` | `done` | Ocioso (`idle`) |
| `tts` | `error` | Erro (`error`) |
| `tts` | `start` | Falando (`speaking`) |
| `turn` | `done` | Ocioso (`idle`) |
| `turn` | `error` | Erro (`error`) |
| `turn` | `start` | Roteando (`routing`) |
| `voice` | `idle` | Ocioso (`idle`) |
| `voice` | `listening` | Ouvindo (`listening`) |
| `voice` | `speaking` | Falando (`speaking`) |
| `voice` | `transcribing` | Transcrevendo (`transcribing`) |
