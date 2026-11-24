<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import GameLink from "../../lib/GameLink.svelte";
  import { toast, errorText } from "../../lib/stores";
  import { call } from "../../lib/api";
  import ActionButton from "../../lib/ActionButton.svelte";
  import PreviewStep from "../../lib/PreviewStep.svelte";

  let { op }: { op: string } = $props();

  let progress = $state<any>(null);
  let returnsRows = $state<any[] | null>(null);
  let returnsFilter = $state("");
  let minutes = $state(15);
  let auto = $state<any>({ laeuft: false });
  let intervall = $state(2);
  let timer: ReturnType<typeof setInterval> | null = null;

  async function loadAuto() {
    try {
      auto = await call("auto_erinnern_status", { name: op });
    } catch (e) {
      toast(errorText(e), "error");
    }
  }
  onMount(() => {
    loadAuto();
    timer = setInterval(loadAuto, 10_000);
  });
  onDestroy(() => timer && clearInterval(timer));
</script>

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
            <td><GameLink spieler={p.spieler} /></td>
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
  <label class="inline">Erinnern, wer in den nächsten <input type="number" min="1" style="width: 5rem" bind:value={minutes} /> Minuten schicken muss (Überfälliges wird nie gemeldet)</label>
</div>
<div class="card">
  <div class="row" style="justify-content: space-between">
    <h2 style="margin: 0">Automatisch erinnern</h2>
    {#if auto.laeuft}<span class="pill ok">läuft seit {auto.seit}</span>{:else}<span class="pill">aus</span>{/if}
  </div>
  <p class="muted">
    Prüft regelmäßig den Stand in DS Ultimate und schreibt jedem, der in den nächsten {minutes} Minuten schicken muss
    und noch nicht abgehakt hat. Jeder Befehl wird nur einmal gemeldet, Überfälliges gar nicht.
    <b>Läuft nur, solange diese App offen ist</b> (PC an, App nicht geschlossen). Was schon gesendet ist, bleibt in Discord.
  </p>
  <div class="row">
    {#if auto.laeuft}
      <ActionButton label="Automatik stoppen" danger run={async () => (auto = await call("auto_erinnern_stop", { name: op }))} />
      <span class="muted">alle {auto.intervall_min} Min. · letzte Prüfung {auto.letzte_pruefung ?? "–"} · nächste {auto.naechste_pruefung ?? "gleich"}</span>
    {:else}
      <label class="inline">alle <input type="number" min="1" style="width: 4.5rem" bind:value={intervall} /> Minuten prüfen</label>
      <ActionButton
        label="Automatik starten"
        primary
        run={async () => (auto = await call("auto_erinnern_start", { name: op, minuten: Number(minutes) || 15, intervall_min: Number(intervall) || 2 }))}
      />
      {#if auto.gestoppt}<span class="muted">zuletzt: {auto.gestoppt}</span>{/if}
    {/if}
  </div>
  {#if auto.protokoll?.length}
    <details style="margin-top: 0.75rem" open={auto.laeuft}>
      <summary>Protokoll ({auto.protokoll.length})</summary>
      <ul class="plain">{#each auto.protokoll as line}<li class:msg-error={line.includes("Fehler")}>{line}</li>{/each}</ul>
    </details>
  {/if}
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
  <div class="row" style="justify-content: space-between">
    <h2 style="margin: 0">Rückkehrzeiten</h2>
    {#if returnsRows}
      <button onclick={() => (returnsRows = null)}>Ausblenden</button>
    {:else}
      <ActionButton label="Anzeigen" run={async () => (returnsRows = await call("returns_table", { name: op }))} />
    {/if}
  </div>
  {#if returnsRows}
    <p class="hint">Nach Rückkehr sortiert (alle Überlebenden daheim). „Frühestens“ = falls die langsamen Einheiten (Rammen, AG) sterben.</p>
    <input placeholder="Filtern (Spieler, Dorf …)" bind:value={returnsFilter} style="margin-bottom: 0.5rem" />
    <div style="max-height: 60vh; overflow-y: auto">
      <table style="font-size: 0.85rem">
        <thead><tr><th>Zurück</th><th>Frühestens</th><th>Spieler</th><th>Dorf</th><th>Was</th><th>Ziel</th><th>Einschlag</th><th>Einheiten</th></tr></thead>
        <tbody>
          {#each returnsRows.filter((r) => !returnsFilter || `${r.spieler} ${r.dorf} ${r.ziel}`.toLowerCase().includes(returnsFilter.toLowerCase())) as r}
            <tr>
              <td><b>{r.zurueck ?? "bleibt dort"}</b></td>
              <td class="muted">{r.fruehestens ?? ""}</td>
              <td><GameLink spieler={r.spieler} /></td>
              <td><GameLink dorf={r.dorf} /></td>
              <td>{r.was}</td>
              <td><GameLink dorf={r.ziel} /></td>
              <td class="muted">{r.einschlag}</td>
              <td>
                {#each Object.entries(r.einheiten) as [u, n]}
                  <span class="unit"><img src={`/units/${u}.png`} alt={u} width="14" height="14" />{n}</span>
                {/each}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .unit { display: inline-flex; align-items: center; gap: 2px; margin-right: 6px; white-space: nowrap; }
</style>
