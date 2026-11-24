<script lang="ts">
  // One outward step (DS Ultimate, Discord): first a preview, then an explicit "send" click.
  import { call } from "./api";
  import { toast, errorText } from "./stores";
  import Value from "./Value.svelte";
  import StateBadge from "./StateBadge.svelte";

  let {
    title,
    description,
    usecase,
    args,
    confirmLabel = "Jetzt senden",
    stepState = "",
    waitHint = "",
    onDone = () => {},
    children,
  }: {
    title: string;
    description: string;
    usecase: string;
    args: Record<string, unknown>;
    confirmLabel?: string;
    stepState?: string;
    waitHint?: string;
    onDone?: () => void;
    children?: import("svelte").Snippet;
  } = $props();

  let preview = $state<any>(null);
  let result = $state<any>(null);
  let busy = $state<"" | "preview" | "send">("");

  async function run(confirm: boolean) {
    busy = confirm ? "send" : "preview";
    try {
      const r = await call(usecase, { ...args, bestaetigt: confirm });
      if (confirm) {
        result = r;
        preview = null;
        toast(`${title}: erledigt.`, "ok");
      } else {
        preview = r;
        result = null;
      }
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      busy = "";
      if (confirm) onDone();
    }
  }

  const canSend = $derived(
    preview &&
      (preview.vorschau?.length ?? preview.wuerde_erinnern?.length ?? 0) > 0 &&
      !/schon|Niemand/.test(preview.hinweis ?? ""),
  );
  // the API's hint talks to Claude ("bestaetigt=true"); the buttons say it better here
  const shown = $derived(
    preview ? Object.fromEntries(Object.entries(preview).filter(([k]) => k !== "hinweis" || !canSend)) : null,
  );
</script>

<div class="card">
  <div class="row" style="justify-content: space-between">
    <h2 style="margin: 0">{title}</h2>
    {#if stepState}<StateBadge state={stepState} />{/if}
  </div>
  <p class="muted">{description}</p>
  <div class="row">
    <button disabled={!!busy} onclick={() => run(false)}>{busy === "preview" ? "Lade Vorschau …" : "Vorschau"}</button>
    {#if canSend}
      <button class="primary" disabled={!!busy} onclick={() => run(true)}>{busy === "send" ? "Läuft …" : confirmLabel}</button>
    {/if}
  </div>
  {#if busy === "send" && waitHint}<p class="hint">{waitHint}</p>{/if}
  {#if children}<div style="margin-top: 0.75rem">{@render children()}</div>{/if}
  {#if shown}<div style="margin-top: 0.75rem"><Value value={shown} /></div>{/if}
  {#if result}<div style="margin-top: 0.75rem"><Value value={result} /></div>{/if}
</div>
