import { CopyIcon, Volume2Icon } from "lucide-react";
import { Message, MessageAction, MessageActions, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import type { MessageAttachment } from "@/lib/api";
import { messageTime } from "@/lib/chat-turn";
import { formatDuration, num } from "@/lib/monitor-core";
import { cn } from "@/lib/utils";

const CHANNELS: Record<string, string> = { whatsapp: "whatsapp", voice: "voz", ui: "ui", lembrete: "lembrete" };
export const VOICE_OFF_TITLE = "Voz desligada: configure TTS_PROVIDER (edge, VoiceStudio ou Piper) para ouvir as respostas.";

export interface ChatMessageData {
  role: string;
  content: string;
  channel?: string;
  created_at: string;
  attachments?: MessageAttachment[];
}

interface ChatMessageProps {
  message: ChatMessageData;
  /** Números do turno, quando esta é a resposta do turno atual. */
  durationMs?: number | null;
  tokensPerSecond?: number | null;
  voiceOn?: boolean;
  onListen?: (text: string) => void;
  onCopy?: (text: string) => void;
  /** O turno atual já mostra os blocos de ferramenta desta resposta. */
  hideTools?: boolean;
}

const URL_RE = /(https?:\/\/[^\s<]+)/g;

function Linkified({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  return (
    <p className="break-words whitespace-pre-wrap">
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <a key={i} href={part} target="_blank" rel="noopener noreferrer" className="text-ice underline-offset-2 hover:underline">
            {part}
          </a>
        ) : (
          part
        ),
      )}
    </p>
  );
}

function toolItems(attachments: MessageAttachment[] | undefined) {
  return (attachments ?? [])
    .filter((a): a is Extract<MessageAttachment, { type: "tools" }> => a.type === "tools")
    .flatMap((a) => a.items ?? []);
}

function mediaLabel(attachments: MessageAttachment[] | undefined): string {
  return (attachments ?? [])
    .filter((a) => a.type === "image" || a.type === "audio")
    .map((a) => (a.type === "image" ? "[imagem]" : "[áudio]"))
    .join(" ");
}

/** Uma mensagem da conversa: usuário em balão à direita; NICKEL sem balão, em markdown, com meta e ações. */
export function ChatMessage({ message, durationMs, tokensPerSecond, voiceOn = true, onListen, onCopy, hideTools = false }: ChatMessageProps) {
  const system = message.channel === "lembrete" || message.role === "system";
  const from = message.role === "user" && !system ? "user" : "assistant";
  const tools = hideTools ? [] : toolItems(message.attachments);
  const media = mediaLabel(message.attachments);
  const text = message.content;
  const meta = [
    message.channel ? CHANNELS[message.channel] ?? message.channel : null,
    messageTime(message.created_at),
    durationMs != null ? formatDuration(durationMs) : null,
    tokensPerSecond != null ? `${num(tokensPerSecond, 1)} tok/s` : null,
  ].filter(Boolean) as string[];

  return (
    <Message from={from} data-role={from}>
      <MessageContent className={cn(system && "text-muted-foreground")}>
        {media ? <span className="text-xs text-subtle-foreground">{media}</span> : null}
        {from === "assistant" ? <MessageResponse>{text}</MessageResponse> : <Linkified text={text} />}
      </MessageContent>
      {tools.length ? (
        <div className="flex flex-wrap gap-1.5" aria-label="Ferramentas usadas">
          {tools.map((tool, i) => (
            <span
              key={`${tool.name}-${i}`}
              className={cn(
                "inline-flex h-[22px] items-center rounded-md px-2 font-mono text-xs",
                tool.ok ? "bg-success/12 text-[#86efac]" : "bg-destructive/12 text-destructive-foreground",
              )}
            >
              {tool.ok ? "ok" : "erro"} · {tool.name}
            </span>
          ))}
        </div>
      ) : null}
      <div className={cn("flex flex-wrap items-center gap-1.5 text-xs text-subtle-foreground", from === "user" && "justify-end")}>
        {meta.map((part, i) => (
          <span key={i} className={i === 0 && message.channel ? "font-mono" : undefined}>
            {i > 0 ? "· " : ""}
            {part}
          </span>
        ))}
        {from === "assistant" && text.trim() ? (
          <MessageActions className="ml-1">
            <MessageAction
              label="Ouvir"
              tooltip={voiceOn ? "Ouça esta resposta em voz alta" : VOICE_OFF_TITLE}
              disabled={!voiceOn}
              onClick={() => onListen?.(text)}
              className="h-8 w-auto gap-1 px-2 text-xs text-muted-foreground"
            >
              <Volume2Icon className="size-3.5" aria-hidden="true" />
              <span aria-hidden="true">Ouvir</span>
            </MessageAction>
            <MessageAction
              label="Copiar"
              tooltip="Copiar a resposta"
              onClick={() => onCopy?.(text)}
              className="h-8 w-auto gap-1 px-2 text-xs text-muted-foreground"
            >
              <CopyIcon className="size-3.5" aria-hidden="true" />
              <span aria-hidden="true">Copiar</span>
            </MessageAction>
          </MessageActions>
        ) : null}
      </div>
    </Message>
  );
}
