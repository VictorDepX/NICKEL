# Voz do NICKEL com o VoiceStudio

O NICKEL fala pelo [VoiceStudio](https://github.com/debpalash/VoiceStudio), um app local com API compatível com a da OpenAI. Esta configuração foi verificada em 2026-11-22 num PC com Windows, RX 6600 de 8 GB e 20 GB de RAM, usando VoiceStudio 0.5.8 e o llama-server com Qwen3.6-35B-A3B rodando ao mesmo tempo.

## Configurar

1. Abra o app VoiceStudio. O backend sobe em `http://127.0.0.1:3900` em 30 a 40 s. Ele só responde enquanto o app estiver aberto.
2. No gerenciador de modelos do VoiceStudio, instale o motor **OmniVoice**. É a voz provisória genérica.
3. No `.env` do NICKEL:

   ```env
   TTS_PROVIDER=voicestudio
   VOICESTUDIO_URL=http://127.0.0.1:3900
   VOICESTUDIO_MODEL=omnivoice
   VOICESTUDIO_VOICE=default
   VOICESTUDIO_TIMEOUT_SECONDS=900
   ```

4. Rode `nickel doctor`. O resultado esperado é `[ok] VoiceStudio em http://127.0.0.1:3900 (voz: default)`. Se aparecer "modelo … ausente", troque `VOICESTUDIO_MODEL` por um dos modelos listados.
5. Em `nickel serve`, marque **Falar respostas** no cabeçalho. Use **Ouvir** em cada mensagem e **Parar** para interromper.

Nenhuma chave é exigida para chamadas feitas do próprio PC. Se o VoiceStudio responder 401 ou 403, gere uma chave nas configurações dele e coloque em `VOICESTUDIO_API_KEY`.

## Trocar a voz provisória

`VOICESTUDIO_VOICE` aceita o **nome** ou o **id** de um perfil de voz criado no VoiceStudio, por clonagem ou por descrição. `default` usa a voz padrão do motor. Se dois perfis tiverem o mesmo nome, o VoiceStudio responde `409 ambiguous_voice` e o erro aparece no Monitor. Nesse caso, use o id.

## O que foi medido

| Situação | Tempo |
|---|---|
| Primeira fala depois de abrir o VoiceStudio (carrega o OmniVoice) | 59 s |
| Frase curta, OmniVoice aquecido, sem o llama-server | 8,8 s |
| Resposta de 49 caracteres com o llama-server carregado (síntese + reprodução) | 39,7 s |
| `GET /v1/models` | ~2,4 s (por isso o teto de saúde do NICKEL é de 6 s) |
| VoxCPM2 (motor anterior) | 3 a 10 min por fala, inviável para conversa |

- **Formato:** o OmniVoice devolve WAV PCM de 16 bits, mono, a 24 kHz.
- **Cancelamento:** "Parar" registra `tts/done {interrupted: true}` no mesmo instante. Depois de cancelada, a fala não gerou áudio no VoiceStudio, ou seja, fechar a conexão interrompe a geração.
- **Memória:** o OmniVoice e o llama-server dividem a placa de vídeo. Com os dois carregados sobram ~1,3 GB de RAM. Se a fala ficar lenta demais, feche o VoiceStudio quando não precisar da voz.

## Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `doctor`: "abra o app VoiceStudio" | O app está fechado ou ainda subindo. Espere ~40 s depois de abrir. |
| Voz "sem resposta em 6 s" no estado | O VoiceStudio está ocupado gerando. O cache de 30 s se atualiza sozinho. |
| "VoiceStudio demorou demais para responder" | O motor é lento demais (ex.: VoxCPM2). Use OmniVoice ou aumente `VOICESTUDIO_TIMEOUT_SECONDS`. |
| "modelo X ausente" | O motor não está instalado. Instale-o no VoiceStudio ou ajuste `VOICESTUDIO_MODEL`. |
| Nota de voz do WhatsApp não chega | Outra fala estava ativa. O Monitor mostra `tts/skipped` ("voz ocupada"). O texto sempre é enviado antes. |

Os eventos `tts/start`, `tts/done`, `tts/skipped` e `tts/error` aparecem na aba Monitor e em `nickel audit export`.
