<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { call } from "../lib/api";
  import { toast, errorText } from "../lib/stores";
  import { copyText } from "../lib/clipboard";
  import ActionButton from "../lib/ActionButton.svelte";
  import Value from "../lib/Value.svelte";

  let status = $state<any[]>([]);
  let collect = $state<any>(null);
  let paste = $state("");
  let pasteResult = $state<any>(null);
  let script = $state<any>(null);
  let hours = $state(24);
  let timer: ReturnType<typeof setInterval> | null = null;

  async function loadStatus() {
    status = await call("troops_status", { hours });
  }

  onMount(async () => {
    try {
      await loadStatus();
      const s = await call("troops_collect_status");
      if (s?.laeuft) {
        collect = s;
        poll();
      }
    } catch (e) {
      toast(errorText(e), "error");
    }
  });

  onDestroy(() => timer && clearInterval(timer));

  function poll() {
    if (timer) clearInterval(timer);
    timer = setInterval(async () => {
      try {
        collect = await call("troops_collect_status");
        if (!collect?.laeuft) {
          clearInterval(timer!);
          timer = null;
          await loadStatus();
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
  }

  async function startCollect() {
    collect = await call("troops_collect_start", { minutes: 30 });
    poll();
  }

  async function stopCollect() {
    collect = await call("troops_collect_stop");
    if (timer) clearInterval(timer);
    timer = null;
    await loadStatus();
  }

  async function importPaste() {
    pasteResult = await call("import_troops", { text: paste });
    paste = "";
    await loadStatus();
  }

  const done = $derived(status.filter((p) => p.done).length);
</script>

<h1>Truppen</h1>

<div class="card">
  <h2>Stand pro Spieler</h2>
  <div class="row">
    <label class="inline">Daten jünger als <input type="number" min="1" style="width: 5rem" bind:value={hours} /> Stunden</label>
    <ActionButton label="Aktualisieren" run={loadStatus} />
    <span class="muted">{done} von {status.length} Spielern vollständig</span>
  </div>
  <table style="margin-top: 0.75rem">
    <thead><tr><th>Spieler</th><th>Dörfer</th><th>Aktuell</th><th></th></tr></thead>
    <tbody>
      {#each status as p}
        <tr>
          <td>{p.player}</td>
          <td>{p.villages}</td>
          <td>{p.fresh}</td>
          <td><span class="pill {p.done ? 'ok' : 'warn'}">{p.done ? "fertig" : "fehlt"}</span></td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<div class="card">
  <h2>Mit einem Klick: Truppen-Skript</h2>
  <p>
    Das Skript liest im Spiel auf <b>Stamm → Mitglieder → Truppen</b> nacheinander alle Mitglieder,
    die ihre Truppen mit dem Stamm teilen. Es liest nur, schickt nichts an fremde Server und lädt
    keinen Code nach. Den Text am Ende kopieren, während unten der Sammel-Modus läuft, oder
    unten einfügen.
  </p>
  {#if !script}
    <ActionButton label="Skript anzeigen" run={async () => (script = await call("truppen_skript"))} />
  {:else}
    <ol>
      {#each script.schritte as step}<li>{step}</li>{/each}
    </ol>
    <p class="msg-warn">{script.hinweis}</p>
    <div class="row">
      <ActionButton label="Zeile für die Schnellleiste kopieren" primary run={() => copyText(script.schnellleiste)} done="Kopiert." />
      <span class="muted">Version {script.version}</span>
    </div>
  {/if}
</div>

<div class="card">
  <h2>Sammel-Modus (Zwischenablage)</h2>
  <p>
    Starten, dann im Spiel jede Truppen-Seite mit <b>Strg+A</b>, <b>Strg+C</b> kopieren (oder den
    Export des Skripts kopieren). Jede Kopie wird sofort eingelesen.
  </p>
  <div class="row">
    {#if collect?.laeuft}
      <ActionButton label="Fertig" primary run={stopCollect} done="Sammeln beendet." />
      <span class="pill ok">läuft</span>
    {:else}
      <ActionButton label="Sammeln starten" primary run={startCollect} />
    {/if}
  </div>
  {#if collect}<div style="margin-top: 1rem"><Value value={collect} /></div>{/if}
</div>

<div class="card">
  <h2>Text einfügen</h2>
  <textarea bind:value={paste} placeholder="Kopierte Truppen-Tabelle(n) oder Skript-Export hier einfügen"></textarea>
  <ActionButton label="Einlesen" primary run={importPaste} disabled={!paste.trim()} done="Truppen eingelesen." />
  {#if pasteResult}<div style="margin-top: 1rem"><Value value={pasteResult} /></div>{/if}
</div>
