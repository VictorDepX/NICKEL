import { useState } from "react";
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from "@/components/ai-elements/tool";
import type { TurnReasoning, TurnToolCall } from "@/lib/chat-turn";
import { formatDuration, num } from "@/lib/monitor-core";

/** Resumo do raciocínio fechado: "Raciocínio · N caracteres · T s". */
export function reasoningLabel(reasoning: TurnReasoning): string {
  const parts = ["Raciocínio", `${num(reasoning.chars)} caracteres`];
  if (reasoning.durationMs != null) parts.push(formatDuration(reasoning.durationMs));
  return parts.join(" · ");
}

function TurnReasoningBlock({ reasoning }: { reasoning: TurnReasoning }) {
  // Montado durante o raciocínio: abre e fecha sozinho (uma vez) quando ele acaba. Montado depois: já vem fechado.
  const [openAtMount] = useState(reasoning.active);
  return (
    <Reasoning isStreaming={reasoning.active} defaultOpen={openAtMount}>
      <ReasoningTrigger
        getThinkingMessage={(streaming) =>
          streaming ? (
            <Shimmer as="span" duration={1.4}>{`Pensando… · ${num(reasoning.chars)} caracteres`}</Shimmer>
          ) : (
            <span>{reasoningLabel(reasoning)}</span>
          )
        }
      />
      <ReasoningContent>{reasoning.text || "…"}</ReasoningContent>
    </Reasoning>
  );
}

function TurnTool({ call }: { call: TurnToolCall }) {
  return (
    <Tool>
      <ToolHeader name={call.name} state={call.state} hint={call.durationMs != null ? formatDuration(call.durationMs) : undefined} />
      <ToolContent>
        <ToolInput input={call.input} />
        <ToolOutput output={call.state === "ok" ? call.output : null} errorText={call.state === "error" ? call.output || "falhou" : null} />
      </ToolContent>
    </Tool>
  );
}

/** Raciocínio e ferramentas do turno atual (eventos do monitor com o `run_id` do turno). */
export function TurnActivity({ reasoning, tools }: { reasoning: TurnReasoning | null; tools: TurnToolCall[] }) {
  if (!reasoning && !tools.length) return null;
  return (
    <div className="flex w-full max-w-[92%] flex-col gap-2" data-testid="turn-activity">
      {reasoning ? <TurnReasoningBlock reasoning={reasoning} /> : null}
      {tools.map((call) => (
        <TurnTool key={call.id} call={call} />
      ))}
    </div>
  );
}
