# Observabilidade, auditoria e voz do NICKEL: especificação

Origem: pedido do Victor em 2026-11-19. Duas entregas independentes, cada uma com plano próprio.

## 1. Monitor, log e auditoria do projeto inteiro

- A interface mostra o que o NICKEL faz **a partir de eventos emitidos pelo código em execução**, nunca de texto fabricado pela UI.
- O log cobre o projeto inteiro: agente, roteamento de workspace, montagem do prompt, chamadas ao modelo, ferramentas, confirmações, voz, WhatsApp, saídas (outbound), OAuth, partida/parada.
- É o **sistema de auditoria**: persistente (SQLite), agrupado por execução (`run_id`), com duração por etapa e exportável.
- Gera **documentação de processos** a partir do código: catálogo de eventos, fluxo de um turno e relatório por execução, com teste que impede a documentação de divergir do código.
- **Raciocínio do modelo em tempo real**: o que o modelo realmente emite (raciocínio expandido, quando o `think` está ligado) mais fases técnicas reais (rota, prompt, modelo, ferramenta). Mostra um resumo curto (calculado sem outro LLM) e o trecho final do texto, e a aparência da tela muda conforme a fase.
- Com `think` desligado não há texto de raciocínio. A tela diz isso e mostra só as fases.

## 2. Voz do agente via VoiceStudio

- O NICKEL fala pelo VoiceStudio instalado no PC (`POST /v1/audio/speech`, API compatível com OpenAI, porta padrão 3900).
- Voz provisória genérica (`default`), trocável depois por um perfil de voz pelo nome.
- A GUI ganha "Falar respostas" e um botão de ouvir por mensagem. Eventos de fala aparecem no monitor.
- No Windows o áudio toca com `winsound` (stdlib). A resposta em texto nunca depende da voz.

## Restrições do projeto

- Python 3.11+, sem dependências novas de runtime; frontend em JS puro, sem build e sem CDN.
- Textos da interface em PT-BR, no imperativo.
- Migração do SQLite apenas aditiva; os 102 testes existentes continuam passando.
- Nenhum segredo, áudio em base64 ou token vai para os eventos (reaproveita `_redact`).

## Fora do escopo

- Trocar o STT (faster-whisper) pelo do VoiceStudio.
- Treinar ou clonar voz.
- Monitor remoto, autenticação do monitor e exportar eventos para Obsidian.
