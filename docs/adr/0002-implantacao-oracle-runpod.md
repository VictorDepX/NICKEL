# ADR-0002: Implantação em VM Oracle Always Free + RunPod Serverless

**Status:** Aceito
**Data:** 2026-10-16
**Decisores:** Victor Daniel

## Contexto

O [ADR-0001](0001-arquitetura-v2.md) supunha uma máquina Linux própria com GPU de 24 GB. Essa máquina não existe, e não há orçamento para comprar uma. O PC disponível é Windows, com uma RX 6600 (8 GB), e não fica ligado o dia todo.

A bridge do WhatsApp, a entrega de lembretes e o estado (SQLite) precisam de um processo sempre ligado. Só a inferência do modelo exige GPU.

## Decisão

Separar o que exige GPU do resto:

- **Núcleo do NICKEL** (bridge, agente, STT em CPU, lembretes, UI, Syncthing): numa VM ARM `VM.Standard.A1.Flex` da Oracle Always Free, com 2 OCPUs e 8 GB, ligada 24 h.
- **Modelo:** `Qwen3.6-27B` (AWQ INT4) num endpoint vLLM do RunPod Serverless, com 0 workers ativos, 1 no máximo e pesos num network volume.
- **Código:** o cliente LLM ganha o provedor `openai` (`/chat/completions`), escolhido por `LLM_PROVIDER`. O Ollama continua disponível para quem tiver GPU local.

## Opções consideradas

| Dimensão | Mini PC + Serverless | PC Windows + Serverless | Pod RunPod sob demanda | **Oracle Free + Serverless** |
|---|---|---|---|---|
| Custo de hardware | Compra | Zero | Zero | Zero |
| Custo mensal | Inferência + energia | Inferência | Pod por hora + volume | Inferência + volume |
| Disponibilidade | 24 h | Só com o PC ligado | Só sob demanda | 24 h |
| Mensagens com o NICKEL desligado | Não há perda | Perdidas | Perdidas | Não há perda |
| Vault (Syncthing) | Funciona | Local | Exige Git | Funciona |
| Voz por atalho | Sim | Sim (com adaptação) | Não | Não |

## Trade-offs

- **Voz por atalho:** sai do escopo nesta implantação, porque não há microfone na VM. A voz continua pelo WhatsApp: áudios são transcritos e respostas em áudio são opcionais.
- **STT na CPU ARM:** usa o `faster-whisper small` em int8, mais rápido e menos preciso que o `large-v3-turbo` na GPU.
- **Partida a frio:** a primeira resposta depois de um tempo parado demora. O WhatsApp avisa após `WA_SLOW_NOTICE_SECONDS`.
- **Privacidade:** o conteúdo das chamadas ao modelo sai da sua infraestrutura e passa pelo RunPod.
- **GPU de 48 GB:** os pesos INT4 têm ~20,4 GB. Em 24 GB sobra pouco para o contexto, então a recomendação é 48 GB, que custa mais por hora.

## Consequências

**Fica mais fácil:**
- Funcionar 24 h sem hardware próprio.
- Pagar só pela inferência.
- Trocar de modelo ou de provedor mexendo só no `.env`.

**Fica mais difícil:**
- Depender de duas contas externas (Oracle e RunPod).
- Lidar com a política de ociosidade da Oracle: a VM deve manter mais de 20% de memória em uso.
- Lidar com a capacidade ARM às vezes esgotada na criação da VM.

**A revisar:**
- Tempo real da partida a frio.
- Se a quantização INT4 mantém visão e tool calling de forma confiável.
- O custo real no fim do primeiro mês.

## Itens de ação

1. [x] Provedor `openai` no cliente LLM, com retentativas e status do RunPod sem gerar job.
2. [x] Aviso de partida a frio no WhatsApp.
3. [x] `scripts/install-server.sh` para Ubuntu 24.04 ARM e serviços com linger.
4. [x] `nickel doctor` ciente do provedor e da memória da VM Oracle.
5. [x] Guia: [`docs/deploy/oracle-runpod.md`](../deploy/oracle-runpod.md).
6. [ ] Criar o endpoint no RunPod e a VM na Oracle; instalar e parear o WhatsApp.
