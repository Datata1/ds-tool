// Talks to the Python API (ap-planner-server). In the desktop app Tauri tells us URL and
// token of the sidecar; in the browser (Docker, dev) the API is on the same origin.

type Backend = { url: string; token: string };

let backendPromise: Promise<Backend> | null = null;

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function backend(): Promise<Backend> {
  if (!backendPromise) {
    backendPromise = (async () => {
      if (isTauri()) {
        const { invoke } = await import("@tauri-apps/api/core");
        return await invoke<Backend>("backend");
      }
      return { url: "", token: "" };
    })();
  }
  return backendPromise;
}

export class ApiError extends Error {}

async function request(path: string, init: RequestInit = {}): Promise<any> {
  const b = await backend();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (b.token) headers.Authorization = `Bearer ${b.token}`;
  let res: Response;
  try {
    res = await fetch(`${b.url}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("Der Planer-Dienst ist nicht erreichbar. App neu starten.");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(body.error ?? `Fehler ${res.status}`);
  }
  return body;
}

/** Call a use case of the planner (same functions Claude uses as tools). */
export async function call<T = any>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  const body = await request(`/api/call/${name}`, { method: "POST", body: JSON.stringify(args) });
  const result = body.result;
  if (result && typeof result === "object" && !Array.isArray(result) && "error" in result) {
    throw new ApiError(String(result.error));
  }
  return result as T;
}

export async function health(): Promise<{ ok: boolean; version: string }> {
  return request("/api/health");
}
