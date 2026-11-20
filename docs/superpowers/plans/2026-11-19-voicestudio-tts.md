# Voz do NICKEL via VoiceStudio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O NICKEL fala com a voz do VoiceStudio instalado no PC (voz genérica provisória), a partir da GUI, com eventos de fala visíveis no monitor.

**Architecture:** Um `VoiceStudioSpeaker` implementa o protocolo `Speaker` existente e chama `POST {url}/v1/audio/speech` (API compatível com OpenAI) pedindo WAV. A reprodução sai de `tts.py` para `playback.py`, que usa `winsound` no Windows. `Services.speak()` é o ponto único de fala: audita, nunca levanta exceção e cancela a fala anterior. A GUI ganha "Falar respostas" e um botão de ouvir por mensagem.

**Tech Stack:** Python 3.11, httpx, `wave`/`winsound` (stdlib), FastAPI, JS puro.

**Spec:** `docs/superpowers/specs/2026-11-19-observabilidade-e-voz-design.md` (seção 2)

**Pré-requisito:** o plano `2026-11-19-observabilidade-auditoria.md` precisa ter as Tasks 1 e 2 concluídas (`AuditLog.record` devolve evento e `nickel/core/events.py` existe). Execute este plano depois dele.

## Global Constraints

- Sem dependências novas de runtime; Windows e Linux; a resposta em texto nunca depende da voz.
- VoiceStudio: porta padrão `3900`, rota `POST /v1/audio/speech` com corpo `{model, input (máx. 4096 caracteres), voice, response_format, speed}`; `model` padrão `omnivoice`; `voice` padrão `default` (nomes OpenAI como `alloy` também mapeiam para a voz padrão do motor).
- Pedir sempre `response_format: "wav"` (o `winsound` só toca WAV e não exige ffmpeg).
- Fala em blocos de até 4000 caracteres (limite da API menos folga), cortando em fim de frase.
- Textos da UI em PT-BR no imperativo.
- Nenhum áudio em base64 nem chave de API em eventos ou logs.

## Review Focus

- VoiceStudio fechado, lento (primeira chamada carrega o modelo) ou respondendo erro: a resposta em texto sai normalmente, o evento `tts/error` registra o motivo e a UI não fica presa em "Falando".
- Resposta longa, com markdown, URLs ou emojis: o texto falado é limpo e dividido em blocos válidos, sem cortar palavra.
- Segunda fala enquanto a primeira toca: a primeira é interrompida, sem sobreposição.
- `409 ambiguous_voice` (dois perfis com o mesmo nome): o erro chega legível ao evento.
- Chave de API vazia: nenhum cabeçalho `Authorization`; preenchida: `Bearer <chave>`.

---

### Task 1: Reprodução multiplataforma e cliente VoiceStudio

**Files:**
- Create: `nickel/speech/playback.py`, `nickel/speech/voicestudio.py`
- Modify: `nickel/speech/tts.py` (o `PiperSpeaker` passa a usar `playback`), `nickel/config.py`
- Test: `tests/test_voicestudio.py`

**Interfaces:**
- Produces:
  - `Settings`: `tts_provider: str = "auto"` (`TTS_PROVIDER`: `auto|voicestudio|piper|none`), `voicestudio_url: str = ""` (`VOICESTUDIO_URL`), `voicestudio_api_key: str = ""`, `voicestudio_model: str = "omnivoice"`, `voicestudio_voice: str = "default"`, `voicestudio_timeout_seconds: float = 120.0` (a primeira chamada carrega o modelo).
  - `playback.play_wav(path: Path) -> None` (async) e `playback.stop_playback() -> None`. No Windows: `winsound.PlaySound(str(path), SND_FILENAME)` em `asyncio.to_thread` e, para parar, `PlaySound(None, SND_PURGE)`. Nos outros sistemas: a lista atual `pw-play`, `paplay`, `aplay`.
  - `class TTSError(RuntimeError)`.
  - `split_for_tts(text: str, limit: int = 4000) -> list[str]`: limpa com `clean_for_speech`, corta em fim de frase (`.`, `!`, `?`, quebra de linha) e só corta no meio da frase se ela passar do limite.
  - `VoiceStudioSpeaker(settings: Settings, work_dir: Path, transport: httpx.AsyncBaseTransport | None = None)` com `async synthesize(text) -> Path` (WAV único; vários blocos são concatenados com `wave`), `async speak(text) -> None`, `stop() -> None`, `async health() -> dict` (`GET /v1/models`; `{"ok": bool, "detail": str}`) e `async aclose()`.

