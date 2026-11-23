<script lang="ts">
  import { onMount } from "svelte";
  import { call } from "../lib/api";
  import { page, toast, errorText } from "../lib/stores";
  import ActionButton from "../lib/ActionButton.svelte";

  let { op }: { op: string } = $props();

  let check = $state<any>(null);
  let cmds = $state<any>(null);
  let solved = $state<any>(null);
  let filter = $state("");
  let showReview = $state(false);

  async function load() {
    check = await call("check_report", { name: op });
    cmds = await call("plan_commands", { name: op });
  }

  let needsSolve = $state(false);

  onMount(async () => {
    try {
      const info = await call("get_operation", { name: op });
      needsSolve = info.plan_veraltet;
      if (!needsSolve) await load();
    } catch (e) {
      toast(errorText(e), "error");
    }
  });

  async function solve() {
    solved = await call("solve_operation", { name: op });
    needsSolve = false;
    await load();
    if (solved?.google_doc?.status && solved.google_doc.status !== "aktuell") {
      toast("Plan geändert – das Google Doc unter „Veröffentlichen“ aktualisieren.", "info");
    }
  }

  const visible = $derived(
    (cmds?.befehle ?? []).filter((c: any) =>
      !filter || Object.values(c).join(" ").toLowerCase().includes(filter.toLowerCase()),
    ),
  );
</script>

<div class="row" style="justify-content: space-between">
  <h1>Ergebnis: {op}</h1>
  <div class="row">
    <button onclick={() => page.set({ name: "form", op })}>Bearbeiten</button>
    <ActionButton label="Neu rechnen" run={solve} done="Neu gerechnet." />
    <button class="primary" onclick={() => page.set({ name: "publish", op })}>Weiter: Veröffentlichen</button>
  </div>
</div>

{#if needsSolve}
  <div class="card">
    <p>Diese Operation ist noch nicht (neu) gerechnet.</p>
    <ActionButton label="Jetzt rechnen" primary run={solve} done="Gerechnet." />
  </div>
{:else if !check}
  <div class="card"><p class="muted">Lade …</p></div>
{:else}
  <div class="card">
    <h2 style="margin-top: 0">
      {#if check.fehler.length}
        <span class="pill error">{check.fehler.length} Fehler</span>
      {:else}
        <span class="pill ok">Keine Fehler</span>
      {/if}
      <span class="pill warn">{check.hinweise.length} Hinweise</span>
      <span class="pill">{cmds?.befehle.length ?? 0} Befehle</span>
    </h2>
    {#if check.fehler.length}
      <h3 class="msg-error">Fehler (müssen behoben werden)</h3>
      <ul class="plain">{#each check.fehler as e}<li>{e}</li>{/each}</ul>
    {/if}
    {#if check.hinweise.length || (cmds?.warnungen ?? []).length}
      <h3>Hinweise</h3>
      <ul class="plain">
        {#each check.hinweise as w}<li>{w}</li>{/each}
        {#each cmds?.warnungen ?? [] as w}<li>{w}</li>{/each}
      </ul>
    {/if}
    {#if check.freie_truppen.length}
      <h3>Freie Truppen nach diesem Plan</h3>
      <ul class="plain">{#each check.freie_truppen as f}<li>{f}</li>{/each}</ul>
    {/if}
    {#if solved?.review_md}
      <button style="margin-top: 0.75rem" onclick={() => (showReview = !showReview)}>
        {showReview ? "Zusammenfassung ausblenden" : "Zusammenfassung pro Ziel"}
      </button>
      {#if showReview}<pre>{solved.review_md}</pre>{/if}
    {/if}
  </div>

  <div class="card">
    <div class="row" style="justify-content: space-between">
      <h2 style="margin: 0">Befehle</h2>
      <input placeholder="Filtern (Spieler, Koordinate …)" bind:value={filter} />
    </div>
    <table style="margin-top: 0.75rem">
      <thead>
        <tr><th>Abschicken</th><th>Ankunft</th><th>Spieler</th><th>Von</th><th>Nach</th><th>Art</th><th>Einheiten</th></tr>
      </thead>
      <tbody>
        {#each visible as c}
          <tr>
            <td>{c.abschicken}</td>
            <td>{c.ankunft}</td>
            <td>{c.spieler}{#if c.wer !== "Main"} <span class="muted">({c.wer})</span>{/if}</td>
            <td>{c.von}</td>
            <td>{c.nach}</td>
            <td>{c.art}</td>
            <td class="muted">{c.einheiten}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}
