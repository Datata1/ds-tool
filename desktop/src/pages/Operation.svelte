<script lang="ts">
  import { onMount } from "svelte";
  import { call } from "../lib/api";
  import { page, toast, errorText, type OpStep } from "../lib/stores";
  import PlanStep from "./op/PlanStep.svelte";
  import CheckStep from "./op/CheckStep.svelte";
  import ReviewStep from "./op/ReviewStep.svelte";
  import ApproveStep from "./op/ApproveStep.svelte";
  import PlayersStep from "./op/PlayersStep.svelte";
  import LiveStep from "./op/LiveStep.svelte";

  let { op, step }: { op: string | null; step?: OpStep } = $props();

  let status = $state<any>(null);
  let current = $state<OpStep>("planen");
  let checkKey = $state(0);
  // existing operation: show the steps only once we know where it stands (no jumping)
  let ready = $state(false);

  async function refresh() {
    if (!op) return;
    try {
      status = await call("operation_status", { name: op });
    } catch (e) {
      toast(errorText(e), "error");
    }
  }

  onMount(async () => {
    await refresh();
    current = step ?? (op ? firstOpen() : "planen");
    ready = true;
  });

  const ok = (s?: string) => s === "aktuell" || s === "aus";

  // A step is done when everything in it is up to date (unconfigured parts count as done).
  const done = $derived<Record<OpStep, boolean>>({
    planen: !!status,
    fakes: !!status?.geplant,
    // an empty plan is never "done": nothing to review or send
    pruefen: !!status?.geplant && status.fehler === 0 && status.befehle_anzahl > 0,
    review:
      !!status?.geplant &&
      status.fehler === 0 &&
      status.befehle_anzahl > 0 &&
      status.dsu_ziele === "aktuell" &&
      (!status.google || status.doc === "aktuell") &&
      ok(status.review),
    freigabe: status?.status === "approved",
    spieler:
      status?.status === "approved" &&
      status.dsu_spieler === "aktuell" &&
      ok(status.befehle) &&
      ok(status.ankuendigung),
    laufend: false,
  });

  const STEPS: [OpStep, string][] = [
    ["planen", "1 Ziele"],
    ["fakes", "2 Fakes"],
    ["pruefen", "3 Prüfen"],
    ["review", "4 SF-Review"],
    ["freigabe", "5 Freigabe"],
    ["spieler", "6 An Spieler"],
    ["laufend", "7 Laufend"],
  ];
  const order = STEPS.map(([s]) => s);

  function firstOpen(): OpStep {
    return order.find((s) => !done[s]) ?? "laufend";
  }

  // later steps open once all earlier ones are done
  function reachable(s: OpStep): boolean {
    if (!op) return s === "planen";
    const i = order.indexOf(s);
    return order.slice(0, i).every((p) => done[p]);
  }

  const idx = $derived(order.indexOf(current));
  const next = $derived(order[idx + 1] as OpStep | undefined);
  const prev = $derived(order[idx - 1] as OpStep | undefined);

  async function saved(name: string, then: "stay" | "fakes" | "solve") {
    const solve = then === "solve";
    if (name !== op) {
      page.set({ name: "op", op: name, step: solve ? "pruefen" : then === "fakes" ? "fakes" : "planen" });
      return;
    }
    if (then === "fakes") {
      await refresh();
      current = "fakes";
      return;
    }
    if (solve) {
      try {
        await call("solve_operation", { name });
      } catch (e) {
        toast(errorText(e), "error");
      }
      await refresh();
      checkKey++;
      current = "pruefen";
    } else {
      await refresh();
    }
  }
</script>

<div class="row" style="justify-content: space-between">
  <h1 style="margin-bottom: 0.25rem">{status?.titel ?? (op ? op : "Neue Operation")}</h1>
  {#if status}
    <span class="muted">Ankunft {new Date(status.ankunft).toLocaleString("de-DE")}</span>
  {/if}
</div>

{#if !ready}
  <p class="muted" style="margin-top: 0.75rem">Lade Operation …</p>
{:else}
<div class="steps" style="margin-top: 0.75rem">
  {#each STEPS as [s, label]}
    <button class:current={current === s} class:done={done[s]} disabled={!reachable(s)} onclick={() => (current = s)}>{label}</button>
  {/each}
</div>

{#if current === "planen" || current === "fakes"}
  {#key `${op}-${current}`}<PlanStep {op} part={current === "fakes" ? "fakes" : "ziele"} onSaved={saved} />{/key}
{:else if op && status}
  {#if current === "pruefen"}
    {#key checkKey}<CheckStep {op} planned={status.geplant} onSolved={async () => { await refresh(); }} />{/key}
  {:else if current === "review"}
    <ReviewStep {op} {status} {refresh} />
  {:else if current === "freigabe"}
    <ApproveStep {op} {status} {refresh} />
  {:else if current === "spieler"}
    <PlayersStep {op} {status} {refresh} />
  {:else if current === "laufend"}
    <LiveStep {op} />
  {/if}
{/if}

{#if op && current !== "planen"}
  <div class="nav-buttons">
    <button disabled={!prev} onclick={() => prev && (current = prev)}>← Zurück</button>
    {#if next}
      <button class="primary" disabled={!done[current]} title={done[current] ? "" : "Erst diesen Schritt abschließen"} onclick={() => (current = next)}>Weiter →</button>
    {/if}
  </div>
{/if}
{/if}
