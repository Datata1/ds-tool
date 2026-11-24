// Things only the desktop shell can do (Tauri). In the browser (Docker/dev) there are fallbacks.

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Open a web link in the player's normal browser. */
export async function openExternal(url: string): Promise<void> {
  if (isTauri()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
  } else {
    window.open(url, "_blank", "noopener");
  }
}

/** Links in the app (<a href="https://…">) always open in the real browser. */
export function interceptLinks(): () => void {
  const handler = (event: MouseEvent) => {
    const a = (event.target as HTMLElement | null)?.closest?.("a");
    const href = a?.getAttribute("href") ?? "";
    if (/^https?:\/\//.test(href)) {
      event.preventDefault();
      openExternal(href);
    }
  };
  document.addEventListener("click", handler);
  return () => document.removeEventListener("click", handler);
}

export type FolderInfo = { current: string; default: string };

export async function getDataFolder(): Promise<FolderInfo | null> {
  if (!isTauri()) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<FolderInfo>("get_data_folder");
}

export async function setDataFolder(path: string): Promise<void> {
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("set_data_folder", { path });
}