- [ ] **Step 1: Escrever os testes que falham** (`httpx.MockTransport`; para o `winsound`, um módulo falso injetado em `sys.modules`)
  - `test_split_for_tts_cleans_and_respects_limit_on_sentence_boundaries`.
  - `test_split_for_tts_empty_after_cleaning_returns_empty_list`.
  - `test_synthesize_posts_expected_body`: o corpo tem `model="omnivoice"`, `voice="default"`, `response_format="wav"` e `input` limpo (sem markdown/URL); devolve um arquivo WAV legível com `wave`.
  - `test_authorization_header_only_when_api_key_set`.
  - `test_long_text_makes_several_requests_and_concatenates_wav`.
  - `test_http_error_becomes_tts_error_with_openai_message` (corpo `{"error":{"message":"...","code":"ambiguous_voice"}}` → `TTSError` cuja mensagem contém o texto).
  - `test_timeout_becomes_tts_error`.
  - `test_health_ok_and_offline` (`GET /v1/models` 200 vs. falha de conexão).
  - `test_speak_empty_text_makes_no_request`.
  - `test_play_wav_uses_winsound_on_windows_and_stop_purges` e `test_play_wav_uses_first_available_player_on_linux`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_voicestudio.py -v`
Expected: FAIL (módulos inexistentes).

- [ ] **Step 3: Implementar**
  - `playback.py` extrai a lógica de `_PLAYERS` hoje em `PiperSpeaker.play`; `PiperSpeaker.play` e `stop` delegam a ele.
  - O erro HTTP lê `error.message` do JSON no padrão OpenAI e, se faltar, usa o texto cru (até 200 caracteres).
  - `stop()` chama `stop_playback()` e marca um evento de cancelamento que `speak` checa entre blocos.

- [ ] **Step 4: Rodar tudo**

Run: `pytest tests/test_voicestudio.py -v && pytest -q`
Expected: PASS (inclusive os testes antigos de TTS/Piper, se houver).

- [ ] **Step 5: Commit**

```bash
git add nickel/speech nickel/config.py tests/test_voicestudio.py
git commit -m "feat(voz): cliente VoiceStudio e reprodução multiplataforma"
```

---

### Task 2: Ligação nos serviços, doctor e estado

**Files:**
- Modify: `nickel/services.py` (`build_services`), `nickel/cli.py` (`doctor`), `nickel/app.py` (`/api/state`), `.env.example`
- Test: `tests/test_voicestudio_wiring.py`

**Interfaces:**
- Consumes: `VoiceStudioSpeaker`, `PiperSpeaker`, `Settings.tts_provider`.
- Produces:
  - `build_services`: `tts_provider="voicestudio"` ou (`"auto"` com `voicestudio_url` definida) cria `VoiceStudioSpeaker`; `"piper"` ou (`"auto"` sem URL e com `tts_voice_path`) mantém o Piper; `"none"` deixa `services.tts = None`.
  - `/api/state.voice` ganha `tts: {"provider": "voicestudio"|"piper"|None, "ok": bool, "detail": str}` (a verificação usa `health()` com cache de 30 s).
  - `doctor`: `[ok] VoiceStudio em <url> (voz: <voz>)` ou `[!!] VoiceStudio em <url> — abra o app VoiceStudio`.
  - `.env.example` documenta `TTS_PROVIDER`, `VOICESTUDIO_URL=http://127.0.0.1:3900`, `VOICESTUDIO_API_KEY`, `VOICESTUDIO_MODEL`, `VOICESTUDIO_VOICE=default`.

- [ ] **Step 1: Escrever os testes que falham**
  - `test_auto_prefers_voicestudio_when_url_set`.
  - `test_auto_falls_back_to_piper_without_url`.
  - `test_provider_none_disables_tts`.
  - `test_state_reports_provider_and_health_cached` (duas chamadas seguidas → uma só requisição ao VoiceStudio).
  - `test_doctor_line_for_voicestudio_online_and_offline`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_voicestudio_wiring.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar.** O `health()` do VoiceStudio nunca bloqueia o `/api/state` por mais de 2 s.

