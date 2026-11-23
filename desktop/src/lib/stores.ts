import { writable } from "svelte/store";

export type Page =
  | { name: "start" }
  | { name: "setup" }
  | { name: "troops" }
  | { name: "ops" }
  | { name: "form"; op: string | null }
  | { name: "result"; op: string }
  | { name: "publish"; op: string }
  | { name: "live"; op: string };

export const page = writable<Page>({ name: "start" });

export type Toast = { id: number; kind: "ok" | "error" | "info"; text: string };
export const toasts = writable<Toast[]>([]);
let nextId = 1;

export function toast(text: string, kind: Toast["kind"] = "info"): void {
  const id = nextId++;
  toasts.update((t) => [...t, { id, kind, text }]);
  setTimeout(() => toasts.update((t) => t.filter((x) => x.id !== id)), kind === "error" ? 9000 : 4000);
}

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
