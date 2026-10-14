# ADR-0001: Arquitetura do NICKEL v2 — assistente local com Qwen, voz e WhatsApp

**Status:** Aceito
**Data:** 2026-10-14
**Decisores:** Victor Daniel

## Contexto

O NICKEL v1 era uma API FastAPI + CLI com Gmail, Google Agenda, Spotify (play/pause/skip), memória opt-in, auditoria e fluxo de confirmação, falando com um LLM em nuvem (Groq).

O objetivo da v2 é um assistente particular que:

- roda localmente com Qwen;
- conversa por voz (push-to-talk no PC) e pelo WhatsApp (texto, áudio e foto);
- tem skills: Spotify, reconhecimento de música (com fallback para YouTube), lembretes com aviso no celular, captura de pensamentos no Obsidian, Gmail e Agenda;
- oferece uma UI local para histórico e confirmações.

Restrições levantadas:

| Item | Valor |
|---|---|
| Máquina do NICKEL | Linux, GPU NVIDIA com 24 GB de VRAM |
| Ligada 24 h? | Não. Lembretes precisam funcionar com o PC desligado |
| WhatsApp | Número pessoal do Victor; o chat "você mesmo" é a interface |
| Vault Obsidian | `Editora`, num PC Windows; chega ao Linux via Syncthing |
| Spotify | Conta Premium (exigida pelo Development Mode desde fev/2026) |
| Ativação de voz | Só por atalho de teclado |

### Diagnóstico do v1 (commit `a7c4f06`)

- `main` não executa: `SyntaxError` em `app/chat.py:217` e nomes não importados (`ensure_google_ready`, `check_spotify_connection`, `get_token_store`). Corrigida só a sintaxe, 14 de 81 testes falham.
- Cada tool é declarada em ~6 lugares (handlers, conjunto de confirmação, schema do LLM, prompt textual, if-chain de execução, rotas).
- Um orquestrador por substring bloqueia ações que o LLM escolhe quando nenhuma palavra-chave bate.
- Uma ação por turno; o resultado da tool não volta ao modelo.
- Só request/response síncrono; não há como receber eventos (WhatsApp) nem disparar lembretes.
- Persistência em JSON reescrito inteiro, sem lock.

## Decisão

Reescrever o núcleo na branch `v2` e portar as integrações que funcionavam.

1. **Núcleo novo (`nickel/core`)**
   - Registro de skills: cada tool é declarada uma vez (nome, descrição, JSON Schema, flag de confirmação, handler).
   - Loop de agente com tool calling nativo do Ollama: o resultado de cada tool volta ao modelo, até 6 passos por turno.
   - SQLite único (`data/nickel.db`) para conversa, confirmações pendentes, lembretes, memória, tokens criptografados e auditoria.
   - Uma única conversa compartilhada entre WhatsApp, voz e UI: o que foi dito num canal vale no outro, e uma confirmação pendente pode ser respondida em qualquer um.
2. **LLM:** `qwen3.6:27b` via Ollama (`/api/chat`, `think: false`, `num_ctx` 16k). Aceita texto e imagem e suporta tools.
3. **Voz:** pipeline STT → LLM → TTS.
   - STT: `faster-whisper` `large-v3-turbo` na GPU (`int8_float16`).
   - TTS: Piper `pt_BR-faber-medium` na CPU.
   - Captura por atalho global do GNOME/KDE que chama `nickel listen` (alterna gravar/parar).
4. **WhatsApp:** bridge Node com open-wa **v5** (`@open-wa/core` + `@open-wa/client` + `@open-wa/driver-puppeteer`, fixados em 5.6.0).
   - A bridge filtra só o chat "você mesmo" e encaminha à API por HTTP com token.
   - Áudios são transcritos; fotos vão ao modelo como imagem.
   - Respostas saem com um marcador invisível e têm o ID registrado, para a bridge não processar as próprias mensagens.
5. **Lembretes:**
   - Ficam no SQLite e viram evento no Google Agenda com notificação no horário; o celular avisa mesmo com o PC desligado.
   - Com o PC ligado, o agendador local também manda mensagem no WhatsApp.
   - Suporte a repetição diária, semanal ou mensal (RRULE).
6. **Obsidian:**
   - Escreve `.md` direto em `06 Pensamentos/` no vault sincronizado.
   - Frontmatter segue as convenções do vault (`type`, `tags`, `created`, `updated`).
   - A transcrição original fica num callout recolhido.
   - O NICKEL só cria arquivos, nunca edita, para não gerar conflito no Syncthing.
   - O índice da pasta é uma consulta Dataview, então não precisa ser reescrito.
7. **Música:**
   - Todo áudio recebido passa pelo ShazamIO (só a assinatura acústica sai da máquina).
   - Se houver match, busca no Spotify; se não achar, busca no YouTube via `yt-dlp`.
   - No PC, a tool `music_recognize` grava o microfone por alguns segundos.
8. **UI local:** página servida pela própria API em `127.0.0.1`, com conversa, confirmações pendentes, lembretes, conexões e auditoria. Atualiza por polling.

