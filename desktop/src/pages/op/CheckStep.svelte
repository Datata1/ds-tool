<script lang="ts">
  import GameLink from "../../lib/GameLink.svelte";
  import { onMount } from "svelte";
  import { call } from "../../lib/api";
  import { toast, errorText } from "../../lib/stores";
  import ActionButton from "../../lib/ActionButton.svelte";

  let { op, planned, onSolved }: { op: string; planned: boolean; onSolved: () => void | Promise<void> } = $props();

  let check = $state<any>(null);
  let data = $state<any>(null);
  let open = $state<Record<string, boolean>>({});
  let filter = $state("");

  async function load() {
    [check, data] = await Promise.all([
      call("check_report", { name: op }),
      call("plan_commands", { name: op }),
    ]);
  }

  onMount(() => {
    if (planned) load().catch((e) => toast(errorText(e), "error"));
  });

  async function solve() {
    await call("solve_operation", { name: op });
    await load();
    onSolved();
  }

  const hints = $derived([...new Set([...(check?.hinweise ?? []), ...(data?.warnungen ?? [])])]);
  const KINDS = ["Off", "AG", "Fake", "Fake-AG", "Unterst."];

  function cell(z: any, k: string): { text: string; cls: string } {
    const want = z.soll[k];
    const have = z.ist[k] ?? 0;
    if (typeof want === "string") return { text: have ? `${have} Befehle` : "fehlt", cls: have ? "ok" : "error" };
    if (!want && !have) return { text: "", cls: "" };
    if (!want) return { text: `${have}`, cls: "" };
    return { text: `${have} / ${want}`, cls: have >= want ? "ok" : "warn" };
  }

  const rows = $derived(
    (data?.befehle ?? []).filter((c: any) => !filter || Object.values(c).join(" ").toLowerCase().includes(filter.toLowerCase())),
  );
</script>

{#if !planned}
  <div class="card">
    <p>Die Operation ist noch nicht (oder nicht mehr aktuell) gerechnet.</p>
    <ActionButton label="Jetzt rechnen" primary run={solve} done="Gerechnet." />
  </div>
{:else if !check || !data}
  <p class="muted">Lade …</p>
{:else}
  <div class="card">
    <div class="row" style="justify-content: space-between">
      <div class="row">
        {#if check.fehler.length}
          <span class="pill error">{check.fehler.length} Fehler</span>
        {:else}
          <span class="pill ok">Keine Fehler</span>
        {/if}
        <span class="pill {hints.length ? 'warn' : ''}">{hints.length} Hinweise</span>
        <span class="pill">{data.befehle.length} Befehle</span>
      </div>
      <ActionButton label="Neu rechnen" run={solve} done="Neu gerechnet." />
    </div>
    {#if data.befehle.length === 0}
      <p class="msg-error" style="margin-bottom: 0">
        <b>Der Plan ist leer</b> – es gibt nichts für DS Ultimate oder die Spieler. Warum, steht unten bei den Hinweisen
        (oft: Ankunft so früh, dass die Dörfer außerhalb des Abschickfensters losschicken müssten). In Schritt 1 Ankunft
        oder Abschickfenster ändern und neu rechnen.
      </p>
    {/if}
    {#if check.fehler.length}
      <h3 class="msg-error">Fehler – vor dem Review beheben</h3>
      <ul class="plain">{#each check.fehler.slice(0, 5) as e}<li>{e}</li>{/each}</ul>
      {#if check.fehler.length > 5}
        <details>
          <summary>{check.fehler.length - 5} weitere Fehler</summary>
          <ul class="plain">{#each check.fehler.slice(5) as e}<li>{e}</li>{/each}</ul>
        </details>
      {/if}
      <p class="hint">Fehler beheben: Schritt „Planen“ öffnen, anpassen (z.B. Ankunft, Ziele), dann neu rechnen. „Weiter“ geht erst ohne Fehler.</p>
    {/if}
  </div>

  <div class="card">
    <h2 style="margin-top: 0">Ziele: gewünscht und geplant</h2>
    <table>
      <thead>
        <tr><th>Ziel</th><th>Ankunft</th>{#each KINDS as k}<th>{k === "Unterst." ? "Flexdeff" : k}</th>{/each}<th></th></tr>
      </thead>
      <tbody>
        {#each data.ziele as z}
          <tr>
            <td><b><GameLink dorf={z.coord} /></b> {z.dorf}<div class="hint"><GameLink spieler={z.besitzer} />{z.wing ? ` · ${z.wing} Wing-Befehle` : ""}</div></td>
            <td>{z.ankunft ?? "–"}</td>
            {#each KINDS as k}
              {@const c = cell(z, k)}
              <td>{#if c.text}<span class="pill {c.cls}">{c.text}</span>{/if}</td>
            {/each}
            <td><button onclick={() => (open[z.coord] = !open[z.coord])}>{open[z.coord] ? "Zu" : "Befehle"}</button></td>
          </tr>
          {#if open[z.coord]}
            <tr>
              <td colspan={KINDS.length + 3}>
                <table>
                  <thead><tr><th>Abschicken</th><th>Ankunft</th><th>Spieler</th><th>Von</th><th>Art</th><th>Einheiten</th></tr></thead>
                  <tbody>
                    {#each z.befehle as c}
                      <tr><td>{c.abschicken}</td><td>{c.ankunft}</td><td><GameLink spieler={c.spieler} /></td><td><GameLink dorf={c.von} /></td><td>{c.art}</td><td class="muted">{c.einheiten}</td></tr>
                    {/each}
                  </tbody>
                </table>
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  </div>

  {#if hints.length}
    <details class="card" open={hints.length <= 6}>
      <summary>Hinweise ({hints.length})</summary>
      <ul class="plain">{#each hints as w}<li>{w}</li>{/each}</ul>
    </details>
  {/if}

  {#if check.freie_truppen.length}
    <details class="card">
      <summary>Freie Truppen nach diesem Plan ({check.freie_truppen.length} Dörfer)</summary>
      <p class="hint">Plätze = Einwohner der Off- bzw. Deff-Einheiten, die nach diesem Plan noch nicht verplant sind.</p>
      <ul class="plain">{#each check.freie_truppen as f}<li>{f}</li>{/each}</ul>
    </details>
  {/if}

  <details class="card">
    <summary>Alle Befehle nach Abschickzeit ({data.befehle.length})</summary>
    <input placeholder="Filtern (Spieler, Koordinate …)" bind:value={filter} style="margin: 0.5rem 0" />
    <table>
      <thead><tr><th>Abschicken</th><th>Ankunft</th><th>Spieler</th><th>Von</th><th>Nach</th><th>Art</th><th>Einheiten</th></tr></thead>
      <tbody>
        {#each rows as c}
          <tr>
            <td>{c.abschicken}</td><td>{c.ankunft}</td>
            <td><GameLink spieler={c.spieler} />{#if c.wer !== "Main"} <span class="muted">({c.wer})</span>{/if}</td>
            <td><GameLink dorf={c.von} /></td><td><GameLink dorf={c.nach} /></td><td>{c.art}</td><td class="muted">{c.einheiten}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </details>
{/if}
