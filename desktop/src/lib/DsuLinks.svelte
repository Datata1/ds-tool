<script lang="ts">
  // The DS Ultimate plans already created for this operation (view links only).
  import { onMount } from "svelte";
  import { call } from "./api";
  import { copyText } from "./clipboard";
  import { openExternal } from "./native";
  import { toast } from "./stores";

  let { op, kind }: { op: string; kind: "pro_ziel" | "pro_spieler" } = $props();

  let links = $state<Record<string, string>>({});

  onMount(async () => {
    try {
      links = (await call("dsu_links", { name: op }))[kind] ?? {};
    } catch {
      links = {};
    }
  });

  const entries = $derived(Object.entries(links));
</script>

{#if entries.length}
  <details open={entries.length <= 12}>
    <summary>Angelegte Pläne ({entries.length})</summary>
    <table>
      <tbody>
        {#each entries as [key, url]}
          <tr>
            <td style="width: 35%">{kind === "pro_ziel" ? `Ziel ${key}` : key}</td>
            <td class="muted" style="font-size: 0.8rem; word-break: break-all">{url}</td>
            <td style="white-space: nowrap; text-align: right">
              <button onclick={() => openExternal(url)}>Öffnen</button>
              <button onclick={async () => { await copyText(url); toast("Link kopiert.", "ok"); }}>Kopieren</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </details>
{/if}
