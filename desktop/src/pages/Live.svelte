<script lang="ts">
  import { call } from "../lib/api";
  import { page } from "../lib/stores";
  import ActionButton from "../lib/ActionButton.svelte";
  import PreviewStep from "../lib/PreviewStep.svelte";

  let { op }: { op: string } = $props();

  let progress = $state<any>(null);
  let returnsMd = $state("");
  let minutes = $state(15);
</script>

<div class="row" style="justify-content: space-between">
  <h1>Laufend: {op}</h1>
  <button onclick={() => page.set({ name: "publish", op })}>Zurück</button>
</div>

<div class="card">
  <h2 style="margin-top: 0">Wer hat schon geschickt?</h2>
  <p class="muted">Zählt, was die Spieler in DS Ultimate als „verschickt“ abhaken (braucht den DS-Ultimate-API-Key).</p>
  <ActionButton label="Stand laden" primary run={async () => (progress = await call("dsu_progress", { name: op }))} />
  {#if progress}
    <p><b>{progress.gesamt}</b></p>
    <table>
      <thead><tr><th>Spieler</th><th>Abgehakt</th><th>Überfällig</th><th>Nächster Befehl</th></tr></thead>
      <tbody>
        {#each progress.spieler as p}
          <tr>
            <td>{p.spieler}</td>
            <td>{p.abgehakt}</td>
            <td class:msg-error={p.ueberfaellig.length}>{p.ueberfaellig.join(", ") || "–"}</td>
            <td class="muted">{p.naechster ?? "–"}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#each progress.hinweise as h}<p class="msg-warn">{h}</p>{/each}
  {/if}
</div>

<div class="card">
  <label class="inline">Erinnern, wer in den nächsten <input type="number" min="1" style="width: 5rem" bind:value={minutes} /> Minuten schicken muss oder überfällig ist</label>
</div>
{#key minutes}
  <PreviewStep
    title="Erinnerung schicken"
    description="Kurze Nachricht in den privaten Thread (bzw. als Direktnachricht) an alle, die noch nicht abgehakt haben."
    usecase="discord_remind"
    args={{ name: op, minuten: minutes }}
    confirmLabel="Erinnerungen senden"
  />
{/key}

<div class="card">
  <h2 style="margin-top: 0">Rückkehrzeiten</h2>
  <ActionButton label="Anzeigen" run={async () => (returnsMd = await call("returns", { name: op }))} />
  {#if returnsMd}<pre>{returnsMd}</pre>{/if}
</div>