- [ ] **Step 4: Rodar tudo**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nickel .env.example tests/test_voicestudio_wiring.py
git commit -m "feat(voz): seleção de provedor, estado e doctor para o VoiceStudio"
```

---

### Task 3: Falar pela GUI, com auditoria

**Files:**
- Modify: `nickel/services.py` (`Services.speak`), `nickel/core/events.py` (kind `tts`), `nickel/channels/voice.py` (usa `services.speak`), `nickel/app.py` (rotas), `nickel/core/stores.py` se faltar chave de estado, `nickel/ui/static/index.html`, `nickel/ui/static/app.js`, `nickel/ui/static/monitor-core.js` (nada a mudar se o catálogo vier do servidor)
- Test: `tests/test_tts_api.py`

**Interfaces:**
- Consumes: `AuditLog.record(..., duration_ms=...)`, `CATALOG`/`PHASES` (observabilidade T2), `StateStore.get/set`.
- Produces:
  - `Services.speak(text: str, *, source: str) -> None` (async): cancela a fala em curso (`tts.stop()`), emite `tts/start {source, chars, provider, voice}`, chama `tts.speak(text)`, depois `tts/done {chars}` com `duration_ms`; qualquer exceção vira `tts/error {detail}` e **não** se propaga. Sem `tts` configurado: `tts/error {detail: "voz indisponível"}`.
  - Catálogo: `CATALOG["tts"]` (estados `start, done, error`), `PHASES`: `tts/start→speaking`, `tts/done→idle`, `tts/error→error`.
  - Rotas: `POST /api/tts/speak` com `{text}` → `202`; `POST /api/tts/stop` → `{"stopped": true}`; `GET /api/preferences` → `{"speak": bool}`; `POST /api/preferences` com `{speak: bool}`, persistido em `StateStore` na chave `ui.speak`. `/api/chat` aceita `speak: bool | null` (sobrescreve a preferência) e, quando ligado, dispara `services.speak(reply.text, source="ui")` em segundo plano (a resposta HTTP não espera a fala).
  - UI: caixa "Falar respostas" no cabeçalho, botão "Ouvir" em cada mensagem do assistente e botão "Parar" visível enquanto a fase for `speaking`.

- [ ] **Step 1: Escrever os testes que falham** (speaker falso com `speak`/`stop` registrados)
  - `test_speak_emits_start_done_with_duration`.
  - `test_speak_swallows_errors_and_emits_tts_error`.
  - `test_speak_without_tts_emits_error_event`.
  - `test_second_speak_stops_the_first`.
  - `test_chat_with_speak_true_triggers_speech_without_blocking_reply`.
  - `test_preferences_roundtrip_persist_in_state`.
  - `test_chat_uses_stored_preference_when_flag_absent`.
  - `test_tts_speak_and_stop_endpoints`.
  - `test_voice_controller_speaks_through_services_speak`.
  - `test_catalog_has_tts_and_phase_mapping`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_tts_api.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar** os itens acima. A tarefa de fala em segundo plano fica em um conjunto de tarefas do app (como `spawn` já faz) para não ser coletada pelo GC.

- [ ] **Step 4: Rodar tudo**

Run: `pytest -q && node --test tests/js && python -m pyflakes nickel tests`
Expected: PASS e `pyflakes` sem saída.

- [ ] **Step 5: Commit**

```bash
git add nickel tests/test_tts_api.py
git commit -m "feat(voz): falar respostas pela GUI com eventos de auditoria"
```

---

### Task 4: Verificação real no PC e documentação

**Files:**
- Create: `docs/deploy/voicestudio.md`
- Modify: `README.md`

Esta tarefa roda no PC do Victor (nada aqui é simulado) e corrige o código se a API real divergir do que este plano assumiu.

- [ ] **Step 1: Subir o VoiceStudio e achar a porta/autenticação**

Run (PowerShell): `Start-Process "$env:LOCALAPPDATA\Programs\VoiceStudio\VoiceStudio.exe"; Start-Sleep 20; Get-NetTCPConnection -State Listen | Where-Object { $_.OwningProcess -in (Get-Process VoiceStudio*).Id } | Select LocalPort`
Expected: uma porta em escuta (esperada: 3900). Se for outra, use-a em `VOICESTUDIO_URL`.

- [ ] **Step 2: Conferir a rota e a autenticação**

Run: `curl.exe -s http://127.0.0.1:3900/v1/models`
Expected: JSON com a lista de modelos, sem exigir chave a partir do próprio PC. Se responder `403`, gere uma chave nas configurações do VoiceStudio e coloque em `VOICESTUDIO_API_KEY`.

- [ ] **Step 3: Sintetizar de verdade**

Run: `curl.exe -s -X POST http://127.0.0.1:3900/v1/audio/speech -H "Content-Type: application/json" -d "{\"model\":\"omnivoice\",\"input\":\"Olá, eu sou o Nickel.\",\"voice\":\"default\",\"response_format\":\"wav\"}" -o D:\NICKEL\data\tmp\teste.wav`
Expected: arquivo WAV tocável (`(New-Object Media.SoundPlayer D:\NICKEL\data\tmp\teste.wav).PlaySync()`). Se o OmniVoice não falar português bem, anote e teste outro `model` listado no Step 2.

- [ ] **Step 4: Ponta a ponta pela GUI**

Configure o `.env` (`VOICESTUDIO_URL`, `TTS_PROVIDER=auto`), rode `nickel doctor` e `nickel serve`. Marque "Falar respostas", envie uma mensagem e ouça a resposta.
Expected: `doctor` com `[ok] VoiceStudio`; a faixa do Monitor passa por "Falando" e volta a "Ocioso"; o evento `tts/done` mostra a duração. Feche o VoiceStudio e envie outra mensagem: o texto responde e aparece `tts/error`, sem travar.

- [ ] **Step 5: Documentar e commitar**

Escreva `docs/deploy/voicestudio.md` (porta, chave, modelo, como trocar a voz provisória por um perfil: `VOICESTUDIO_VOICE=<nome do perfil>`, problemas comuns) e linke no `README.md`.

```bash
git add docs/deploy/voicestudio.md README.md
git commit -m "docs(voz): guia de integração com o VoiceStudio verificado no PC"
```
