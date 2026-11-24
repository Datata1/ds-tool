<script lang="ts">
  import { call } from "../../lib/api";
  import ActionButton from "../../lib/ActionButton.svelte";

  let { op, status, refresh }: { op: string; status: any; refresh: () => void } = $props();

  let note = $state("");
  const approved = $derived(status.status === "approved");

  async function set(s: string) {
    await call("set_status", { name: op, status: s, note: note || null });
    note = "";
    refresh();
  }
</script>

<div class="card">
  {#if approved}
    <p><span class="pill ok">Von der SF freigegeben</span></p>
    <p>Weiter mit „An Spieler“: Spieler-Pläne, Befehle und Ankündigung.</p>
    <ActionButton label="Freigabe zurücknehmen" run={() => set("in_review")} />
  {:else}
    <p>Hat die SF den Plan geprüft und ist einverstanden? Änderungswünsche: zurück zu „Planen“, neu rechnen – Pläne, Doc und Review werden dann aktualisiert.</p>
    <label>Notiz (optional)<input bind:value={note} placeholder="z.B. OK von Graf, Fakes auf 494|502 verdoppelt" /></label>
    <div class="row" style="margin-top: 0.75rem">
      <ActionButton label="Plan freigeben" primary run={() => set("approved")} done="Freigegeben." />
    </div>
  {/if}
</div>
