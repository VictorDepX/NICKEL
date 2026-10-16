# Implantação: Oracle Always Free + RunPod Serverless

O NICKEL roda 24 h numa VM ARM grátis da Oracle. O modelo (Qwen3.6-27B) roda no RunPod Serverless e só é cobrado enquanto processa. Decisão e trade-offs: [ADR-0002](../adr/0002-implantacao-oracle-runpod.md).

```
WhatsApp ─► VM Oracle (bridge, NICKEL, STT, lembretes, UI, Syncthing) ─► RunPod Serverless (vLLM + Qwen)
                    │                                                        ▲
                    └── Syncthing ◄──► PC Windows (vault Editora)            └─ network volume com os pesos
```

## Custos esperados

| Item | Custo |
|---|---|
| VM Oracle (2 OCPU ARM, 8 GB) | US$ 0 (Always Free) |
| RunPod, GPU de 48 GB (A6000/A40, US$ 1,22/h) | ~US$ 27/mês com ~45 min de GPU por dia |
| RunPod, GPU de 24 GB (US$ 0,69/h) | ~US$ 16/mês, mas a memória fica no limite (veja o passo 1) |
| Network volume de 30 GB (US$ 0,07/GB) | ~US$ 2/mês |

O RunPod cobra por segundo: a carga do modelo, a execução e o tempo ocioso configurado. Se a GPU ficar parada, o custo é zero.

## 1. Endpoint no RunPod

1. Crie uma conta em runpod.io, adicione crédito e gere uma **API key** em *Settings → API Keys*.
2. Em *Storage*, crie um **network volume** de 30 GB num datacenter com GPUs de 48 GB disponíveis. Os pesos do modelo ficam salvos nele, para não serem baixados a cada partida.
3. Em *Serverless → New Endpoint*, use o template **vLLM** na versão mais recente (v2.27.0 ou superior, que traz o vLLM 0.29; o Qwen3.6 exige vLLM 0.19 ou superior). Configure as variáveis:
   ```
   MODEL_NAME=cyankiwi/Qwen3.6-27B-AWQ-INT4
   MAX_MODEL_LEN=32768
   GPU_MEMORY_UTILIZATION=0.92
   ENABLE_AUTO_TOOL_CHOICE=true
   TOOL_CALL_PARSER=qwen3_coder
   OPENAI_SERVED_MODEL_NAME_OVERRIDE=qwen3.6-27b
   ```
   Deixe `QUANTIZATION` vazio: o vLLM detecta o formato pelo `config.json` do modelo.
4. Ajuste o endpoint:

   | Campo | Valor |
   |---|---|
   | GPU | 48 GB (A6000 ou A40) como primeira opção |
   | Active workers | 0 |
   | Max workers | 1 |
   | Idle timeout | 60 s (mantém o worker quente durante uma conversa; esse tempo também é cobrado) |
   | FlashBoot | Ligado |
   | Network volume | O volume do passo 2 |

5. Anote o **Endpoint ID** e teste. A primeira chamada pode demorar alguns minutos, porque baixa ~20 GB para o volume:
   ```bash
   curl https://api.runpod.ai/v2/ENDPOINT_ID/openai/v1/chat/completions \
     -H "Authorization: Bearer SUA_API_KEY" -H "Content-Type: application/json" \
     -d '{"model":"qwen3.6-27b","messages":[{"role":"user","content":"Responda só: ok"}],"chat_template_kwargs":{"enable_thinking":false}}'
   ```

**GPU de 24 GB:** os pesos em INT4 ocupam ~20,4 GB, o que deixa pouco espaço para o contexto. Para testar, use `MAX_MODEL_LEN=16384`. Se o worker cair por falta de memória (OOM), volte para 48 GB.

**Imagens:** confira se o modelo aceita fotos enviando uma pelo WhatsApp depois da instalação. O model card mostra exemplos com imagem, mas não garante que a quantização mantém o encoder de visão.

## 2. VM na Oracle

1. Crie a conta em oracle.com/cloud/free. A **home region** é definitiva: escolha **Brazil East (São Paulo)**. O cadastro pede cartão só para verificação.
2. Em *Compute → Instances → Create instance*, configure:
   - **Image:** Canonical Ubuntu 24.04 (a versão aarch64 aparece ao escolher o shape ARM).
   - **Shape:** `VM.Standard.A1.Flex`, com **2 OCPUs e 8 GB de RAM**.
   - **SSH:** cole sua chave pública (ou baixe a que a Oracle gerar).
   - **Disco:** o boot volume padrão (~50 GB) basta.
3. Se aparecer *Out of host capacity*, tente outro *availability domain* ou repita mais tarde. A falta de capacidade ARM é comum e temporária.

