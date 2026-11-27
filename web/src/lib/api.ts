// Cliente tipado das rotas do NICKEL (nickel/app.py). Só `fetch`: sem estado e sem DOM.
import type { Catalog, AuditEvent } from "./monitor-core";

// ------------------------------------------------------------------ tipos

export type Level = "ok" | "warn" | "bad";

export interface ConnectorItem {
  id: string;
  name: string;
  level: Level;
  detail: string;
  /** Presente quando falta autorizar (ex.: `/auth/google/start`). */
  action?: string;
}

export interface TtsState {
  provider: string | null;
  ok: boolean;
  detail: string;
}

export interface VoiceState {
  available: boolean;
  state: string;
  stt: boolean;
  tts: TtsState;
  microphone: boolean;
}

export interface OAuthStatus {
  status: string;
  message?: string;
  missing?: string[];
  connect_url?: string;
}

export interface AppState {
  llm: { ok: boolean; model?: string; model_present?: boolean; detail?: string; [key: string]: unknown };
  whatsapp: { ready: boolean; detail?: string; [key: string]: unknown };
  google: OAuthStatus;
  spotify: OAuthStatus;
  obsidian: { available: boolean; notes_dir: string; vault: string };
  voice: VoiceState;
  connectors: ConnectorItem[];
  pipelines: ConnectorItem[];
  music: boolean;
  tools: string[];
  workspace: string;
  think_default: boolean;
}

export type MessageAttachment =
  | { type: "tools"; items: { name: string; ok: boolean; [key: string]: unknown }[] }
  | { type: "image" | "audio"; [key: string]: unknown };

export interface StoredMessage {
  id: number;
  channel: string;
  role: "user" | "assistant" | "system" | string;
  content: string;
  attachments: MessageAttachment[];
  created_at: string;
}

export interface Workspace {
  id: string;
  name: string;
  description: string;
  aliases: string[];
  backend: string | null;
  tools: string[] | null;
  notes_dir: string | null;
}

export interface WorkspacesResponse {
  active: string;
  items: Workspace[];
}

export interface ChatRequest {
  text: string;
  /** `null`: o servidor decide (workspace ativo ou LLM_THINK). */
  think?: boolean | null;
  /** `undefined`: vale a preferência guardada no servidor. */
  speak?: boolean;
}

export interface ChatResponse {
  text: string;
  pending_action_id: string | null;
  links: string[];
}

export interface Preferences {
  speak: boolean;
}

export interface PendingAction {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  summary: string;
  channel: string;
  status: string;
  created_at: string;
  result: Record<string, unknown> | null;
}

export interface Reminder {
  id: number;
  text: string;
  due_at: string;
  due_local: string;
  repeat: "none" | "daily" | "weekly" | "monthly" | string;
  status: string;
  calendar_event_id: string | null;
  created_at: string;
  delivered_at: string | null;
}

export interface NewReminder {
  text: string;
  /** Quando lembrar, em texto livre ou ISO (a rota é criada na Tarefa 7). */
  when: string;
}

export interface RunInfoRow {
  run_id: string;
  started_at: string;
  events: number;
  errors: number;
  duration_ms: number | null;
}

export interface MemoryEntry {
  key: string;
  value: string;
  created_at: string;
}

export interface SystemMemorySample {
  t: number;
  total: number;
  used: number;
  available: number;
  llama: number;
  nickel: number;
}

export interface SystemMemory {
  available: boolean;
  samples: SystemMemorySample[];
  interval_s: number;
}

// ------------------------------------------------------------------ transporte

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function failure(response: Response): Promise<ApiError> {
  let message = response.statusText || `HTTP ${response.status}`;
  try {
    const text = await response.text();
    if (text) {
      try {
        const body = JSON.parse(text) as { detail?: unknown };
        message = typeof body.detail === "string" ? body.detail : text;
      } catch {
        message = text;
      }
    }
  } catch {
    /* corpo ilegível: fica a mensagem padrão */
  }
  return new ApiError(response.status, message);
}

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "content-type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

const enc = encodeURIComponent;

// ------------------------------------------------------------------ rotas

export const getState = () => request<AppState>("/api/state");

export const getMessages = (limit = 120, workspace?: string) =>
  request<StoredMessage[]>(`/api/messages?limit=${limit}${workspace ? `&workspace=${enc(workspace)}` : ""}`);

export const getWorkspaces = () => request<WorkspacesResponse>("/api/workspaces");

export const activateWorkspace = (id: string) =>
  request<{ active: string; name: string }>(`/api/workspaces/${enc(id)}/activate`, "POST");

export const sendChat = ({ text, think, speak }: ChatRequest) => {
  const body: Record<string, unknown> = { text, think: think ?? null };
  if (speak !== undefined) body.speak = speak;
  return request<ChatResponse>("/api/chat", "POST", body);
};

export const getPreferences = () => request<Preferences>("/api/preferences");
export const setPreferences = (prefs: Preferences) => request<Preferences>("/api/preferences", "POST", prefs);

export const ttsSpeak = (text: string) => request<{ accepted: boolean }>("/api/tts/speak", "POST", { text });
export const ttsStop = () => request<{ stopped: boolean }>("/api/tts/stop", "POST");

export const getPending = () => request<PendingAction[]>("/api/pending");
export const confirmPending = (id: string) => request<{ text: string }>(`/api/pending/${enc(id)}/confirm`, "POST");
export const cancelPending = (id: string) => request<{ text: string }>(`/api/pending/${enc(id)}/cancel`, "POST");

export const getReminders = () => request<Reminder[]>("/api/reminders");
export const createReminder = ({ text, when }: NewReminder) =>
  request<Reminder>("/api/reminders", "POST", { text, when });
export const cancelReminder = (id: number) => request<{ cancelled: number }>(`/api/reminders/${id}`, "DELETE");

export const getAudit = (limit = 40) => request<AuditEvent[]>(`/api/audit?limit=${limit}`);
export const getRuns = (limit = 20) => request<RunInfoRow[]>(`/api/runs?limit=${limit}`);
export const getRun = (id: string) => request<AuditEvent[]>(`/api/runs/${enc(id)}`);
/** Link de download do relatório em Markdown (não passa por `fetch`). */
export const runReportUrl = (id: string) => `/api/runs/${enc(id)}/report.md`;

export const getMemory = () => request<MemoryEntry[]>("/api/memory");
export const forgetMemory = (key: string) => request<{ deleted: boolean }>(`/api/memory/${enc(key)}`, "DELETE");
export const getSystemMemory = () => request<SystemMemory>("/api/system/memory");

export const getEventsCatalog = () => request<Required<Catalog>>("/api/events/catalog");

export const toggleVoice = () => request<{ state: string }>("/voice/toggle", "POST");
