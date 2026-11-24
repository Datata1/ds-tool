<script lang="ts">
  import { onMount } from "svelte";
  import { call } from "../../lib/api";
  import { page, toast, errorText } from "../../lib/stores";
  import ActionButton from "../../lib/ActionButton.svelte";
  import GameLink from "../../lib/GameLink.svelte";

  // part "ziele": real targets + general settings; part "fakes": fake targets (+ suggestions)
  let {
    op,
    part = "ziele",
    onSaved,
  }: { op: string | null; part?: "ziele" | "fakes"; onSaved: (name: string, then: "stay" | "fakes" | "solve") => void } =
    $props();

  let data = $state<any>(null);
  let opName = $state("");
  let isNew = $state(true);
  let lookups = $state<Record<number, string>>({});
  let advanced = $state(false);
  let yamlText = $state("");
  let players = $state<{ spieler: string; doerfer: number; aktuell: number; mit_truppen: number }[]>([]);
  let playerFilter = $state("");
  // fake suggestions
  let radius = $state(10);
  let tribes = $state("");
  let fakesPerTarget = $state(1);
  let suggestions = $state<any[]>([]);
  let picked = $state<Record<string, boolean>>({});
  let newFake = $state("");

  onMount(async () => {
    try {
      const form = await call("operation_form", { name: op });
      data = form.operation;
      data.send_window ??= { start: "07:00:00", end: "23:00:00" };
      data.off_settings ??= {};
      data.off_settings.min_pop ??= 3000;
      data.fake_settings ??= {};
      data.fake_settings.unit ??= "ram";
      data.off_send_gap_s ??= 2;
      data.participants ??= {};
      data.participants.exclude_players ??= [];
      players = await call("operation_players", {
        tribes: data.participants.allies?.length ? data.participants.allies : null,
        hours: data.max_troop_age_hours ?? 24,
      });
      // "only these players" (e.g. written by Claude) -> shown as: everyone else unticked
      if (data.participants.players?.length) {
        const only = new Set(data.participants.players.map((n: string) => n.toLowerCase()));
        data.participants.exclude_players = players
          .map((p) => p.spieler)
          .filter((n) => !only.has(n.toLowerCase()));
        data.participants.players = [];
      }
      // which rows are fake targets (fixed while editing, so rows never jump between steps)
      for (const t of data.targets) t._fake = !(t.offs || t.nobles || t.tab_offs || t.support);
      isNew = form.neu;
      opName = form.name ?? "";
      data.targets.forEach((_: unknown, i: number) => lookup(i));
    } catch (e) {
      toast(errorText(e), "error");
    }
  });

  const excluded = $derived(new Set((data?.participants?.exclude_players ?? []).map((n: string) => n.toLowerCase())));
  const included = (name: string) => !excluded.has(name.toLowerCase());
  const shownPlayers = $derived(
    players.filter((p) => !playerFilter || p.spieler.toLowerCase().includes(playerFilter.toLowerCase())),
  );
  const includedCount = $derived(players.filter((p) => included(p.spieler)).length);

  function setIncluded(name: string, on: boolean) {
    const rest = data.participants.exclude_players.filter((n: string) => n.toLowerCase() !== name.toLowerCase());
    data.participants.exclude_players = on ? rest : [...rest, name];
  }
  function setAll(on: boolean) {
    const names = shownPlayers.map((p) => p.spieler);
    for (const n of names) setIncluded(n, on);
  }
  function onlyWithTroops() {
    data.participants.exclude_players = players.filter((p) => p.mit_truppen === 0).map((p) => p.spieler);
  }

  function newTarget() {
    return { coord: "", offs: 3, nobles: 4, fakes: 0, fake_nobles: 0, tab_offs: 0, note: "", _fake: false };
  }

  const realTargets = $derived(data ? data.targets.map((t: any, i: number) => [t, i]).filter(([t]: any) => !t._fake) : []);
  const fakeTargets = $derived(data ? data.targets.map((t: any, i: number) => [t, i]).filter(([t]: any) => t._fake) : []);
  const usedCoords = $derived(new Set(data ? data.targets.map((t: any) => String(t.coord).trim()) : []));

  function addFake(coord: string, note = "") {
    coord = coord.trim();
    if (!/^\d{1,3}\|\d{1,3}$/.test(coord)) throw new Error("Koordinate im Format 123|456 eingeben.");
    if (usedCoords.has(coord)) throw new Error(`${coord} ist schon ein Ziel.`);
    data.targets.push({ coord, offs: 0, nobles: 0, fakes: Number(fakesPerTarget) || 1, fake_nobles: 0, tab_offs: 0, note, _fake: true });
    lookup(data.targets.length - 1);
  }

  async function suggest() {
    const ziele = realTargets.map(([t]: any) => String(t.coord).trim()).filter(Boolean);
    suggestions = await call("fake_ziele_vorschlag", {
      ziele,
      abstand: Number(radius) || 10,
      staemme: tribes.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean),
    });
    picked = Object.fromEntries(suggestions.filter((v) => !usedCoords.has(v.coord)).map((v) => [v.coord, true]));
  }

  function addPicked() {
    let n = 0;
    for (const v of suggestions) {
      if (picked[v.coord] && !usedCoords.has(v.coord)) {
        addFake(v.coord);
        n++;
      }
    }
    picked = {};
    toast(`${n} Fake-Ziele hinzugefügt.`, "ok");
  }

  async function lookup(i: number) {
    const coord = String(data.targets[i]?.coord ?? "").trim();
    if (!/^\d{1,3}\|\d{1,3}$/.test(coord)) {
      lookups[i] = coord ? "Format: 123|456" : "";
      return;
    }
    try {
      const v = await call("village_lookup", { ref: coord });
      lookups[i] = `${v.name} – ${v.owner} [${v.tribe}], ${v.points} Punkte`;
    } catch (e) {
      lookups[i] = errorText(e);
    }
  }

  function toggleSupport(t: any) {
    t.support = t.support ? null : { min_pop: 3000 };
  }

  function clean(op: any) {
    const out = structuredClone($state.snapshot(op));
    out.off_settings.min_pop = Number(out.off_settings.min_pop || 1);
    out.off_send_gap_s = Number(out.off_send_gap_s || 0);
    for (const t of out.targets) {
      delete t._fake;
      for (const k of ["offs", "nobles", "fakes", "fake_nobles", "tab_offs"]) t[k] = Number(t[k] || 0);
      if (t.support) {
        t.support.min_pop = Number(t.support.min_pop || 1);
        if (!t.support.arrival) delete t.support.arrival;
      }
      if (!t.arrival) delete t.arrival;
    }
    return out;
  }

  async function save(): Promise<string> {
    const name = (opName || data.name).trim();
    if (!name) throw new Error("Bitte einen Namen eingeben.");
    if (advanced) {
      const r = await call("write_operation", { name, operation_yaml: yamlText });
      return r.name;
    }
    const r = await call("save_operation_form", { name, operation: clean(data) });
    return r.name;
  }

  async function saveOnly() {
    const name = await save();
    opName = name;
    isNew = false;
    toast("Gespeichert.", "ok");
    onSaved(name, "stay");
  }

  async function saveAndNext() {
    onSaved(await save(), "fakes");
  }

  async function saveAndSolve() {
    onSaved(await save(), "solve");
  }

  async function showYaml() {
    if (!advanced) {
      if (isNew) {
        const name = (opName || data.name || "neue-operation").trim();
        await call("save_operation_form", { name, operation: clean(data) });
        opName = name;
        isNew = false;
      }
      yamlText = (await call("get_operation", { name: opName })).operation_yaml;
    }
    advanced = !advanced;
  }
