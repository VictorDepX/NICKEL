import { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainIcon, MicIcon, Volume2Icon } from "lucide-react";
import { useLocation, useNavigate } from "react-router";
import { toast } from "sonner";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { ChatMessage, VOICE_OFF_TITLE } from "@/components/chat/chat-message";
import { ConfirmationCard } from "@/components/chat/confirmation-card";
import { StatusLine, useNow } from "@/components/chat/status-line";
import { TurnActivity } from "@/components/chat/turn-activity";
import { VoiceBar } from "@/components/chat/voice-bar";
import { Orb } from "@/components/orb";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { APP_STATE_KEY, useAppState } from "@/hooks/use-app-state";
import { useEvents } from "@/hooks/use-events";
import { useResolvePending } from "@/hooks/use-resolve-pending";
import { PENDING_KEY, usePending, useWorkspaces } from "@/hooks/use-shell-data";
import {
  getMessages,
  getPreferences,
  sendChat,
  setPreferences,
  toggleVoice,
  ttsSpeak,
  ttsStop,
} from "@/lib/api";
import { activityPlacement, lastServerId, pendingLocals, turnAnchor, turnView, type LocalMessage } from "@/lib/chat-turn";
import { chatStatus, type AuditEvent } from "@/lib/monitor-core";
import { MESSAGES_KEY, readThink, writeThink } from "@/lib/conversa-prefs";
import { cn } from "@/lib/utils";

export const PREFERENCES_KEY = ["preferences"] as const;

const TOGGLE_PILL =
  "h-auto min-h-11 gap-1.5 rounded-full border border-input px-3.5 text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground md:min-h-9 data-[state=on]:border-[#2e3a47] data-[state=on]:bg-accent data-[state=on]:text-accent-foreground";

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));

/** Eventos que mudam o histórico (turno terminou) ou as confirmações pendentes. */
function useChatInvalidation() {
  const queryClient = useQueryClient();
  const { state } = useEvents();
  const seen = useRef<number | null>(null);
  useEffect(() => {
    const previous = seen.current;
    seen.current = state.lastId;
    if (previous === null) return;
    const fresh = state.timeline.filter((e: AuditEvent) => e.id > previous);
    if (fresh.some((e) => e.kind === "confirmation")) {
      void queryClient.invalidateQueries({ queryKey: PENDING_KEY });
    }
    if (fresh.some((e) => e.kind === "confirmation" || (e.kind === "turn" && (e.status === "done" || e.status === "error")))) {
      void queryClient.invalidateQueries({ queryKey: MESSAGES_KEY });
    }
  }, [state.lastId, state.timeline, queryClient]);
}

function ErrorCard({ title, message }: { title: string; message: string }) {
  return (
    <div role="alert" className="w-full max-w-[92%] rounded-[18px] border border-destructive/35 bg-destructive/10 px-4 py-3 text-sm">
      <p className="font-medium text-destructive-foreground">{title}</p>
      <p className="mt-1 break-words text-muted-foreground">{message}</p>
    </div>
  );
}

