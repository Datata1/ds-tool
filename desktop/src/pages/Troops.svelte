<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { call } from "../lib/api";
  import { toast, errorText } from "../lib/stores";
  import { copyText } from "../lib/clipboard";
  import ActionButton from "../lib/ActionButton.svelte";
  import Value from "../lib/Value.svelte";
  import GameLink from "../lib/GameLink.svelte";

  type Row = {
    player: string;
    coord: string;
    name: string;
    units: Record<string, number>;
    incoming_attacks: number;
    captured_at: string;
  };

  const UNIT_LABEL: Record<string, string> = {
    spear: "Speer", sword: "Schwert", axe: "Axt", archer: "Bogen", spy: "Späher", light: "LKav",
    marcher: "BB", heavy: "SKav", ram: "Ramme", catapult: "Kata", knight: "Pala", snob: "AG",
  };
  const OFF_POP: Record<string, number> = { axe: 1, light: 4, marcher: 5, ram: 5, catapult: 8 };
  const DEFF_POP: Record<string, number> = { spear: 1, sword: 1, archer: 1, heavy: 6 };

  let tab = $state<"table" | "status" | "import">("table");
  let rows = $state<Row[]>([]);
  let status = $state<any[]>([]);
  let hours = $state(24);
  let filter = $state("");
  let sortKey = $state("player");
  let sortDesc = $state(false);
  let script = $state<any>(null);
  let paste = $state("");
  let pasteResult = $state<any>(null);
  let collect = $state<any>(null);
  let timer: ReturnType<typeof setInterval> | null = null;

  async function load() {
    rows = await call("troops_overview");
    status = await call("troops_status", { hours });
  }

  onMount(async () => {
    try {
      await load();
      script = await call("truppen_skript");
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

  const units = $derived(
    Object.keys(UNIT_LABEL).filter((u) => rows.some((r) => (r.units[u] ?? 0) > 0)),
  );

  function ageHours(iso: string): number {
    return (Date.now() - new Date(iso).getTime()) / 3_600_000;
  }
  function ageText(iso: string): string {
    const h = ageHours(iso);
    return h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} Tage`;
  }
  const off = (r: Row) => Object.entries(OFF_POP).reduce((s, [u, p]) => s + (r.units[u] ?? 0) * p, 0);
  const deff = (r: Row) => Object.entries(DEFF_POP).reduce((s, [u, p]) => s + (r.units[u] ?? 0) * p, 0);

  function value(r: Row, key: string): number | string {
    if (key === "player") return r.player.toLowerCase();
    if (key === "coord") return r.coord;
    if (key === "off") return off(r);
    if (key === "deff") return deff(r);
    if (key === "age") return ageHours(r.captured_at);
    return r.units[key] ?? 0;
  }

  const visible = $derived.by(() => {
    const f = filter.toLowerCase();
    const list = rows.filter((r) => !f || `${r.player} ${r.coord} ${r.name}`.toLowerCase().includes(f));
    return [...list].sort((a, b) => {
      const va = value(a, sortKey);
      const vb = value(b, sortKey);
      const c = va < vb ? -1 : va > vb ? 1 : 0;
      return sortDesc ? -c : c;
    });
  });

  const totals = $derived.by(() => {
    const t: Record<string, number> = {};
    for (const r of visible) for (const u of units) t[u] = (t[u] ?? 0) + (r.units[u] ?? 0);
    return t;
  });

  function sortBy(key: string) {
    if (sortKey === key) sortDesc = !sortDesc;
    else {
      sortKey = key;
      sortDesc = key !== "player" && key !== "coord";
    }
  }

  const fmt = (n: number) => n.toLocaleString("de-DE");
  // compact: 950 / 9.500 / 12,3k – keeps all columns on screen
  const short = (n: number) =>
    n >= 1_000_000
      ? `${(n / 1_000_000).toLocaleString("de-DE", { maximumFractionDigits: 1 })}M`
      : n >= 10_000
        ? `${(n / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 })}k`
        : fmt(n);
  const done = $derived(status.filter((p) => p.done).length);

  async function fromClipboard() {
    pasteResult = await call("import_troops_from_clipboard", { wait_seconds: 1 });
    await load();
  }
  async function importPaste() {
    pasteResult = await call("import_troops", { text: paste });
    paste = "";
    await load();
  }
  function poll() {
    if (timer) clearInterval(timer);
    timer = setInterval(async () => {
      try {
        collect = await call("troops_collect_status");
        if (!collect?.laeuft) {
          clearInterval(timer!);
          timer = null;
          await load();
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
  }
</script>

<h1>Truppen</h1>
<div class="steps">
  <button class:current={tab === "table"} onclick={() => (tab = "table")}>Alle Dörfer ({rows.length})</button>
  <button class:current={tab === "status"} onclick={() => (tab = "status")}>Pro Spieler ({done}/{status.length} aktuell)</button>
  <button class:current={tab === "import"} onclick={() => (tab = "import")}>Truppen einlesen</button>
</div>

{#if tab === "table"}
  <div class="card">
    <div class="row" style="justify-content: space-between">
      <input placeholder="Filtern: Spieler, Koordinate, Dorf" bind:value={filter} style="min-width: 18rem" />
      <span class="muted">{visible.length} Dörfer · Off/Deff = Einwohner (Axt 1, LKav 4, Ramme 5 …)</span>
    </div>
    {#if rows.length === 0}
      <p>Noch keine Truppen eingelesen. <button onclick={() => (tab = "import")}>Jetzt einlesen</button></p>
    {:else}
      <div class="tablewrap">
        <table class="troops">
          <thead>
            <tr>
              <th class="sort" onclick={() => sortBy("player")}>Spieler</th>
              <th class="sort" onclick={() => sortBy("coord")}>Dorf</th>
              {#each units as u}
                <th class="num sort" title={UNIT_LABEL[u]} onclick={() => sortBy(u)}>
                  <img src={`/units/${u}.png`} alt={UNIT_LABEL[u]} width="18" height="18" />
                </th>
              {/each}
              <th class="num sort" title="Off-Einwohner" onclick={() => sortBy("off")}>Off</th>
              <th class="num sort" title="Deff-Einwohner" onclick={() => sortBy("deff")}>Deff</th>
              <th class="num sort" onclick={() => sortBy("age")}>Alter</th>
            </tr>
          </thead>
          <tbody>
            {#each visible as r}
              <tr>
                <td class="player"><GameLink spieler={r.player} /></td>
                <td class="village" title={r.name}>
                  <GameLink dorf={r.coord} />{#if r.incoming_attacks} <span class="pill error" title="eingehende Angriffe">⚔{r.incoming_attacks}</span>{/if}
                  <div class="vname">{r.name}</div>
                </td>
                {#each units as u}<td class="num" title={r.units[u] ? `${UNIT_LABEL[u]}: ${fmt(r.units[u])}` : ""}>{r.units[u] ? short(r.units[u]) : ""}</td>{/each}
                <td class="num strong" class:full={off(r) >= 3000}>{short(off(r))}</td>
                <td class="num strong">{short(deff(r))}</td>
                <td class="num" class:msg-warn={ageHours(r.captured_at) > hours}>{ageText(r.captured_at)}</td>
              </tr>
            {/each}
          </tbody>
          <tfoot>
            <tr>
              <th colspan="2">Summe ({visible.length})</th>
              {#each units as u}<th class="num" title={fmt(totals[u] ?? 0)}>{short(totals[u] ?? 0)}</th>{/each}
              <th></th><th></th><th></th>
            </tr>
          </tfoot>
        </table>
      </div>
    {/if}
  </div>
{:else if tab === "status"}
  <div class="card">
    <div class="row">
      <label class="inline">Aktuell = jünger als <input type="number" min="1" style="width: 5rem" bind:value={hours} /> Stunden</label>
      <ActionButton label="Aktualisieren" run={load} />
    </div>
    <table style="margin-top: 0.75rem">
      <thead><tr><th>Spieler</th><th class="num">Dörfer</th><th class="num">Aktuell</th><th></th></tr></thead>
      <tbody>
        {#each status as p}
          <tr>
            <td><GameLink spieler={p.player} /></td>
            <td class="num">{p.villages}</td>
            <td class="num">{p.fresh}</td>
            <td><span class="pill {p.done ? 'ok' : 'warn'}">{p.done ? "aktuell" : "fehlt / alt"}</span></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{:else}
  <div class="card">
    <h2 style="margin-top: 0">1. Truppen-Skript in die Schnellleiste (einmalig)</h2>
    {#if script}
      <ol>{#each script.schritte as step}<li>{step}</li>{/each}</ol>
      <div class="row">
        <ActionButton label="Zeile für die Schnellleiste kopieren" primary run={() => copyText(script.schnellleiste)} done="Kopiert." />
        <span class="muted">Version {script.version}</span>
      </div>
      <p class="hint">{script.hinweis}</p>
    {/if}
  </div>
  <div class="card">
    <h2 style="margin-top: 0">2. Ergebnis einlesen</h2>
    <p>Im Spiel im Skript-Fenster auf <b>Kopieren</b> klicken, dann hier:</p>
    <ActionButton label="Aus der Zwischenablage einlesen" primary run={fromClipboard} done="Truppen eingelesen." />
    <details>
      <summary>Oder Text von Hand einfügen</summary>
      <textarea bind:value={paste} placeholder="Skript-Export oder kopierte Truppen-Tabelle"></textarea>
      <ActionButton label="Einlesen" run={importPaste} disabled={!paste.trim()} done="Truppen eingelesen." />
    </details>
    {#if pasteResult}<div style="margin-top: 1rem"><Value value={pasteResult} /></div>{/if}
  </div>
  <details class="card">
    <summary>Ohne Skript: Seiten einzeln kopieren (Sammel-Modus)</summary>
    <p>Starten, dann im Spiel jede Truppen-Seite mit Strg+A, Strg+C kopieren. Jede Kopie wird sofort eingelesen.</p>
    <div class="row">
      {#if collect?.laeuft}
        <ActionButton label="Fertig" primary run={async () => { collect = await call("troops_collect_stop"); await load(); }} />
        <span class="pill ok">läuft</span>
      {:else}
        <ActionButton label="Sammeln starten" run={async () => { collect = await call("troops_collect_start", { minutes: 30 }); poll(); }} />
      {/if}
    </div>
    {#if collect}<div style="margin-top: 1rem"><Value value={collect} /></div>{/if}
  </details>
{/if}

<style>
  /* no inner scroll box: the page scrolls, the header row stays on top */
  .tablewrap { margin-top: 0.75rem; }
  .troops { font-size: 0.8rem; table-layout: fixed; width: 100%; }
  .troops th, .troops td {
    padding: 0.3rem 0.25rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    overflow-wrap: normal;
  }
  .troops thead th:nth-child(1) { width: 15%; }
  .troops thead th:nth-child(2) { width: 15%; }
  .vname { color: var(--muted); font-size: 0.72rem; overflow: hidden; text-overflow: ellipsis; }
  .troops img { vertical-align: middle; }
  .strong { font-weight: 600; }
  .full { color: var(--ok); }
  .troops thead th { position: sticky; top: 0; z-index: 1; background: var(--panel); }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .sort { cursor: pointer; user-select: none; }
  .sort:hover { color: var(--text); }
  tfoot th { border-top: 2px solid var(--border); }
</style>
