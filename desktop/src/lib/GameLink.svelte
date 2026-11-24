<script lang="ts">
  // Player name or village coordinate that opens the page in the game (player's own browser).
  import { call } from "./api";
  import { openExternal } from "./native";
  import { toast, errorText } from "./stores";

  // dorf: any text containing a coordinate ("478|535", "478|535 Name"); shown as given.
  let { dorf, spieler, text }: { dorf?: string; spieler?: string; text?: string } = $props();

  const coord = $derived(dorf?.match(/\d{1,3}\|\d{1,3}/)?.[0]);
  const name = $derived(spieler?.trim() ?? "");
  const linkable = $derived(dorf ? !!coord : !!name && name !== "?" && name !== "Barbar" && name !== "-");

  async function open(event: MouseEvent) {
    event.preventDefault();
    event.stopPropagation();
    try {
      const r = await call("spiel_link", dorf ? { dorf: coord } : { spieler: name });
      await openExternal(r.url);
    } catch (e) {
      toast(errorText(e), "error");
    }
  }
</script>

{#if linkable}<a href="#spiel" class="game" title="Im Spiel öffnen" onclick={open}>{text ?? dorf ?? spieler}</a>{:else}{text ?? dorf ?? spieler ?? ""}{/if}

<style>
  .game { color: inherit; text-decoration: none; border-bottom: 1px dotted var(--muted); }
  .game:hover { color: var(--accent); border-bottom-color: var(--accent); }
</style>
