# ADR-0003: Workspaces sobre um modelo único e inferência local com Qwen3.6-35B-A3B

**Status:** Aceito
**Data:** 2026-11-18
**Decisores:** Victor Daniel

## Contexto

O [ADR-0002](0002-implantacao-oracle-runpod.md) colocou a inferência no RunPod Serverless e o núcleo numa VM Oracle. Victor quer também uma opção totalmente local, no PC Windows (RX 6600 de 8 GB de VRAM, 24 GB de RAM), que reproduza o fluxo dos Projetos do Claude: contextos de trabalho separados (RPG, código, prospecção etc.), cada um com instruções, ferramentas e pasta próprias.

Restrições do hardware:
- Não cabem dois modelos úteis ao mesmo tempo em 8 GB de VRAM.
- ROCm não suporta a RX 6600 no Windows. O caminho é Vulkan (llama.cpp).
- Um modelo denso de 27B a 4 bits (~16,5 GB) precisaria ler ~10 GB da RAM por token e geraria poucos tokens por segundo. Um MoE com ~3B parâmetros ativos lê ~2 GB por token.

## Decisão

1. **"Agente de projeto" é um perfil, não um modelo.** Um `Workspace` agrupa instruções, ferramentas permitidas, pasta de notas, parâmetros de geração, histórico próprio e backend. Todos os workspaces usam o mesmo modelo carregado.
2. **Modelo local:** `Qwen3.6-35B-A3B` (MoE, ~3B ativos), quantização `IQ4_XS` (~17,7 GB), servido por `llama-server` (llama.cpp, backend Vulkan) com `--n-cpu-moe`. O NICKEL fala com ele pelo provider `llamacpp` (API `/v1/chat/completions`).
3. **Roteamento:** comando explícito (`/rpg texto`, `/ws`), workspace ativo persistente e, opcionalmente, palavras-chave. Roteamento por embeddings fica para depois.
4. **Backend por workspace:** `local` (padrão) ou `cloud` (RunPod, ADR-0002). Workspaces que exigem mais raciocínio podem apontar para o 27B na nuvem.
5. **Arquivos de workspace em Markdown** com frontmatter, editáveis no Obsidian.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Perfis sobre um modelo (escolhida)** | Sem troca de pesos, respostas rápidas, instruções editáveis, funciona com qualquer backend | Sem especialização por modelo |
| B. Um modelo por workspace (llama-swap) | Pode usar um coder ou um modelo de RPG | Segundos de carga a cada troca, RAM disputada |
| C. Orquestrador + SLMs como agentes | Barato por chamada | SLM não sustenta contexto longo de projeto |
| D. Dois modelos simultâneos | Em teoria, paralelismo | Não cabe em 8 GB de VRAM |
| E. Modelo denso 27B local | Melhor qualidade por token | 2 a 5 tokens/s estimados: inviável em fluxos com várias chamadas |

## Trade-offs

- **Qualidade:** o 35B-A3B fica abaixo do 27B denso em raciocínio longo. O backend `cloud` por workspace cobre esse caso.
- **RAM:** o IQ4_XS deixa ~6 GB de folga em 24 GB, com Windows e navegador abertos. O Q4_K_M (~20,7 GB) tende a forçar o uso de disco.
- **Velocidade:** as estimativas (10 a 20 tokens/s) vêm de cálculo de largura de banda e de relatos em hardware NVIDIA/CUDA. Não há medição na RX 6600 com Vulkan.
- **Raciocínio:** com `thinking` ligado, a geração cresce em milhares de tokens. Por padrão fica desligado e é ligado por workspace.
- **PC ligado:** a opção local só funciona com o PC ligado e o `llama-server` de pé.
- **Roteamento por palavras-chave** erra mais que embeddings. Por isso vem desligado por padrão e a troca explícita é o caminho principal.
- **Histórico:** cada workspace tem a própria conversa. A memória de preferências (`memory_*`) continua global.

## Consequências

**Fica mais fácil:**
- Replicar um Projeto novo: criar um arquivo `.md` em `workspaces/`.
- Trocar de modelo ou de backend só no `.env` e no frontmatter.
- Restringir ferramentas por contexto (por exemplo, o workspace de RPG sem e-mail).

**Fica mais difícil:**
- Validar a velocidade real e o uso de RAM no PC.
- Manter instruções de vários workspaces coerentes com a persona base.

**A revisar:**
- Tokens/s e uso de RAM do IQ4_XS na RX 6600 com Vulkan (rodar `scripts/windows/bench-llama.ps1`).
- Qualidade das chamadas de ferramenta e de PT-BR do 35B-A3B quantizado.
- Se o roteamento por embeddings compensa o segundo modelo (embeddings pequenos, em CPU).

## Fora do escopo desta entrega

A adaptação completa do NICKEL ao Windows continua pendente: atalho global de voz, notificações do sistema, serviços de fundo e script de instalação. Esta entrega cobre o modelo local, os workspaces e os scripts do `llama-server`.

## Itens de ação

1. [x] Provider `llamacpp` e opções de geração por chamada.
2. [x] Workspaces: perfis em Markdown, roteador, histórico e ferramentas por workspace, pasta de notas por workspace.
3. [x] Scripts de download, inicialização e benchmark no Windows.
4. [ ] Medir velocidade e RAM no PC e ajustar `--n-cpu-moe` e contexto.
5. [ ] Colar nos arquivos de `workspaces/` as instruções reais dos Projetos.
6. [ ] Roteamento por embeddings.
7. [ ] Adaptar voz, notificações e serviços ao Windows.
