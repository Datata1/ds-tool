<script lang="ts">
  import { onMount } from "svelte";
  import { call } from "../lib/api";
  import { page, errorText } from "../lib/stores";

  let data = $state<any>(null);
  let error = $state("");

  onMount(async () => {
    try {
      data = await call("overview");
    } catch (err) {
      error = errorText(err);
    }
  });

  const statusLabel: Record<string, string> = {
    draft: "Entwurf",
    in_review: "Im Review",
    approved: "Freigegeben",
  };
</script>

<h1>Übersicht</h1>
{#if error}
  <div class="card msg-error">{error}</div>
{:else if !data}
  <p class="muted">Lade …</p>
{:else if !data.welt}
  <div class="card">
    <h2>Willkommen!</h2>
    <p>Noch ist keine Welt eingerichtet. Das dauert nur eine Minute.</p>
    <button class="primary" onclick={() => page.set({ name: "setup" })}>Jetzt einrichten</button>
  </div>
{:else}
  <div class="grid">
    <div class="card">
      <div class="muted">Welt</div>
      <h2 style="margin: 0.25rem 0">{data.welt}</h2>
    </div>
    <div class="card">
      <div class="muted">Truppen</div>
      <h2 style="margin: 0.25rem 0">{data.truppen_doerfer ?? 0} Dörfer</h2>
      <div class="muted">{data.truppen_stand ? `Stand ${data.truppen_stand}` : "noch keine"}</div>
    </div>
    <div class="card">
      <div class="muted">Operationen</div>
      <h2 style="margin: 0.25rem 0">{data.operationen_anzahl ?? 0}</h2>
    </div>
  </div>

  {#if data.naechster_schritt}
    <div class="card"><b>Nächster Schritt:</b> {data.naechster_schritt}</div>
  {/if}

  <div class="card">
    <div class="row" style="justify-content: space-between">
      <h2 style="margin: 0">Neueste Operationen</h2>
      <button class="primary" onclick={() => page.set({ name: "op", op: null })}>Neue Operation</button>
    </div>
    {#if (data.neueste_operationen ?? []).length === 0}
      <p class="muted">Noch keine Operation geplant.</p>
    {:else}
      <table>
        <thead><tr><th>Name</th><th>Ankunft</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {#each data.neueste_operationen as op}
            <tr>
              <td>{op.title}</td>
              <td>{new Date(op.arrival).toLocaleString("de-DE")}</td>
              <td><span class="pill">{statusLabel[op.status] ?? op.status}</span></td>
              <td><button onclick={() => page.set({ name: "op", op: op.name })}>Öffnen</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
{/if}