**Por que 8 GB e não 12 GB:** a Oracle pode recuperar instâncias Always Free ociosas. Uma instância conta como ociosa quando, por 7 dias, CPU (p95), rede e memória ficam **todas** abaixo de 20%. O NICKEL usa pouca CPU e rede, então a memória é o que mantém a VM ativa. Com 8 GB, o uso normal (Python, Whisper e Chrome) fica acima de 20%. O `nickel doctor` mostra esse percentual na VM.

## 3. Instalar o NICKEL na VM

```bash
ssh ubuntu@IP_DA_VM
git clone -b v2 https://github.com/VictorDepX/NICKEL.git nickel
cd nickel
./scripts/install-server.sh
```

O script instala:
- **Sistema:** Python, Node 22, ffmpeg e Syncthing.
- **Chromium ARM**, pelo Playwright, para a bridge.
- **Dependências** do STT, da música e do TTS.
- **`.env` de servidor** com chaves geradas e STT `small` em CPU.

Depois, edite o `.env`:

```bash
nano .env
```

| Variável | Valor |
|---|---|
| `LLM_BASE_URL` | `https://api.runpod.ai/v2/ENDPOINT_ID/openai/v1` |
| `LLM_API_KEY` | API key do RunPod |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Do Google Cloud (README) |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Do painel do Spotify (README) |

Suba os serviços e pareie o WhatsApp:

```bash
./scripts/install-services.sh
journalctl --user -fu nickel-whatsapp
```

No celular, abra *WhatsApp → Aparelhos conectados → Conectar um aparelho* e escaneie o QR que aparece no log.

## 4. Túnel SSH (UI, OAuth e Syncthing)

A UI e o Syncthing escutam só em `127.0.0.1` na VM. Acesse pelo túnel, a partir do seu PC:

```bash
ssh -L 8000:127.0.0.1:8000 -L 8384:127.0.0.1:8384 ubuntu@IP_DA_VM
```

- **UI:** abra `http://localhost:8000` e, em *Conexões*, conecte Google e Spotify. Os redirects do README (`localhost:8000` e `127.0.0.1:8000`) funcionam sem mudança, porque o túnel usa a mesma porta.
- **Syncthing da VM:** `http://localhost:8384`.

## 5. Sincronizar o vault

1. No Windows, instale o Syncthing (instalador oficial) e abra a interface dele (`http://127.0.0.1:8384` no Windows).
2. Troque os *Device IDs* entre o Windows e a VM: *Actions → Show ID* num lado, *Add Remote Device* no outro.
3. No Windows, compartilhe a pasta `C:\Users\Pichau\Documents\Editora` com a VM. Na VM, aceite com o caminho `/home/ubuntu/Editora`.
4. Opcional: crie `.stignore` na raiz do vault com a linha `.obsidian/workspace*.json`, para não sincronizar o layout das janelas.

O NICKEL só cria notas novas em `06 Pensamentos`, nunca edita as existentes. Isso evita conflitos de sincronização.

## 6. Celular (opcional)

Para ver a UI no celular sem expor nada na internet, use o Tailscale (gratuito):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 8000
```

Instale o app do Tailscale no celular, com a mesma conta. A UI fica em `https://NOME-DA-VM.SEU-TAILNET.ts.net`, acessível só pelos seus aparelhos. Faça o OAuth pelo túnel SSH: o Google e o Spotify redirecionam para `localhost`.

## 7. Conferir

```bash
.venv/bin/nickel doctor
```

Depois, mande "oi" no chat *Você* do WhatsApp:
- Se o worker estiver frio, chega primeiro "Um momento. O modelo pode estar iniciando." e, em seguida, a resposta.
- Com o worker quente, a resposta chega direto.

## Manutenção

**Atualizar:**
```bash
git pull
.venv/bin/pip install -e '.[server,dev]'
systemctl --user restart nickel nickel-whatsapp
```

**Logs:** `journalctl --user -u nickel -n 100` e `journalctl --user -u nickel-whatsapp -n 100`.

**Backup:** copie `data/nickel.db` (conversa, lembretes, memória, tokens) e `data/wa-session/` (sessão do WhatsApp).

**Custo do RunPod:** acompanhe em *Billing*. Se subir demais, reduza o *Idle timeout* do endpoint.

## Riscos conhecidos

- **Recuperação da VM pela Oracle:** se acontecer, os dados da VM se perdem. Mantenha o backup em dia. Passar a conta para *Pay As You Go* dá mais margem: a Oracle continua sem cobrar o que fica dentro do Always Free. Configure um alerta de orçamento.
- **Privacidade:** o conteúdo de cada chamada ao modelo passa pelo RunPod (mensagens, e-mails lidos, fotos). As GPUs da *Secure Cloud* rodam em datacenters auditados.
- **WhatsApp:** o open-wa é um cliente não oficial e agora roda a partir de um IP de datacenter. O risco de bloqueio do número continua existindo.
- **Partida a frio:** a primeira resposta depois de um tempo parado depende de o worker subir e carregar ~20 GB do volume.
