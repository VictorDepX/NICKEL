# NICKEL v2

Assistente pessoal com Qwen. Conversa pelo WhatsApp (texto, áudio e foto) e por voz no PC (push-to-talk), e tem uma UI local para histórico e confirmações.

- **Skills:** Spotify, reconhecimento de música (Spotify ou YouTube), pensamentos no Obsidian, lembretes que avisam no celular, Gmail, Google Agenda e memória opt-in.
- **Decisões de arquitetura e trade-offs:** [`docs/adr/0001-arquitetura-v2.md`](docs/adr/0001-arquitetura-v2.md) e [`docs/adr/0002-implantacao-oracle-runpod.md`](docs/adr/0002-implantacao-oracle-runpod.md).

```
WhatsApp ─┐                                   ┌─ Spotify / ShazamIO / YouTube
Voz (PC) ─┼─► Agente (Qwen + tools) ─► Skills ─┼─ Obsidian (vault via Syncthing)
UI local ─┘        │                           └─ Gmail / Google Agenda
                   └─ SQLite: conversa, confirmações, lembretes, memória, tokens, auditoria
```

## Modos de implantação

| Modo | Onde roda o NICKEL | Onde roda o modelo | Guia |
|---|---|---|---|
| **Servidor** (em uso) | VM ARM grátis da Oracle, 24 h | RunPod Serverless (vLLM), pago por segundo | [`docs/deploy/oracle-runpod.md`](docs/deploy/oracle-runpod.md) |
| **Local** | Linux com GPU NVIDIA de 24 GB | Ollama na mesma máquina | Seção abaixo |

O modo é definido por `LLM_PROVIDER` no `.env`: `openai` para o RunPod ou outro provedor compatível, `ollama` para GPU local.

No modo servidor, a voz por atalho não existe (a VM não tem microfone), mas áudios pelo WhatsApp funcionam normalmente.

## Requisitos (modo local)

- Linux com GPU NVIDIA de 24 GB (o `qwen3.6:27b` ocupa ~19 GB).
- Python 3.11+, Node.js 20+, ffmpeg.
- Spotify Premium: o Development Mode da API exige isso desde fev/2026.
- Syncthing sincronizando o vault `Editora` entre o Windows e esta máquina.

## Instalação (modo local)

```bash
git checkout v2
./scripts/install.sh          # pacotes, Ollama + modelo, .venv, voz do Piper, bridge, .env com chaves
$EDITOR .env                  # OBSIDIAN_VAULT_PATH, Google, Spotify
./scripts/install-services.sh # serviços systemd de usuário + comando nickel-listen
```

Depois:

1. **Pareie o WhatsApp.** Rode `journalctl --user -fu nickel-whatsapp` e escaneie o QR em *WhatsApp → Aparelhos conectados → Conectar um aparelho*. A sessão fica em `data/wa-session/`.
2. **Converse.** No celular, abra a conversa *"Você"* (mensagem para você mesmo). O NICKEL lê só esse chat e responde nele.
3. **Conecte Google e Spotify.** Abra `http://127.0.0.1:8000` e use *Conexões → Conectar*.
4. **Configure o atalho de voz.**
   - GNOME: *Configurações → Teclado → Atalhos personalizados*, comando `~/.local/bin/nickel-listen`.
   - KDE: *Atalhos personalizados*, mesmo comando.
   - Uso: aperte uma vez para falar. Ele para sozinho após 1,5 s de silêncio, ou quando você aperta de novo. Enquanto ele fala, apertar interrompe.
5. **Confira.** `nickel doctor` lista o que falta.

### Google (Gmail + Agenda)

1. No Google Cloud Console, crie um projeto e ative a Gmail API e a Google Calendar API.
2. Crie um *OAuth client ID* do tipo **Web application**, com o redirect `http://localhost:8000/auth/google/callback`.
3. Coloque o ID e o segredo no `.env`.
4. Na tela de consentimento, adicione seu e-mail como usuário de teste.

### Spotify

