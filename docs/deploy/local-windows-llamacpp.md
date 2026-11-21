# Modelo local no Windows (llama.cpp + Qwen3.6-35B-A3B)

Guia do [ADR-0003](../adr/0003-workspaces-e-modelo-local.md). Roda o modelo no seu PC (RX 6600 de 8 GB, 24 GB de RAM) e o NICKEL fala com ele por `LLM_PROVIDER=llamacpp`.

> **Estado:** os scripts foram escritos sem acesso ao seu PC e não foram executados lá. O primeiro passo real é o teste do passo 4. As velocidades citadas são estimativas.

## O que roda

- `llama-server` (llama.cpp, backend **Vulkan**): carrega `Qwen3.6-35B-A3B` em `IQ4_XS` (~17,7 GB). Os pesos dos experts MoE ficam na RAM e a GPU guarda atenção e camadas fixas.
- NICKEL (Python): `nickel serve` ou `nickel chat`, apontando para `http://127.0.0.1:8080/v1`.

## 1. Baixar o llama.cpp

```powershell
.\scripts\windows\get-llama.ps1
```

Baixa o build `bin-win-vulkan-x64` da última release para `%LOCALAPPDATA%\llama.cpp`. Se o nome do arquivo mudar, o script lista os assets do Windows e você baixa à mão.

## 2. Baixar o modelo

```powershell
.\scripts\windows\get-model.ps1 -WithVision
```

Grava em `%USERPROFILE%\models` o `Qwen_Qwen3.6-35B-A3B-IQ4_XS.gguf` e, com `-WithVision`, o `mmproj-…-f16.gguf` (necessário para fotos no WhatsApp; ocupa memória extra). O download retoma se cair. Outras quantizações: `-Quant Q4_K_M` (~20,7 GB, no limite dos 24 GB) ou `-Quant IQ3_M` se a RAM faltar.

## 3. Subir o servidor

```powershell
.\scripts\windows\start-llama.ps1            # texto
.\scripts\windows\start-llama.ps1 -Vision    # com fotos
```

Padrão medido numa RX 6600 8 GB com 20 GB de RAM: `--n-cpu-moe 30` e `--load-mode none` (experts das 30 primeiras camadas residentes na RAM, o resto na GPU; ~21 tok/s de geração, ~190 tok/s de prefill, VRAM ~7,3 GB), contexto de 16k, um slot (`-np 1`) e `--jinja` (necessário para chamada de ferramentas). Espere a mensagem de que o servidor está escutando.

## 4. Medir

Em outra janela, com o servidor de pé:

```powershell
.\scripts\windows\bench-llama.ps1
```

Mostra tokens/s de prefill e de geração (prompt curto e longo) e a RAM livre antes e depois. Referências para decidir:

| Resultado | Ação |
|---|---|
| Geração abaixo de ~5 tokens/s | Confira se a GPU é usada (log do servidor deve citar Vulkan e a RX 6600); não use `-Mmap` (com mmap o Windows pagina os experts do disco e o prefill cai para ~4 tok/s); reduza `-Ctx` |
| RAM livre abaixo de ~2 GB | Feche o navegador, use `-Quant IQ3_M` ou `-Ctx 8192` |
| VRAM sobrando | Reduza `-NCpuMoe` (ex.: `-NCpuMoe 30`) para trazer camadas de experts para a GPU e acelerar; repita o benchmark |
| Falha de memória na GPU | Aumente `-NCpuMoe` (ex.: 32) ou use `-NCpuMoe -1` (`--cpu-moe`) |

## 5. Configurar o NICKEL

No `.env`:

```ini
LLM_PROVIDER=llamacpp
LLM_BASE_URL=http://127.0.0.1:8080/v1
LLM_MODEL=qwen3.6-35b-a3b
LLM_THINK=false
LLM_TIMEOUT_SECONDS=300
LLM_MAX_TOKENS=1500
OBSIDIAN_VAULT_PATH=C:\Users\Pichau\Documents\Editora
WORKSPACES_DIR=C:\Users\Pichau\Documents\Editora\NICKEL\Workspaces
```

Copie os arquivos de `workspaces\` para `WORKSPACES_DIR` e troque o corpo de cada um pelas instruções reais dos seus Projetos. Depois:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
nickel doctor
nickel chat
```

No chat: `/ws` lista os workspaces; `/rpg texto` troca e envia.

## Backend na nuvem para workspaces pesados

Para um workspace pedir mais raciocínio ao 27B do RunPod (ADR-0002), ponha `backend: cloud` no frontmatter e configure:

```ini
LLM_CLOUD_BASE_URL=https://api.runpod.ai/v2/<ENDPOINT_ID>/openai/v1
LLM_CLOUD_API_KEY=<chave do RunPod>
LLM_CLOUD_MODEL=qwen3.6-27b
```

Sem `LLM_CLOUD_BASE_URL`, esses workspaces usam o modelo local.

## O que ainda não está adaptado ao Windows

Atalho global de voz, notificações do sistema, serviços de fundo e `install.sh` (pensados para Linux). A bridge do WhatsApp (Node + Chromium) e as integrações de Spotify, Google e Obsidian não dependem disso. Detalhes em ADR-0003, "Fora do escopo desta entrega".

## Problemas comuns

- **`nickel doctor` mostra "llama-server ainda carregando":** o modelo leva de dezenas de segundos a alguns minutos para carregar na primeira vez.
- **Respostas sem ferramentas:** confirme `--jinja` nos argumentos impressos pelo `start-llama.ps1`.
- **Timeout:** aumente `LLM_TIMEOUT_SECONDS`; com `think: true` a geração cresce em milhares de tokens.
- **Workspace não aparece:** o arquivo precisa terminar em `.md`, não começar com `_` e não se chamar `README.md`.
