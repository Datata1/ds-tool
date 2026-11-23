<script lang="ts">
  // One outward step (DS Ultimate, Discord): first a preview, then an explicit "send" click.
  import { call } from "./api";
  import { toast, errorText } from "./stores";
  import Value from "./Value.svelte";

  let {
    title,
    description,
    usecase,
    args,
    confirmLabel = "Jetzt senden",
    onDone = () => {},
  }: {
    title: string;
    description: string;
    usecase: string;
    args: Record<string, unknown>;
    confirmLabel?: string;
    onDone?: () => void;
  } = $props();

  let preview = $state<any>(null);
  let result = $state<any>(null);
  let busy = $state(false);

  async function run(confirm: boolean) {
    busy = true;
    try {
      const r = await call(usecase, { ...args, bestaetigt: confirm });
      if (confirm) {
        result = r;
        preview = null;
        toast(`${title}: erledigt.`, "ok");
        onDone();
      } else {
        preview = r;
        result = null;
      }
    } catch (e) {
      toast(errorText(e), "error");
    } finally {
      busy = false;
    }
  }

  const canSend = $derived(
    preview &&
      (preview.vorschau?.length ?? preview.wuerde_erinnern?.length ?? 0) > 0 &&
      !/schon|Niemand/.test(preview.hinweis ?? ""),
  );
</script>

<div class="card">
  <h2 style="margin-top: 0">{title}</h2>
  <p class="muted">{description}</p>
  <div class="row">
    <button disabled={busy} onclick={() => run(false)}>{busy ? "Bitte warten …" : "Vorschau"}</button>
    {#if canSend}
      <button class="primary" disabled={busy} onclick={() => run(true)}>{confirmLabel}</button>
    {/if}
  </div>
  {#if preview}<div style="margin-top: 0.75rem"><Value value={preview} /></div>{/if}
  {#if result}<div style="margin-top: 0.75rem"><Value value={result} /></div>{/if}
</div>
