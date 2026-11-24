<script lang="ts">
  // Shows any JSON result readably: lists as bullets, objects as key/value rows.
  import Value from "./Value.svelte";
  import GameLink from "./GameLink.svelte";

  let { value, field = "" }: { value: unknown; field?: string } = $props();

  const COORD = /^\d{1,3}\|\d{1,3}$/;
  const PLAYER_FIELDS = new Set(["player", "spieler", "owner", "besitzer", "account"]);

  function label(key: string): string {
    const k = key.replace(/^\d+_/, "").replace(/_/g, " ");
    return k.charAt(0).toUpperCase() + k.slice(1);
  }
</script>

{#if value === null || value === undefined}
  <span class="muted">–</span>
{:else if Array.isArray(value) && value.length > 0 && value.every((v) => v && typeof v === "object" && !Array.isArray(v))}
  {@const cols = [...new Set(value.flatMap((v) => Object.keys(v as object)))]}
  <table>
    <thead><tr>{#each cols as c}<th>{label(c)}</th>{/each}</tr></thead>
    <tbody>
      {#each value as item}
        <tr>{#each cols as c}<td><Value value={(item as any)[c]} field={c} /></td>{/each}</tr>
      {/each}
    </tbody>
  </table>
{:else if Array.isArray(value)}
  {#if value.length === 0}
    <span class="muted">keine</span>
  {:else}
    <ul class="plain">
      {#each value as item}
        <li><Value value={item} /></li>
      {/each}
    </ul>
  {/if}
{:else if typeof value === "object"}
  <table>
    <tbody>
      {#each Object.entries(value as Record<string, unknown>) as [k, v]}
        <tr><th style="width: 30%">{label(k)}</th><td><Value value={v} field={k} /></td></tr>
      {/each}
    </tbody>
  </table>
{:else if typeof value === "boolean"}
  <span class="pill {value ? 'ok' : 'warn'}">{value ? "ja" : "nein"}</span>
{:else if typeof value === "string" && COORD.test(value.trim())}
  <GameLink dorf={value.trim()} />
{:else if typeof value === "string" && value && value !== "Barbar" && value !== "?" && PLAYER_FIELDS.has(field.toLowerCase())}
  <GameLink spieler={value} />
{:else if typeof value === "string" && /^https?:\/\//.test(value)}
  <a href={value} target="_blank" rel="noreferrer">{value}</a>
{:else}
  <span style="white-space: pre-wrap">{String(value)}</span>
{/if}