## Opções consideradas

### 1. Base do código

| Dimensão | A: Consertar o v1 | B: Núcleo novo + integrações portadas | C: Do zero |
|---|---|---|---|
| Complexidade | Alta (refatorar quase todo `chat/llm/orchestrator/main`) | Média | Média-alta |
| Reaproveitamento | Total, inclusive dívidas | OAuth, clientes Google/Spotify, políticas, persona | Nenhum |
| Encaixe com eventos e loop de agente | Ruim | Bom | Bom |

**Escolha: B.** A reaproveitaria mais linhas, mas exigiria reescrever exatamente as partes que bloqueiam a v2. C perderia integrações e políticas que já funcionam.

### 2. Voz

| Dimensão | A: Pipeline STT → Qwen → TTS | B: Qwen3-Omni nativo |
|---|---|---|
| Suporte local | Maduro (faster-whisper, Piper, Ollama) | Entrada de áudio no llama.cpp; saída de voz exige runtimes específicos |
| VRAM | ~19 GB (LLM) + ~1 GB (STT) | 30B-A3B inteiro, mais o Talker |
| Troca de peças | Independente | Acoplada |

**Escolha: A.**

### 3. Cliente WhatsApp

| Dimensão | A: open-wa v5 | B: open-wa v4 | C: Baileys / Evolution API |
|---|---|---|---|
| Manutenção | Ativa (5.6.0 em 14/10/2026) | Última versão em fev/2025 | Ativa |
| Pedido do usuário | Sim | Sim | Não |
| Risco | API recém-lançada | Quebra com mudanças do WhatsApp Web | Outra stack |

**Escolha: A**, com a bridge isolada atrás de três endpoints HTTP (`/send`, `/send-voice`, `/health`). Trocar de biblioteca depois afeta só `whatsapp-bridge/`.

### 4. Aviso de lembretes

| Dimensão | A: Google Agenda + WhatsApp | B: ntfy | C: Só WhatsApp |
|---|---|---|---|
| Funciona com o PC desligado | Sim (o Google notifica) | Só com servidor externo | Não |
| Infra nova | Nenhuma (Agenda já integrada) | App + servidor | Nenhuma |

**Escolha: A.** ntfy foi descartado.

### 5. Escrita no Obsidian

| Dimensão | A: Arquivo direto + Syncthing | B: Plugin Local REST API |
|---|---|---|
| Dependência | Nenhuma no Obsidian | O Obsidian precisa estar aberto no Windows |
| Funciona com o Windows desligado | Sim (sincroniza depois) | Não |

**Escolha: A.**

## Análise de trade-offs

- **Número pessoal no WhatsApp:** é a opção mais simples para o usuário (nada de chip extra), mas o risco de bloqueio por cliente não oficial recai sobre o número principal. Mitigações: a bridge só lê o chat "você mesmo", não envia para terceiros e não faz envios em massa.
- **Confirmação:** a política do v1 pedia confirmação para qualquer escrita. Na v2, ela continua obrigatória para o que sai do controle do usuário (enviar e-mail, criar ou alterar eventos genéricos na Agenda, salvar memória de longo prazo). Ficam sem confirmação as escritas pessoais e reversíveis feitas por pedido explícito: nota no inbox do Obsidian, lembrete e rascunho de e-mail. A resposta sempre diz o que mudou. Sem isso, capturar um pensamento custaria duas mensagens.
- **VRAM:** `qwen3.6:27b` ocupa ~19 GB. Com STT na GPU sobra pouco dos 24 GB. Se faltar memória, reduza `LLM_NUM_CTX` ou mova o STT para a CPU (`STT_DEVICE=cpu`).

## Consequências

**Fica mais fácil:**
- Adicionar skills: um arquivo, uma função `register()`.
- Pedidos encadeados ("que música é essa? toca no Spotify").
- Usar o assistente fora de casa pelo WhatsApp.

**Fica mais difícil:**
- Manter a bridge do WhatsApp: ela depende de uma API recém-lançada e de um cliente não oficial.
- O setup inicial: Ollama, modelo, voz do Piper, Node, Syncthing e OAuth.

**A revisar:**
- Estabilidade do open-wa v5 nas primeiras semanas.
- Latência real do 27B na voz; se passar de ~3 s, testar `qwen3.5:9b` para a voz.
- Se o ShazamIO quebrar (API não oficial), avaliar um provedor pago como fallback.

## Itens de ação

1. [x] Núcleo: config, SQLite, cliente Ollama, registro de skills, agente, confirmações, auditoria.
2. [x] Skills: Spotify, música, Obsidian, lembretes, Gmail, Agenda, memória.
3. [x] Canais: bridge WhatsApp, voz push-to-talk, UI local.
4. [x] Vault: pasta `06 Pensamentos`, índice com Dataview, modelo e link na `Home`.
5. [ ] Instalar na máquina Linux (`scripts/install.sh`) e parear o WhatsApp.
6. [ ] Configurar o Syncthing entre o Windows e o Linux.
7. [ ] Conectar Google e Spotify pela UI.
