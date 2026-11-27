import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { EventsProvider, useEvents } from "./use-events";
import type { AuditEvent } from "@/lib/monitor-core";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, ((e: unknown) => void)[]>();
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: unknown) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data?: unknown) {
    for (const fn of this.listeners.get(type) ?? []) fn(data === undefined ? {} : { data: JSON.stringify(data) });
  }
}

const catalog = { kinds: {}, phases: { "turn/start": "routing", "turn/done": "idle" }, labels: {} };
const ev = (id: number, kind: string, status: string): AuditEvent => ({
  id, at: "2026-11-27T10:00:00+00:00", kind, name: kind, status, detail: {}, run_id: "r1", duration_ms: null,
});

function Probe() {
  const { state, connected } = useEvents();
  return <p data-testid="out">{`${connected ? "on" : "off"}|${state.phase}|${state.lastId}`}</p>;
}

const out = () => screen.getByTestId("out").textContent;
const last = () => FakeEventSource.instances[FakeEventSource.instances.length - 1];

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(catalog), { status: 200 })));
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("carrega o catálogo, aplica eventos e reconecta com after=<último id>", async () => {
  render(<EventsProvider><Probe /></EventsProvider>);
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
  expect(last().url).toBe("/api/events/stream");

  act(() => last().emit("open"));
  act(() => last().emit("audit", ev(1, "turn", "start")));
  expect(out()).toBe("on|routing|1");

  // A conexão cai no meio do turno: aparece desconectado e o estado não muda sozinho.
  const first = last();
  act(() => first.emit("error"));
  expect(first.closed).toBe(true);
  expect(out()).toBe("off|routing|1");

  await act(async () => {
    await vi.advanceTimersByTimeAsync(600);
  });
  expect(FakeEventSource.instances).toHaveLength(2);
  expect(last().url).toBe("/api/events/stream?after=1");

  // O servidor reenvia o que faltou: o turno fecha e a fase volta a "idle".
  act(() => last().emit("open"));
  act(() => last().emit("audit", ev(2, "turn", "done")));
  expect(out()).toBe("on|idle|2");
});

test("o backoff cresce até 5 s e zera quando reconecta", async () => {
  render(<EventsProvider><Probe /></EventsProvider>);
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
  const wait = async (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

  for (const expected of [500, 1000, 2000, 4000, 5000, 5000]) {
    const count = FakeEventSource.instances.length;
    act(() => last().emit("error"));
    await wait(expected - 1);
    expect(FakeEventSource.instances).toHaveLength(count);
    await wait(1);
    expect(FakeEventSource.instances).toHaveLength(count + 1);
  }

  act(() => last().emit("open"));
  const count = FakeEventSource.instances.length;
  act(() => last().emit("error"));
  await wait(500);
  expect(FakeEventSource.instances).toHaveLength(count + 1);
});

test("ao desmontar fecha a conexão e não reconecta", async () => {
  const { unmount } = render(<EventsProvider><Probe /></EventsProvider>);
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
  const source = last();
  unmount();
  expect(source.closed).toBe(true);
  await vi.advanceTimersByTimeAsync(6000);
  expect(FakeEventSource.instances).toHaveLength(1);
});
