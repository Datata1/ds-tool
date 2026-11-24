<script lang="ts">
  import { call } from "../../lib/api";
  import { copyText } from "../../lib/clipboard";
  import ActionButton from "../../lib/ActionButton.svelte";
  import PreviewStep from "../../lib/PreviewStep.svelte";
  import DsuLinks from "../../lib/DsuLinks.svelte";

  let { op, status, refresh }: { op: string; status: any; refresh: () => void } = $props();

  let aktion = $state<any>(null);
  let texts = $state<string[] | null>(null);
</script>

<PreviewStep
  title="1. DS-Ultimate-Pläne pro Spieler"
  description="Jeder Spieler bekommt einen Plan nur mit seinen Befehlen."
  usecase="dsu_publish"
  args={{ name: op, fuer: "spieler", aktualisieren: status.dsu_spieler !== "fehlt" }}
  confirmLabel="Pläne anlegen"
  stepState={status.dsu_spieler}
  waitHint="DS Ultimate wird höflich Plan für Plan befüllt – etwa 5–10 Sekunden pro Plan."
  onDone={refresh}
>
  {#key status.dsu_spieler}<DsuLinks {op} kind="pro_spieler" />{/key}
</PreviewStep>

{#if status.discord}
  <PreviewStep
    title={`2. Befehle an jeden Spieler (${status.befehle_art === "thread" ? "private Threads" : "Direktnachricht"})`}
    description="Jeder bekommt seine Befehle mit Plan-Link. Schon gesendete Nachrichten werden bearbeitet, nicht doppelt geschickt."
    usecase="discord_send"
    args={{ name: op, art: status.befehle_art }}
    stepState={status.befehle}
    onDone={refresh}
  />
  {#if status.befehle_fehlen?.length}
    <div class="card msg-warn">Ohne Discord-Zuordnung (bekommen nichts): {status.befehle_fehlen.join(", ")}</div>
  {/if}
  <PreviewStep
    title="3. Öffentliche Ankündigung"
    description="Grunddaten ohne Ziele, Aufruf zu zusätzlichen Fakes, erwähnt die Rollen von Stamm und Wing."
    usecase="discord_send"
    args={{ name: op, art: "spieler" }}
    stepState={status.ankuendigung}
    onDone={refresh}
  />
{:else}
  <div class="card">
    <h2 style="margin-top: 0">2. Nachrichten</h2>
    <p class="muted">Discord-Bot nicht eingerichtet: Texte kopieren und selbst posten.</p>
    <div class="row">
      <ActionButton label="Befehle pro Spieler" run={async () => (texts = await call("discord_message", { name: op, art: "dm" }))} />
      <ActionButton label="Ankündigung" run={async () => (texts = await call("discord_message", { name: op, art: "spieler" }))} />
    </div>
    {#each texts ?? [] as part, i}
      <div class="row" style="justify-content: space-between; margin-top: 0.75rem">
        <b>Nachricht {i + 1}</b>
        <ActionButton label="Kopieren" run={() => copyText(part)} done="Kopiert." />
      </div>
      <pre>{part}</pre>
    {/each}
  </div>
{/if}

<details class="card">
  <summary>Für die Stammesführung: aktion.md (mit Bearbeiten-Links)</summary>
  <ActionButton label="aktion.md erzeugen" run={async () => (aktion = await call("aktion_message", { names: [op] }))} />
  {#each aktion?.nachrichten ?? [] as msg, i}
    <div class="row" style="margin-top: 0.75rem; justify-content: space-between">
      <b>Nachricht {i + 1}</b>
      <ActionButton label="Kopieren" run={() => copyText(msg)} done="Kopiert." />
    </div>
    <pre>{msg}</pre>
  {/each}
</details>
