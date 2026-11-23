<script lang="ts">
  import { onMount } from "svelte";
  import { call } from "../lib/api";
  import { page, toast, errorText } from "../lib/stores";
  import { copyText } from "../lib/clipboard";
  import ActionButton from "../lib/ActionButton.svelte";
  import PreviewStep from "../lib/PreviewStep.svelte";
  import Value from "../lib/Value.svelte";

  let { op }: { op: string } = $props();

  let settings = $state<any>(null);
  let status = $state<string>("");
  let doc = $state<any>(null);
  let links = $state<any>(null);
  let aktion = $state<any>(null);
  let threads = $state(true);

  async function load() {
    settings = await call("app_settings");
    const list: any[] = await call("list_operations");
    status = list.find((o) => o.name === op)?.status ?? "";
    links = await call("dsu_links", { name: op });
  }

  onMount(() => load().catch((e) => toast(errorText(e), "error")));

  async function syncDoc() {
    doc = await call("google_doc_sync", { name: op });
  }

  async function setStatus(s: string) {
    await call("set_status", { name: op, status: s });
    await load();
  }

  const approved = $derived(status === "approved");
</script>

<div class="row" style="justify-content: space-between">
  <h1>Veröffentlichen: {op}</h1>
  <div class="row">
    <button onclick={() => page.set({ name: "result", op })}>Zum Ergebnis</button>
    <button onclick={() => page.set({ name: "live", op })}>Laufend</button>
  </div>
</div>
<p class="muted">
  Status: <span class="pill">{approved ? "Freigegeben" : status === "in_review" ? "Im Review" : "Entwurf"}</span>
  · Alles, was nach außen geht, zeigt zuerst eine Vorschau.
</p>

<h2>1. Für die SF (Review)</h2>
<PreviewStep
  title="DS-Ultimate-Pläne pro Ziel"
  description="Legt pro Zieldorf einen Plan in DS Ultimate an (bei Änderungen: dieselben Pläne neu befüllen)."
  usecase="dsu_publish"
  args={{ name: op, fuer: "ziele", aktualisieren: (links?.pro_ziel && Object.keys(links.pro_ziel).length > 0) }}
  confirmLabel="Pläne anlegen"
  onDone={load}
/>

<div class="card">
  <h2 style="margin-top: 0">Google Doc</h2>
  <p class="muted">
    Das Doc zeigt immer den aktuellen Plan: beim ersten Mal anlegen und für alle mit Link lesbar
    freigeben, danach dasselbe Doc neu befüllen (Link bleibt gleich).
  </p>
  {#if settings && !settings.google.angemeldet}
    <p class="msg-warn">Erst unter Einrichtung bei Google anmelden.</p>
  {/if}
  <div class="row">
    <ActionButton label="Google Doc aktualisieren" primary run={syncDoc} disabled={!settings?.google.angemeldet} />
    {#if doc?.link}
      <a href={doc.link} target="_blank" rel="noreferrer">Doc öffnen</a>
      <ActionButton label="Link kopieren" run={() => copyText(doc.link)} done="Kopiert." />
    {/if}
  </div>
  {#if doc}<div style="margin-top: 0.75rem"><Value value={doc} /></div>{/if}
</div>

{#if settings?.discord_bot_token}
  <PreviewStep
    title="SF-Review in Discord"
    description="Ein Block pro Zieldorf mit DS-Ultimate-Link, oben der Link zum Google Doc."
    usecase="discord_send"
    args={{ name: op, art: "review" }}
    onDone={() => setStatus("in_review")}
  />
{:else}
  <div class="card muted">Discord-Bot nicht eingerichtet – Review-Text über Claude oder die Konsole.</div>
{/if}

<h2>2. Freigabe</h2>
<div class="card">
  <div class="row">
    {#if approved}
      <span class="pill ok">Von der SF freigegeben</span>
      <ActionButton label="Freigabe zurücknehmen" run={() => setStatus("in_review")} />
    {:else}
      <ActionButton label="Als freigegeben markieren" primary run={() => setStatus("approved")} done="Freigegeben." />
    {/if}
  </div>
</div>

<h2>3. An die Spieler</h2>
{#if !approved}
  <p class="muted">Erst nach der Freigabe.</p>
{:else}
  <PreviewStep
    title="DS-Ultimate-Pläne pro Spieler"
    description="Jeder Spieler bekommt einen Plan nur mit seinen Befehlen."
    usecase="dsu_publish"
    args={{ name: op, fuer: "spieler", aktualisieren: (links?.pro_spieler && Object.keys(links.pro_spieler).length > 0) }}
    confirmLabel="Pläne anlegen"
    onDone={load}
  />
  {#if settings?.discord_bot_token}
    <div class="card">
      <label class="inline"><input type="checkbox" bind:checked={threads} /> In private Threads (sonst Direktnachricht)</label>
    </div>
    {#key threads}
      <PreviewStep
        title="Befehle an jeden Spieler"
        description="Jeder bekommt seine Befehle mit Plan-Link. Schon gesendete Nachrichten werden bearbeitet, nicht doppelt geschickt."
        usecase="discord_send"
        args={{ name: op, art: threads ? "thread" : "dm" }}
      />
    {/key}
    <PreviewStep
      title="Öffentliche Ankündigung"
      description="Grunddaten ohne Ziele, Aufruf zu zusätzlichen Fakes, erwähnt die Rollen von Stamm und Wing."
      usecase="discord_send"
      args={{ name: op, art: "spieler" }}
    />
  {/if}
{/if}

<h2>Für die Stammesführung</h2>
<div class="card">
  <p class="muted">aktion.md: alle Pläne mit Bearbeiten-Links, Discord-fertig zum Kopieren.</p>
  <ActionButton label="aktion.md erzeugen" run={async () => (aktion = await call("aktion_message", { names: [op] }))} />
  {#if aktion}
    {#each aktion.nachrichten as msg, i}
      <div class="row" style="margin-top: 0.75rem; justify-content: space-between">
        <b>Nachricht {i + 1}</b>
        <ActionButton label="Kopieren" run={() => copyText(msg)} done="Kopiert." />
      </div>
      <pre>{msg}</pre>
    {/each}
  {/if}
</div>
