<script lang="ts">
  import { onMount } from "svelte";
  import { call } from "../lib/api";
  import { page, toast, errorText } from "../lib/stores";
  import ActionButton from "../lib/ActionButton.svelte";

  let { op }: { op: string | null } = $props();

  let data = $state<any>(null);
  let opName = $state("");
  let isNew = $state(true);
  let lookups = $state<Record<number, string>>({});
  let advanced = $state(false);
  let yamlText = $state("");

  onMount(async () => {
    try {
      const form = await call("operation_form", { name: op });
      data = form.operation;
      isNew = form.neu;
      opName = form.name ?? "";
      data.targets.forEach((_: unknown, i: number) => lookup(i));
    } catch (e) {
      toast(errorText(e), "error");
    }
  });

  function newTarget() {
    return { coord: "", offs: 3, nobles: 4, fakes: 0, fake_nobles: 0, fusion: false, tab_offs: 0, note: "" };
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
    for (const t of out.targets) {
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
  }

  async function saveAndSolve() {
    const name = await save();
    page.set({ name: "result", op: name });
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

<h1>{isNew ? "Neue Operation" : `Operation bearbeiten`}</h1>

{#if !data}
  <p class="muted">Lade …</p>
{:else}
  <div class="card">
    <div class="grid">
      <label>Name<input bind:value={data.name} oninput={() => isNew && (opName = data.name)} placeholder="z.B. Flut 25.11." /></label>
      <label>Ankunft (Serverzeit)<input type="datetime-local" step="1" bind:value={data.arrival} /></label>
    </div>
    <label style="margin-top: 0.75rem">Worum geht es? (steht im Google Doc; Zeilen mit „- “ werden Aufzählungen)
      <textarea bind:value={data.beschreibung} style="min-height: 4rem"></textarea>
    </label>
  </div>

  {#if advanced}
    <div class="card">
      <h2>Erweitert (YAML)</h2>
      <p class="muted">Alle Felder der Operation. Wird beim Speichern geprüft.</p>
      <textarea bind:value={yamlText} style="min-height: 24rem"></textarea>
    </div>
  {:else}
    {#each data.targets as t, i}
      <div class="card">
        <div class="row" style="justify-content: space-between">
          <h2 style="margin: 0">Ziel {i + 1}</h2>
          <button class="danger" onclick={() => data.targets.splice(i, 1)} disabled={data.targets.length === 1}>Entfernen</button>
        </div>
        <div class="grid" style="margin-top: 0.5rem">
          <label>Koordinate<input bind:value={t.coord} onblur={() => lookup(i)} placeholder="481|521" /></label>
          <label>Volle Offs<input type="number" min="0" bind:value={t.offs} /></label>
          <label>AGs<input type="number" min="0" bind:value={t.nobles} /></label>
          <label>Fakes<input type="number" min="0" bind:value={t.fakes} /></label>
          <label>Fake-AGs<input type="number" min="0" bind:value={t.fake_nobles} /></label>
          <label>Tab-Offs (zwischen AGs)<input type="number" min="0" bind:value={t.tab_offs} /></label>
        </div>
        {#if lookups[i]}<p class="muted">{lookups[i]}</p>{/if}
        <div class="row" style="margin-top: 0.5rem">
          <label class="inline"><input type="checkbox" bind:checked={t.fusion} /> Fusions-Offs erlaubt</label>
          <label class="inline"><input type="checkbox" checked={!!t.support} onchange={() => toggleSupport(t)} /> Flexdeff nach dem letzten AG</label>
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
    <ActionButton label="Speichern & rechnen" primary run={saveAndSolve} />
    <ActionButton label="Nur speichern" run={saveOnly} />
    <ActionButton label={advanced ? "Zurück zum Formular" : "Erweitert (YAML)"} run={showYaml} />
    <button onclick={() => page.set({ name: "ops" })}>Abbrechen</button>
  </div>
  {#if advanced}<p class="muted">Im YAML-Modus wird das YAML gespeichert. Zurück zum Formular lädt die gespeicherte Fassung neu nicht automatisch – erst speichern, dann die Seite neu öffnen.</p>{/if}
{/if}