1. Crie um app em developer.spotify.com.
2. Cadastre o redirect **`http://127.0.0.1:8000/auth/spotify/callback`**. O Spotify não aceita `localhost`.
3. Coloque o ID e o segredo no `.env`.
4. O app fica em Development Mode, ligado à sua conta Premium.

### Obsidian

As notas vão para `06 Pensamentos/` no vault.

- Cada nota tem frontmatter (`type: pensamento`, `categoria`, `fonte`, `status: inbox`) e guarda o texto original num callout recolhido.
- O NICKEL só **cria** arquivos, nunca edita os existentes, para não gerar conflito no Syncthing.
- O índice `06 Pensamentos/Pensamentos.md` usa Dataview e já está ligado à `Home`.

## Uso

| Você diz/escreve | O que acontece |
|---|---|
| "me lembra de pagar a luz amanhã às 9" | Lembrete local + evento no Google Agenda. O celular avisa mesmo com o PC desligado; com o PC ligado, chega também no WhatsApp |
| *áudio de uma música tocando* | ShazamIO identifica e devolve o link do Spotify (ou do YouTube) |
| "que música é essa?" (pela voz, no PC) | Grava 10 s do microfone e identifica |
| "toca Clube da Esquina" | Busca e toca no dispositivo Spotify ativo |
| "anota: …" ou um pensamento solto | Nota organizada no Obsidian |
| *foto* + "o que é isso?" | O Qwen analisa a imagem |
| "manda um e-mail pra Ana dizendo…" | Pede confirmação (*sim/não*) antes de enviar |

Confirmações podem ser respondidas no WhatsApp, pela voz ou na UI. Política completa: [`docs/Nickel/policy_confirmation.md`](docs/Nickel/policy_confirmation.md).

Comandos: `nickel serve` · `nickel listen` (só modo local) · `nickel chat` (texto no terminal) · `nickel doctor` · `nickel keys`.

## Estrutura

```
nickel/
  core/          agente, clientes LLM (Ollama e OpenAI/RunPod), registro de skills, SQLite, persona
  skills/        uma tool por função; cada módulo expõe register(registry)
  integrations/  Google, Spotify, música, Obsidian
  channels/      WhatsApp e voz
  speech/        faster-whisper, Piper, microfone
  ui/static/     UI local
whatsapp-bridge/ open-wa v5 → HTTP local
docs/Nickel/     persona e políticas (canônicas)
docs/adr/        decisões de arquitetura
docs/deploy/     guias de implantação
scripts/         install.sh (local), install-server.sh (VM), install-services.sh
```

**Nova skill:** crie `nickel/skills/<nome>.py` com `register(registry)`, inclua em `SKILL_MODULES` e atualize `docs/Nickel/tool_contracts.md`.

## Desenvolvimento

```bash
.venv/bin/pytest                 # Python
(cd whatsapp-bridge && npm test) # filtros da bridge
```

Os testes usam dublês para o LLM, o WhatsApp, o Spotify e o reconhecimento; não precisam de GPU nem de rede.

## Problemas comuns

- **Primeira resposta demora (modo servidor).** É a partida a frio do worker no RunPod. O WhatsApp avisa depois de `WA_SLOW_NOTICE_SECONDS`. Para respostas mais rápidas, aumente o *Idle timeout* do endpoint (custa mais).
- **Falta VRAM (CUDA OOM).** Reduza `LLM_NUM_CTX` ou mova o STT para a CPU com `STT_DEVICE=cpu` e `STT_COMPUTE_TYPE=int8`.
- **Resposta lenta na voz.** Teste `LLM_MODEL=qwen3.5:9b`.
- **WhatsApp desconectou.** Rode `systemctl --user restart nickel-whatsapp` e, se pedir, escaneie o QR de novo. O open-wa é um cliente não oficial: use com moderação.
- **Notificação ou áudio não saem pelo serviço.** Rode `systemctl --user import-environment DISPLAY WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS` e reinicie o `nickel`.
- **Spotify retorna "Nenhum dispositivo".** Abra o Spotify em algum aparelho, ou defina `SPOTIFY_DEVICE_NAME`.

## Licença

MIT.
