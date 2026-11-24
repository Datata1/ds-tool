<script lang="ts">
  let { state }: { state: string } = $props();
  const look: Record<string, [string, string]> = {
    aktuell: ["ok", "erledigt"],
    veraltet: ["warn", "veraltet – neu senden"],
    fehlt: ["", "offen"],
    aus: ["", "nicht eingerichtet"],
  };
  const [cls, text] = $derived(look[state] ?? ["", state]);
</script>

<span class="pill {cls}">{text}</span>
