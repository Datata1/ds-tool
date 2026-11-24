<script lang="ts">
  import { onMount } from "svelte";
  import { call } from "../lib/api";
  import { page, errorText } from "../lib/stores";

  let ops = $state<any[] | null>(null);
  let error = $state("");

  onMount(async () => {
    try {
      const list: any[] = await call("list_operations");
      // newest arrival first
      ops = list.sort((a, b) => String(b.arrival ?? "").localeCompare(String(a.arrival ?? "")));
    } catch (e) {
      error = errorText(e);
    }
  });

  const statusLabel: Record<string, string> = {
    draft: "Entwurf",
    in_review: "Im Review",
    approved: "Freigegeben",
  };
</script>

<div class="row" style="justify-content: space-between">
  <h1>Operationen</h1>
  <button class="primary" onclick={() => page.set({ name: "op", op: null })}>Neue Operation</button>
</div>

{#if error}
  <div class="card msg-error">{error}</div>
{:else if !ops}
  <p class="muted">Lade …</p>
{:else if ops.length === 0}
  <div class="card"><p>Noch keine Operation. Leg die erste an!</p></div>
{:else}
  <div class="card">
    <table>
      <thead><tr><th>Name</th><th>Ankunft</th><th>Ziele</th><th>Status</th><th></th></tr></thead>
      <tbody>
        {#each ops as op}
          <tr>
            <td>{op.title ?? op.name}{#if op.error}<div class="msg-error">{op.error}</div>{/if}</td>
            <td>{op.arrival ? new Date(op.arrival).toLocaleString("de-DE") : ""}</td>
            <td>{(op.targets ?? []).length}</td>
            <td>
              <span class="pill">{statusLabel[op.status] ?? op.status ?? "?"}</span>
              {#if !op.planned}<span class="pill warn">nicht gerechnet</span>{/if}
            </td>
            <td class="actions">
              <button class="primary" onclick={() => page.set({ name: "op", op: op.name })}>Öffnen</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .actions { white-space: nowrap; text-align: right; }
  .actions button { padding: 0.3rem 0.7rem; font-size: 0.85rem; }
</style>