export default function Conversa() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const { state, connected } = useEvents();
  const { data: appState } = useAppState();
  const { data: workspaces } = useWorkspaces();
  const { data: pending } = usePending();
  useChatInvalidation();

  const workspaceId = appState?.workspace ?? workspaces?.active ?? "";
  const messages = useQuery({
    queryKey: [...MESSAGES_KEY, workspaceId],
    queryFn: () => getMessages(120, workspaceId || undefined),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });
  const preferences = useQuery({ queryKey: PREFERENCES_KEY, queryFn: getPreferences });

  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<{ title: string; message: string } | null>(null);
  const [locals, setLocals] = useState<LocalMessage[]>([]);
  const [thinkChoice, setThinkChoice] = useState<boolean | null>(readThink);

  const think = thinkChoice ?? appState?.think_default ?? false;
  const speak = preferences.data?.speak ?? false;
  const voiceOn = Boolean(appState?.voice?.tts?.provider);
  const micAvailable = appState?.voice?.available === true;
  const workspaceName = workspaces?.items.find((w) => w.id === workspaceId)?.name ?? (workspaceId || "geral");

  const status = chatStatus(state, 0);
  const now = useNow(status.active);
  const turn = useMemo(() => turnView(state, now), [state, now]);

  const server = useMemo(() => messages.data ?? [], [messages.data]);
  const unsynced = useMemo(() => pendingLocals(server, locals), [server, locals]);
  const anchor = turnAnchor(server, turn);

  const speakPref = useMutation({
    mutationFn: (value: boolean) => setPreferences({ speak: value }),
    onMutate: async (value) => {
      const previous = queryClient.getQueryData(PREFERENCES_KEY);
      queryClient.setQueryData(PREFERENCES_KEY, { speak: value });
      return { previous };
    },
    onError: (err, _value, context) => {
      queryClient.setQueryData(PREFERENCES_KEY, context?.previous);
      toast.error(`Falha ao salvar a preferência: ${errorText(err)}`);
    },
  });

  const addLocal = (role: LocalMessage["role"], content: string): LocalMessage => {
    const local: LocalMessage = {
      key: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role,
      content,
      created_at: new Date().toISOString(),
      afterId: lastServerId(messages.data),
    };
    setLocals((prev) => [...prev, local]);
    return local;
  };

  /** Busca o histórico de novo; `true` se veio. */
  const syncMessages = async () => {
    try {
      await queryClient.invalidateQueries({ queryKey: MESSAGES_KEY }, { throwOnError: true });
      return true;
    } catch {
      return false;
    }
  };

  const handleSubmit = async ({ text: raw }: PromptInputMessage) => {
    const value = (raw ?? text).trim();
    if (!value || sending) return;
    setError(null);
    setSending(true);
    setText("");
    const mine = addLocal("user", value);
    try {
      const reply = await sendChat({ text: value, think: thinkChoice, speak: preferences.data?.speak });
      if (reply.text.trim()) addLocal("assistant", reply.text);
      void queryClient.invalidateQueries({ queryKey: APP_STATE_KEY });
      // O servidor grava a mensagem (às vezes sem o comando de área): com o histórico novo, a otimista sai.
      if (await syncMessages()) setLocals((prev) => prev.filter((m) => m.key !== mine.key));
    } catch (err) {
      setLocals((prev) => prev.filter((m) => m.key !== mine.key));
      setText((current) => (current.trim() ? current : value)); // não apaga o que foi digitado durante o envio
      setError({ title: "Falha ao enviar", message: errorText(err) });
      void syncMessages();
    } finally {
      setSending(false);
    }
  };

  // Rascunho vindo do Início: envia uma vez e limpa o estado da rota, para um reload não reenviar.
  const draftSent = useRef(false);
  const draft = (location.state as { draft?: unknown } | null)?.draft;
  useEffect(() => {
    if (typeof draft !== "string" || !draft.trim() || draftSent.current || preferences.isPending) return;
    draftSent.current = true;
    navigate(location.pathname, { replace: true, state: null });
    void handleSubmit({ text: draft, files: [] });
    // handleSubmit muda a cada render; o ref garante o envio único.
  }, [draft, preferences.isPending]);

  const { resolve, busyId: busyPending } = useResolvePending();
  const resolvePending = async (id: string, decision: "confirm" | "cancel") => {
    setError(null);
    await resolve(id, decision, (result) => {
      if (result.ok) {
        if (result.text.trim()) addLocal("assistant", result.text);
      } else {
        setError({ title: decision === "confirm" ? "Falha ao confirmar" : "Falha ao cancelar", message: errorText(result.error) });
      }
    });
  };

  const listen = (value: string) => {
    ttsSpeak(value).catch((err) => toast.error(`Falha ao falar: ${errorText(err)}`));
  };
  const copy = (value: string) => {
    navigator.clipboard
      ?.writeText(value)
      .then(() => toast.success("Resposta copiada"))
      .catch(() => toast.error("Não foi possível copiar"));
  };
  const stopSpeech = () => {
    ttsStop().catch((err) => toast.error(`Falha ao parar: ${errorText(err)}`));
  };
  const mic = () => {
    toggleVoice().catch((err) => toast.error(`Falha no microfone: ${errorText(err)}`));
  };

  const placement = activityPlacement(turn, anchor);
  const activity = turn && placement !== "none" ? <TurnActivity key={turn.runId} reasoning={turn.reasoning} tools={turn.tools} /> : null;
  const empty = !server.length && !unsynced.length && !messages.isPending && !messages.isError;
  const speaking = state.phase === "speaking";

  return (
    <section className="flex h-[calc(100svh-53px)] min-h-0 flex-col md:h-svh md:pr-32" aria-label="Conversa">
      <header className="flex flex-wrap items-center gap-3 border-b border-border-soft px-4 py-3 md:px-6">
        <Orb size={44} phase={state.phase} />
        <h1 className="min-w-0 flex-1 truncate text-[15px] font-semibold tracking-tight">
          NICKEL <span className="font-normal text-muted-foreground">· {workspaceName}</span>
        </h1>
        <div className="flex items-center gap-2">
          <Toggle
            pressed={think}
            onPressedChange={(value) => {
              setThinkChoice(value);
              writeThink(value);
            }}
            className={TOGGLE_PILL}
            aria-label="Pensar"
            title="Pensar antes de responder"
          >
            <BrainIcon aria-hidden="true" />
            <span className="hidden sm:inline">Pensar</span>
          </Toggle>
          <Toggle
            pressed={speak}
            disabled={!voiceOn || preferences.isPending}
            onPressedChange={(value) => speakPref.mutate(value)}
            className={TOGGLE_PILL}
            aria-label="Falar respostas"
            title={voiceOn ? "Falar as respostas em voz alta" : VOICE_OFF_TITLE}
          >
            <Volume2Icon aria-hidden="true" />
            <span className="hidden sm:inline">Falar respostas</span>
          </Toggle>
        </div>
      </header>

      <Conversation className="min-h-0">
        <ConversationContent className="mx-auto w-full max-w-3xl gap-6 px-4 py-6 md:px-6">
          {messages.isError ? (
            <ErrorCard title="Não foi possível carregar a conversa" message={errorText(messages.error)} />
          ) : null}
          {empty ? <ConversationEmptyState className="min-h-48" /> : null}
          {server.map((message, i) => (
            <div key={message.id} className="contents">
              {placement === "anchor" && i === anchor ? activity : null}
              <ChatMessage
                message={message}
                durationMs={i === anchor ? turn?.durationMs : null}
                tokensPerSecond={i === anchor ? turn?.tokensPerSecond : null}
                hideTools={i === anchor && Boolean(turn?.tools.length)}
                voiceOn={voiceOn}
                onListen={listen}
                onCopy={copy}
              />
            </div>
          ))}
          {unsynced
            .filter((m) => m.role === "user")
            .map((m) => (
              <ChatMessage key={m.key} message={{ ...m, channel: "ui" }} />
            ))}
          {placement === "bottom" ? activity : null}
          {unsynced
            .filter((m) => m.role === "assistant")
            .map((m) => (
              <ChatMessage key={m.key} message={{ ...m, channel: "ui" }} voiceOn={voiceOn} onListen={listen} onCopy={copy} />
            ))}
          {(pending ?? []).map((action) => (
            <ConfirmationCard
              key={action.id}
              action={action}
              busy={busyPending === action.id}
              onConfirm={(id) => void resolvePending(id, "confirm")}
              onCancel={(id) => void resolvePending(id, "cancel")}
            />
          ))}
          {error ? <ErrorCard title={error.title} message={error.message} /> : null}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-4 pb-4 md:px-6">
        {speaking ? <VoiceBar onStop={stopSpeech} /> : null}
        <StatusLine state={state} connected={connected} sending={sending} />
        <PromptInput onSubmit={handleSubmit}>
          <PromptInputBody>
            <PromptInputTextarea
              aria-label="Mensagem para o NICKEL"
              value={text}
              onChange={(e) => setText(e.currentTarget.value)}
              className="min-h-12 px-4 text-[15px]"
            />
          </PromptInputBody>
          <PromptInputFooter>
            <PromptInputTools>
              <Tooltip>
                <TooltipTrigger asChild>
                  {/* Botão desabilitado não recebe foco nem hover: o span segura a dica. */}
                  <span tabIndex={micAvailable ? -1 : 0} className="inline-flex rounded-full">
                    <PromptInputButton
                      aria-label="Microfone"
                      aria-pressed={state.phase === "listening"}
                      disabled={!micAvailable}
                      onClick={mic}
                      className={cn("size-11 rounded-full", state.phase === "listening" && "bg-accent text-accent-foreground")}
                    >
                      <MicIcon className="size-5" aria-hidden="true" />
                    </PromptInputButton>
                  </span>
                </TooltipTrigger>
                <TooltipContent>{micAvailable ? "Falar com o NICKEL" : "Microfone não configurado"}</TooltipContent>
              </Tooltip>
            </PromptInputTools>
            <PromptInputSubmit
              status={sending ? "submitted" : undefined}
              disabled={sending || !text.trim()}
              className="size-11 rounded-full"
            />
          </PromptInputFooter>
        </PromptInput>
      </div>
    </section>
  );
}
