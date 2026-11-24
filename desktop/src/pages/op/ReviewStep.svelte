<script lang="ts">
  import { call } from "../../lib/api";
  import { copyText } from "../../lib/clipboard";
  import { openExternal } from "../../lib/native";
  import ActionButton from "../../lib/ActionButton.svelte";
  import PreviewStep from "../../lib/PreviewStep.svelte";
  import StateBadge from "../../lib/StateBadge.svelte";
  import DsuLinks from "../../lib/DsuLinks.svelte";

  let { op, status, refresh }: { op: string; status: any; refresh: () => void } = $props();

  let doc = $state<any>(null);
  let reviewText = $state<string[] | null>(null);
  let manualLink = $state("");
</script>

<p class="muted">Die SF bekommt pro Zieldorf einen DS-Ultimate-Plan, das Google Doc und die Review-Nachricht.</p>

<PreviewStep
  title="1. DS-Ultimate-Pläne pro Ziel"
  description="Ein Plan pro Zieldorf. Bei Änderungen werden dieselben Pläne neu befüllt (Links bleiben gleich)."
  usecase="dsu_publish"
  args={{ name: op, fuer: "ziele", aktualisieren: status.dsu_ziele === "veraltet" || status.dsu_ziele === "aktuell" }}
  confirmLabel="Pläne anlegen"
  stepState={status.dsu_ziele}
  waitHint="DS Ultimate wird höflich Plan für Plan befüllt – etwa 5–10 Sekunden pro Plan."
  onDone={refresh}
>
  {#key status.dsu_ziele}<DsuLinks {op} kind="pro_ziel" />{/key}
</PreviewStep>

<div class="card">
  <div class="row" style="justify-content: space-between">
    <h2 style="margin: 0">2. Google Doc</h2>
    <StateBadge state={status.doc} />
  </div>
  <p class="muted">
    Zeigt immer den aktuellen Plan: beim ersten Mal anlegen und für alle mit Link lesbar freigeben, danach
    dasselbe Doc neu befüllen.
  </p>
  {#if !status.google}
    <p>Ohne Google-Login geht es von Hand (ca. 1 Minute):</p>
    <ol>
      <li><ActionButton label="Dokument im Browser öffnen" primary run={() => call("operation_doc", { name: op, open_in_browser: true })} /> → dort <b>Strg+A</b>, <b>Strg+C</b>.</li>
      <li>
        {#if status.doc_link}
          Dein Doc öffnen, <b>alles markieren und ersetzen</b> (Strg+A, Strg+V):
          <button onclick={() => openExternal(status.doc_link)}>Doc öffnen</button>
        {:else}
          <button onclick={() => openExternal("https://docs.new")}>Neues Google Doc (docs.new)</button> → <b>Strg+V</b>.
          Teilen → „Jeder mit dem Link“ → <b>Betrachter</b>.
        {/if}
      </li>
      <li>
        {#if status.doc_link}
          <ActionButton label="Erledigt – Doc ist aktuell" run={async () => { await call("operation_doc", { name: op, geschrieben: true, geteilt: true }); refresh(); }} done="Gemerkt." />
        {:else}
          Link des Docs hier eintragen:
          <div class="row" style="margin-top: 0.4rem">
            <input bind:value={manualLink} placeholder="https://docs.google.com/document/d/…" style="min-width: 26rem" />
            <ActionButton label="Speichern" run={async () => { await call("operation_doc", { name: op, gdoc_id: manualLink, geteilt: true }); manualLink = ""; refresh(); }} disabled={!manualLink} done="Doc gemerkt." />
          </div>
        {/if}
      </li>
    </ol>
    <p class="hint">Automatisch (anlegen, freigeben, neu befüllen) geht es nach einmaliger Google-Einrichtung – siehe Einrichtung → Google Doc.</p>
  {:else}
    <div class="row">
      <ActionButton label="Google Doc aktualisieren" primary run={async () => { doc = await call("google_doc_sync", { name: op }); refresh(); }} done="Google Doc ist aktuell." />
      {#if status.doc_link}
        <button onclick={() => openExternal(status.doc_link)}>Doc öffnen</button>
        <ActionButton label="Link kopieren" run={() => copyText(status.doc_link)} done="Kopiert." />
      {/if}
    </div>
    {#if doc}<p class="hint">{doc.aktion.join(", ")}</p>{/if}
  {/if}
</div>

{#if status.discord}
  <PreviewStep
    title="3. Review-Nachricht an die SF"
    description="Ein Block pro Zieldorf mit DS-Ultimate-Link, oben der Link zum Google Doc. Geht erst, wenn das Doc aktuell ist."
    usecase="discord_send"
    args={{ name: op, art: "review" }}
    stepState={status.review}
    onDone={async () => { await call("set_status", { name: op, status: "in_review" }); refresh(); }}
  />
{:else}
  <div class="card">
    <h2 style="margin-top: 0">3. Review-Nachricht an die SF</h2>
    <p class="muted">Discord-Bot nicht eingerichtet: Text kopieren und selbst posten.</p>
    <ActionButton label="Text erzeugen" run={async () => (reviewText = await call("discord_message", { name: op, art: "review" }))} />
    {#each reviewText ?? [] as part, i}
      <div class="row" style="justify-content: space-between; margin-top: 0.75rem">
        <b>Nachricht {i + 1}</b>
        <ActionButton label="Kopieren" run={() => copyText(part)} done="Kopiert." />
      </div>
      <pre>{part}</pre>
    {/each}
  </div>
{/if}