</script>

{#if !data}
  <p class="muted">Lade …</p>
{:else if part === "ziele"}
  <div class="card">
    <div class="grid">
      <label>Name<input bind:value={data.name} oninput={() => isNew && (opName = data.name)} placeholder="z.B. Flut 25.11." /></label>
      <label>Ankunft (Serverzeit)<input type="datetime-local" step="1" bind:value={data.arrival} /><span class="hint">Standard für alle Ziele; pro Ziel änderbar.</span></label>
      <label>Abschicken von<input type="time" step="1" bind:value={data.send_window.start} /><span class="hint">Ab dieser Uhrzeit können eure Spieler losschicken.</span></label>
      <label>Abschicken bis<input type="time" step="1" bind:value={data.send_window.end} /></label>
    </div>
    <label style="margin-top: 0.75rem">Worum geht es? (steht im Google Doc; Zeilen mit „- “ werden Aufzählungen)
      <textarea bind:value={data.beschreibung} style="min-height: 4rem"></textarea>
    </label>
  </div>

  <div class="card">
    <div class="row" style="justify-content: space-between">
      <h2 style="margin: 0">Teilnehmende Spieler ({includedCount}/{players.length})</h2>
      <div class="row">
        <input placeholder="Spieler suchen" bind:value={playerFilter} style="width: 12rem" />
        <button onclick={() => setAll(true)}>Alle</button>
        <button onclick={() => setAll(false)}>Keine</button>
        <button onclick={onlyWithTroops} title="Nur Spieler, von denen Truppen eingelesen sind">Nur mit Truppen</button>
      </div>
    </div>
    <p class="hint">Nur angehakte Spieler bekommen Befehle. Wer neu in den Stamm kommt, ist automatisch dabei.</p>
    {#if players.length === 0}
      <p class="muted">Keine Spieler gefunden – ist der eigene Stamm in der Einrichtung eingetragen?</p>
    {:else}
      <div class="players">
        {#each shownPlayers as p}
          <label class="inline player" class:off={!included(p.spieler)}>
            <input type="checkbox" checked={included(p.spieler)} onchange={(e) => setIncluded(p.spieler, e.currentTarget.checked)} />
            <span class="pname">{p.spieler}</span>
            {#if p.mit_truppen === 0}<span class="pill warn tag" title="Keine Truppen eingelesen">keine Truppen</span>
            {:else if p.mit_truppen < p.doerfer}<span class="pill tag" title="Dörfer mit eingelesenen Truppen">{p.mit_truppen}/{p.doerfer} Dörfer</span>
            {:else if p.aktuell < p.doerfer}<span class="pill warn tag" title="Truppendaten älter als erlaubt">alt</span>{/if}
          </label>
        {/each}
      </div>
    {/if}
  </div>

  <div class="card">
    <h2 style="margin-top: 0">Offs</h2>
    <div class="grid">
      <label>Volle Off ab<input type="number" min="1" bind:value={data.off_settings.min_pop} /><span class="hint">Off-Einwohner (Axt 1, LKav 4, BB 5, Ramme 5, Kata 8). Darunter zählt ein Dorf nicht als volle Off.</span></label>
      <label>Abstand Off vor AG (Sekunden)<input type="number" min="0" bind:value={data.off_send_gap_s} /><span class="hint">Ohne Millisekunden landet in derselben Sekunde, was zuerst abgeschickt wurde. So viele Sekunden früher geht jede Off vor dem ersten AG raus.</span></label>
    </div>
    <p class="hint">Neue Operationen starten mit den Werten deiner letzten gespeicherten Operation.</p>
  </div>

  {#if advanced}
    <div class="card">
      <h2>Erweitert (YAML)</h2>
      <p class="muted">Alle Felder der Operation. Wird beim Speichern geprüft.</p>
      <textarea bind:value={yamlText} style="min-height: 24rem"></textarea>
    </div>
  {:else}
    {#each realTargets as [t, i], n}
      <div class="card">
        <div class="row" style="justify-content: space-between">
          <h2 style="margin: 0">Ziel {n + 1}</h2>
          <button class="danger" onclick={() => data.targets.splice(i, 1)} disabled={realTargets.length === 1}>Entfernen</button>
        </div>
        <div class="grid" style="margin-top: 0.5rem">
          <label>Koordinate<input bind:value={t.coord} onblur={() => lookup(i)} placeholder="481|521" /></label>
          <label>Volle Offs<input type="number" min="0" bind:value={t.offs} /></label>
          <label>AGs<input type="number" min="0" bind:value={t.nobles} /></label>
          <label>Tab-Offs<input type="number" min="0" bind:value={t.tab_offs} /><span class="hint">Kleine Offs zwischen den AGs gegen Deff, die der Gegner dazwischen stellt.</span></label>
        </div>
        {#if lookups[i]}<p class="muted">{lookups[i]}</p>{/if}
        <div class="row" style="margin-top: 0.5rem">
          <label class="inline"><input type="checkbox" checked={!!t.support} onchange={() => toggleSupport(t)} /> <span title="Landet in derselben Sekunde wie die AGs, abgeschickt nach dem letzten AG. Nur Dörfer, die das nicht schaffen, landen 1 s später.">Flexdeff nach dem letzten AG (gleiche Sekunde)</span></label>
        </div>
        {#if t.support}
          <div class="grid" style="margin-top: 0.5rem">
            <label>Deff-Einwohner<input type="number" min="1" bind:value={t.support.min_pop} /></label>
            <label>Feste Landezeit (optional)<input type="datetime-local" step="1" bind:value={t.support.arrival} /></label>
          </div>
        {/if}
        <div class="grid" style="margin-top: 0.5rem">
          <label>Eigene Ankunft (optional)<input type="datetime-local" step="1" bind:value={t.arrival} /></label>
          <label>Notiz<input bind:value={t.note} /></label>
        </div>
      </div>
    {/each}
    <button onclick={() => data.targets.push(newTarget())}>+ Ziel hinzufügen</button>
  {/if}

  <div class="row" style="margin-top: 1.25rem">
    <ActionButton label="Speichern & weiter zu den Fakes" primary run={saveAndNext} />
    <ActionButton label="Nur speichern" run={saveOnly} />
    <ActionButton label={advanced ? "Zurück zum Formular" : "Erweitert (YAML)"} run={showYaml} />
    <button onclick={() => page.set({ name: "ops" })}>Zur Liste</button>
  </div>
  {#if advanced}<p class="muted">Im YAML-Modus wird das YAML gespeichert. Zurück zum Formular lädt die gespeicherte Fassung neu nicht automatisch – erst speichern, dann die Seite neu öffnen.</p>{/if}
{:else}
  <div class="card">
    <h2 style="margin-top: 0">Fake-Ziele ({fakeTargets.length})</h2>
    <p class="hint" style="margin-top: 0">Fakes lenken den Gegner von den echten Zielen ab. Hier Dörfer von Hand eintragen oder unten aus Vorschlägen übernehmen.</p>
    <div class="grid">
      <label>Fake-Einheit
        <select bind:value={data.fake_settings.unit}>
          <option value="ram">Ramme</option>
          <option value="catapult">Katapult</option>
        </select>
        <span class="hint">Langsamste Einheit eines Fakes – so sieht er wie ein echter Angriff aus.</span>
      </label>
      <label>Fakes pro neuem Ziel<input type="number" min="1" bind:value={fakesPerTarget} /><span class="hint">Gilt für Ziele, die du ab jetzt hinzufügst.</span></label>
      <label>Fake-Ziel von Hand
        <div class="row" style="flex-wrap: nowrap">
          <input bind:value={newFake} placeholder="481|521" onkeydown={(e) => { if (e.key === "Enter") { try { addFake(newFake); newFake = ""; } catch (err) { toast(errorText(err), "error"); } } }} />
          <ActionButton label="+" run={async () => { addFake(newFake); newFake = ""; }} />
        </div>
      </label>
    </div>
    {#if fakeTargets.length}
      <table style="margin-top: 0.75rem">
        <thead><tr><th>Ziel</th><th>Dorf</th><th class="num">Fakes</th><th class="num">Fake-AGs</th><th>Notiz</th><th></th></tr></thead>
        <tbody>
          {#each fakeTargets as [t, i] (i)}
            <tr>
              <td class="nowrap"><GameLink dorf={String(t.coord)} /></td>
              <td class="muted small">{lookups[i] ?? ""}</td>
              <td class="num"><input type="number" min="0" class="tiny" bind:value={t.fakes} /></td>
              <td class="num"><input type="number" min="0" class="tiny" bind:value={t.fake_nobles} /></td>
              <td><input bind:value={t.note} /></td>
              <td><button class="danger" onclick={() => data.targets.splice(i, 1)}>✕</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
    {:else}
      <p class="muted">Noch keine Fake-Ziele.</p>
    {/if}
  </div>

  <div class="card">
    <h2 style="margin-top: 0">Vorschläge aus dem Zielstamm</h2>
    <div class="grid">
      <label>Höchstens … Felder von einem echten Ziel<input type="number" min="1" bind:value={radius} /></label>
      <label>Stämme (optional)<input bind:value={tribes} placeholder="automatisch: Stamm der Ziele" /><span class="hint">Tags mit Komma, z.B. SWRE, SWRE2.</span></label>
    </div>
    <div class="row" style="margin-top: 0.5rem">
      <ActionButton label="Dörfer suchen" run={suggest} />
      {#if suggestions.length}
        <span class="muted">{suggestions.length} Dörfer gefunden</span>
        <button onclick={() => (picked = Object.fromEntries(suggestions.filter((v) => !usedCoords.has(v.coord)).map((v) => [v.coord, true])))}>Alle markieren</button>
        <button onclick={() => (picked = {})}>Keine</button>
        <ActionButton label={`Markierte hinzufügen (${Object.values(picked).filter(Boolean).length})`} primary run={async () => addPicked()} />
      {/if}
    </div>
    {#if suggestions.length}
      <table style="margin-top: 0.75rem">
        <thead><tr><th></th><th>Dorf</th><th>Spieler</th><th>Stamm</th><th class="num">Punkte</th><th class="num">Felder</th><th>zu Ziel</th></tr></thead>
        <tbody>
          {#each suggestions as v (v.coord)}
            {@const used = usedCoords.has(v.coord)}
            <tr class:muted={used}>
              <td><input type="checkbox" disabled={used} bind:checked={picked[v.coord]} /></td>
              <td><span class="nowrap"><GameLink dorf={v.coord} /></span> <span class="muted small">{v.dorf}</span>{#if used} <span class="pill ok">schon drin</span>{/if}</td>
              <td><GameLink spieler={v.spieler} /></td>
              <td>{v.stamm}</td>
              <td class="num">{v.punkte.toLocaleString("de-DE")}</td>
              <td class="num">{v.abstand.toLocaleString("de-DE")}</td>
              <td>{v.naechstes_ziel}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>

  {#if realTargets.length}
    <details class="card">
      <summary>Zusätzlich Fakes auf die echten Ziele</summary>
      <table style="margin-top: 0.5rem">
        <thead><tr><th>Ziel</th><th class="num">Fakes</th><th class="num">Fake-AGs</th></tr></thead>
        <tbody>
          {#each realTargets as [t] (t)}
            <tr>
              <td><GameLink dorf={String(t.coord)} /></td>
              <td class="num"><input type="number" min="0" class="tiny" bind:value={t.fakes} /></td>
              <td class="num"><input type="number" min="0" class="tiny" bind:value={t.fake_nobles} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </details>
  {/if}

  <div class="row" style="margin-top: 1.25rem">
    <ActionButton label="Speichern & rechnen" primary run={saveAndSolve} />
    <ActionButton label="Nur speichern" run={saveOnly} />
    <button onclick={() => page.set({ name: "ops" })}>Zur Liste</button>
  </div>
{/if}

<style>
  .nowrap { white-space: nowrap; overflow-wrap: normal; }
  .tiny { width: 5rem; }
  .small { font-size: 0.8rem; }
  .num { text-align: right; }
  .players { display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: 0.25rem 1rem; margin-top: 0.5rem; }
  .player { display: flex; align-items: center; gap: 0.4rem; min-width: 0; }
  .player .pname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .player .tag { white-space: nowrap; font-size: 0.72rem; padding: 0 0.4rem; flex-shrink: 0; }
  .player.off .pname { color: var(--muted); text-decoration: line-through; }
</style>
