import { expect, test } from "vitest";
import { invalidatesAppState } from "./use-app-state";
import type { AuditEvent } from "@/lib/monitor-core";

const ev = (kind: string, status: string): AuditEvent => ({
  id: 1, at: "", kind, name: kind, status, detail: {}, run_id: null, duration_ms: null,
});

test("invalida o estado em turn done/error, confirmation e reminder", () => {
  expect(invalidatesAppState(ev("turn", "done"))).toBe(true);
  expect(invalidatesAppState(ev("turn", "error"))).toBe(true);
  expect(invalidatesAppState(ev("confirmation", "requested"))).toBe(true);
  expect(invalidatesAppState(ev("reminder", "delivered"))).toBe(true);
  expect(invalidatesAppState(ev("turn", "start"))).toBe(false);
  expect(invalidatesAppState(ev("llm", "done"))).toBe(false);
});
