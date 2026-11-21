# ADR-0004: Monitor e auditoria com `AuditLog` como barramento de eventos

**Status:** Aceito
**Data:** 2026-11-21
**Decisores:** Victor Daniel

## Contexto

Um turno do NICKEL passa por roteamento, montagem de prompt, chamadas ao modelo, ferramentas e confirmações. Com o modelo local (ver [ADR-0003](0003-workspaces-e-modelo-local.md)) um turno leva dezenas de segundos, e sem visibilidade não dá para saber em que etapa ele está nem por que demorou. Também faltava uma trilha de auditoria consultável e documentação de processos que não envelhecesse.

## Decisão

1. **`AuditLog` é o barramento de eventos.** Cada `record` grava no SQLite e entrega o evento aos assinantes do processo (`call_soon_threadsafe`, filas com descarte do mais antigo). O `run_id` vem de uma `ContextVar`, reaproveitada pela voz e pelo WhatsApp em volta dos turnos do agente.
2. **Catálogo como fonte única.** `nickel/core/events.py` define kinds, estados, campos, fases da interface e o fluxo de um turno. Um teste com AST barra eventos emitidos fora do catálogo. A documentação em `docs/processos/` é gerada por `nickel audit docs`, e um teste de igualdade barra divergência.
3. **Streaming do LLM opt-in** por `on_delta`. O raciocínio vem de `reasoning_content`/`thinking`; tags `<think>` são removidas do texto (o `llama-server` real emite `<think>\n` depois de chamadas de ferramenta).
4. **Resumo de raciocínio determinístico**, sem segunda chamada ao modelo.
5. **SSE com assinatura antes do replay**, backfill paginado e detecção de lacunas. Há uma só definição de duração de run: a do evento `turn` final, ou a soma das durações.
6. **Eventos `llm` registram o backend realmente usado**, além de `requested_backend`.
7. **`reasoning/progress` é efêmero no banco.** Vai ao vivo para os assinantes, mas sai do SQLite quando chega o `reasoning/final` do mesmo run e passo. Sobras com mais de 1 h (turnos que caíram antes do `final`) são apagadas no startup.

## Medições (PC do Victor)

RX 6600 (8 GB), 19,9 GB de RAM, `llama-server` b12532 (Vulkan), Qwen3.6-35B-A3B IQ4_XS, `--n-cpu-moe 30`, `--load-mode none`:
- ~21 tokens/s na geração e ~190 tokens/s no prefill (prompt de 2.278 tokens);
- um turno real com uma ferramenta levou 37,8 s (prompt de ~2.800 tokens).

Isso atende o item de ação 4 do ADR-0003 para velocidade.

## Trade-offs

- Barramento em processo: simples e sem dependências, mas só serve ao processo que grava. A CLI lê o SQLite.
- Resumo determinístico é previsível e grátis, porém mais pobre que um resumo gerado pelo modelo.
- Catálogo central exige atualizar um arquivo ao criar eventos, e os testes forçam isso.

## Limites conhecidos

- O monitor não tem autenticação. O servidor escuta em `127.0.0.1`, mas o guia da Oracle o publica na tailnet com `tailscale serve`.
- "Respondendo" só aparece com streaming: sem `on_delta`, o turno fica em "Pensando" até terminar.
- ~~`PHASES` rotulava `llm/done` como "Respondendo" mesmo quando o modelo pedia uma ferramenta.~~ Corrigido: a fase vem de `reasoning/answering`, gravado no primeiro trecho real da resposta.

## Consequências

- Documentação de processos nunca diverge do código.
- `nickel audit report|export|docs` permite revisar execuções sem subir a UI.

## Itens de ação

1. [x] Barramento, catálogo, SSE, aba Monitor e relatórios.
2. [x] Documentação gerada e CLI de auditoria.
3. [ ] Autenticação do monitor, se for exposto fora de `127.0.0.1` (o `tailscale serve` do guia da Oracle já expõe na tailnet).
4. [x] "Respondendo" vem de `reasoning/answering`, não de `llm/done`.
