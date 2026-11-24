<script lang="ts">
  import { onMount } from "svelte";
  import { call } from "../lib/api";
  import { toast, errorText } from "../lib/stores";
  import { getDataFolder, setDataFolder, isTauri, type FolderInfo } from "../lib/native";
  import ActionButton from "../lib/ActionButton.svelte";
  import Value from "../lib/Value.svelte";

  type Tab = "welt" | "vorgaben" | "dsu" | "discord" | "google" | "ordner";
  let tab = $state<Tab>("welt");

  let appSettings = $state<any>(null);
  let profile = $state<any>(null);
  let folder = $state<FolderInfo | null>(null);
  let newFolder = $state("");

  // world
  let world = $state("");
  let ownTribes = $state("");
  let wingTribes = $state("");
  let player = $state("");
  let setupResult = $state<any>(null);

  // access
  let discordToken = $state("");
  let dsuKey = $state("");

  // discord
  let discord = $state<any>(null);
  let server = $state("");
  let channels = $state({ review: "", announce: "", commands: "" });
  let members = $state<any>(null);
  let mapping = $state<Record<string, string>>({});
  let initial: Record<string, string> = {};

  const tags = (s: string) => s.split(/[,\s]+/).map((t) => t.trim()).filter(Boolean);

  async function load() {
    appSettings = await call("app_settings");
    folder = await getDataFolder();
    newFolder = folder?.current ?? "";
    if (appSettings.welt) {
      profile = await call("get_profile");
      if (profile && !profile.error) {
        profile.own_text = (profile.own_tribes ?? []).join(", ");
        profile.wing_text = (profile.allied_tribes ?? []).join(", ");
        profile.pref_text = (profile.preferences ?? []).join("\n");
      }
    } else {
      tab = "welt";
    }
  }

  onMount(() => load().catch((e) => toast(errorText(e), "error")));

  const done = $derived({
    welt: !!appSettings?.welt,
    vorgaben: !!profile && !profile.error,
    dsu: !!appSettings?.dsu_api_key,
    discord: !!appSettings?.discord_bot_token,
    google: !!appSettings?.google?.angemeldet,
    ordner: true,
  });

  async function setupWorld() {
    setupResult = await call("setup_world", {
      world,
      own_tribes: tags(ownTribes),
      allied_tribes: tags(wingTribes),
      player,
    });
    await load();
  }

  async function saveProfile() {
    const { own_text, wing_text, pref_text, ...p } = $state.snapshot(profile);
    p.own_tribes = tags(own_text);
    p.allied_tribes = tags(wing_text);
    p.preferences = String(pref_text).split("\n").map((x: string) => x.trim()).filter(Boolean);
    p.world_start = p.world_start || null;
    await call("save_profile", { profile_yaml: JSON.stringify(p) });
    await load();
  }

  async function saveKey(kind: "dsu" | "discord", clear = false) {
    const args =
      kind === "dsu" ? { dsu_api_key: clear ? "" : dsuKey } : { discord_bot_token: clear ? "" : discordToken };
    appSettings = await call("save_app_settings", args);
    dsuKey = "";
    discordToken = "";
  }

  async function discordSetup() {
    discord = await call("discord_setup", {
      server: server || null,
      review_channel: channels.review || null,
      announce_channel: channels.announce || null,
      commands_channel: channels.commands || null,
    });
    if (discord.server) server = discord.server;
    for (const [alias, name] of Object.entries<string>(discord.kanaele ?? {})) {
      if (alias === "review") channels.review = name;
      if (alias === "ankuendigung") channels.announce = name;
      if (alias === "befehle") channels.commands = name;
    }
  }

  async function loadMembers() {
    members = await call("discord_members");
    mapping = {};
    initial = {};
    for (const [name, row] of Object.entries<any>(members.stammesmitglieder ?? {})) {
      const ids = (row.zugeordnet ?? []).map((x: any) => x.id);
      mapping[name] = ids[0] ?? row.vorschlag?.id ?? "";
      initial[name] = ids[0] ?? "";
    }
  }

  async function saveMapping() {
    const changed = Object.fromEntries(Object.entries(mapping).filter(([n, id]) => id !== initial[n]));
    if (Object.keys(changed).length) await call("discord_assign", { mapping: changed });
    await loadMembers();
  }

  const TABS: [Tab, string][] = [
    ["welt", "Welt & Stamm"],
    ["vorgaben", "Vorgaben"],
    ["dsu", "DS Ultimate"],
    ["discord", "Discord"],
    ["google", "Google Doc"],
    ["ordner", "Datenordner"],
  ];
</script>

<h1>Einrichtung</h1>
<div class="steps">
  {#each TABS as [key, label]}
    <button class:current={tab === key} class:done={done[key] && key !== "ordner"} disabled={key !== "welt" && key !== "ordner" && !appSettings?.welt} onclick={() => (tab = key)}>{label}</button>
  {/each}
</div>

{#if !appSettings}
  <p class="muted">Lade …</p>
{:else if tab === "welt"}
  <div class="card">
    {#if appSettings.welt}
      <p><span class="pill ok">eingerichtet</span> Welt <b>{appSettings.welt}</b>. Stamm und Wing änderst du unter „Vorgaben“.</p>
      <p class="hint">Andere Welt? Unten neu einrichten – das Profil der alten Welt bleibt erhalten.</p>
    {/if}
    <div class="grid">
      <label>Welt<input bind:value={world} placeholder="de260" /><span class="hint">Steht in der Adresse im Spiel: de260.die-staemme.de</span></label>
      <label>Eigener Stamm (Tag)<input bind:value={ownTribes} placeholder="RAK" /><span class="hint">Deren Dörfer werden verplant.</span></label>
      <label>Wing (Tags)<input bind:value={wingTribes} placeholder="RAKK, RAKKK" /><span class="hint">Verbündete: ihre DS-Ultimate-Pläne werden gelesen, nie verplant.</span></label>
      <label>Dein Spielername<input bind:value={player} /><span class="hint">optional</span></label>
    </div>
    <p class="hint">Lädt die öffentliche Karte (höchstens einmal pro Stunde).</p>
    <ActionButton label="Welt einrichten" primary run={setupWorld} done="Welt eingerichtet." disabled={!world || !ownTribes} />
    {#if setupResult}<div style="margin-top: 1rem"><Value value={setupResult} /></div>{/if}
  </div>
{:else if tab === "vorgaben"}
  {#if profile && !profile.error}
    <div class="card">
      <p class="hint" style="margin-top: 0">Gilt für die ganze Welt. Off-Größe, Fakes, Abstand und Abschickzeiten stellst du pro Operation im Formular ein.</p>
      <h3>Stamm</h3>
      <div class="grid">
        <label>Eigener Stamm<input bind:value={profile.own_text} /><span class="hint">Tags mit Komma. Diese Dörfer werden verplant.</span></label>
        <label>Wing<input bind:value={profile.wing_text} /><span class="hint">Verbündete Stämme (nur lesen, nie verplanen).</span></label>
        <label>Weltstart<input type="date" bind:value={profile.world_start} /><span class="hint">Für den 10:1-Schutz neuer Spieler.</span></label>
        <label>Truppendaten höchstens (h) alt<input type="number" bind:value={profile.max_troop_age_hours} /><span class="hint">Ältere Daten werden als Warnung gemeldet.</span></label>
      </div>
      <label style="margin-top: 0.75rem">Strategie-Vorlieben (eine pro Zeile)
        <textarea bind:value={profile.pref_text}></textarea>
        <span class="hint">Freitext für Claude, z.B. „Fakes nie aus Dörfern mit eingehenden Angriffen“.</span>
      </label>
      <ActionButton label="Vorgaben speichern" primary run={saveProfile} done="Gespeichert." />
    </div>
  {/if}
{:else if tab === "dsu"}
  <div class="card">
    <p>DS-Ultimate-Pläne legt der Planer auch <b>ohne Key</b> an (über die normale Webseite).</p>
    <p>Mit eigenem API-Key (bekommst du von den DS-Ultimate-Admins) geht das Anlegen stabiler, und du siehst live, wer seine Befehle als „verschickt“ abgehakt hat (Seite „Laufend“, Erinnerungen).</p>
    <p>{#if appSettings.dsu_api_key}<span class="pill ok">Key eingetragen</span>{:else}<span class="pill">kein Key</span>{/if}</p>
    <div class="row">
      <input type="password" bind:value={dsuKey} placeholder="API-Key einfügen" style="min-width: 22rem" />
      <ActionButton label="Speichern" primary run={() => saveKey("dsu")} done="Gespeichert." disabled={!dsuKey} />
      {#if appSettings.dsu_api_key}<ActionButton label="Key löschen" danger run={() => saveKey("dsu", true)} />{/if}
    </div>
    <p class="hint">Wird nur auf diesem Rechner gespeichert. Nie weitergeben.</p>
  </div>
{:else if tab === "discord"}
  <div class="card">
    <h3 style="margin-top: 0">1. Bot-Token</h3>
    {#if appSettings.discord_bot_token}
      <p><span class="pill ok">Token eingetragen</span></p>
    {:else}
      <ol>
        <li><a href="https://discord.com/developers/applications">discord.com/developers/applications</a> → „New Application“ → Name z.B. „AP-Planer“.</li>
        <li>Links „Bot“ → „Reset Token“ → kopieren. Unter „Privileged Gateway Intents“ „Server Members Intent“ einschalten.</li>
      </ol>
    {/if}
    <div class="row">
      <input type="password" bind:value={discordToken} placeholder={appSettings.discord_bot_token ? "neuen Token einfügen" : "Token einfügen"} style="min-width: 22rem" />
      <ActionButton label="Speichern" primary run={() => saveKey("discord")} done="Gespeichert." disabled={!discordToken} />
    </div>
  </div>
  {#if appSettings.discord_bot_token}
    <div class="card">
      <h3 style="margin-top: 0">2. Server und Kanäle</h3>
      {#if !discord}
        <ActionButton label="Server und Kanäle laden" primary run={discordSetup} />
      {:else}
        {#if discord.einladen}
          <p>{discord.hinweis}</p>
          <a href={discord.einladen}>Bot auf den Server einladen</a>
          <ActionButton label="Erneut prüfen" run={discordSetup} />
        {:else}
          <div class="grid">
            <label>Server
              <select bind:value={server} onchange={discordSetup}>
                <option value="">– wählen –</option>
                {#each discord.server_zur_auswahl ?? discord.server_liste ?? [] as s}<option value={s}>{s}</option>{/each}
              </select>
            </label>
            {#if discord.kanaele_liste}
              <label>SF-Review
                <select bind:value={channels.review}>
                  <option value="">–</option>
                  {#each discord.kanaele_liste as c}<option value={c}>#{c}</option>{/each}
                </select>
              </label>
              <label>Private Threads (Befehle)
                <select bind:value={channels.commands}>
                  <option value="">–</option>
                  {#each discord.kanaele_liste as c}<option value={c}>#{c}</option>{/each}
                </select>
                <span class="hint">Jeder Spieler bekommt hier einen privaten Thread; die öffentliche Ankündigung landet auch hier.</span>
              </label>
              <label>Ankündigung (optional)
                <select bind:value={channels.announce}>
                  <option value="">–</option>
                  {#each discord.kanaele_liste as c}<option value={c}>#{c}</option>{/each}
                </select>
              </label>
            {/if}
          </div>
          {#if discord.kanaele_liste}
            <ActionButton label="Kanäle speichern" primary run={discordSetup} done="Gespeichert." />
          {/if}
          {#if discord.rollen}<div style="margin-top: 0.75rem"><b>Rollen für die Ankündigung:</b> <Value value={discord.rollen} /></div>{/if}
          {#if discord.probleme?.length}<p class="msg-error">{discord.probleme.join(" ")}</p>{/if}
          <p class="hint">Damit die SF die privaten Threads sieht: in Discord der SF-Rolle im Kanal das Recht „Threads verwalten“ geben.</p>
        {/if}
      {/if}
    </div>
    <div class="card">
      <h3 style="margin-top: 0">3. Spieler zuordnen</h3>
      <ActionButton label="Mitglieder laden" run={loadMembers} />
      {#if members?.stammesmitglieder}
        <table style="margin-top: 0.75rem">
          <thead><tr><th>DS-Spieler</th><th>Discord</th><th></th></tr></thead>
          <tbody>
            {#each Object.entries(members.stammesmitglieder) as [name, row]}
              <tr>
                <td>{name}</td>
                <td>
                  <select bind:value={mapping[name]}>
                    <option value="">– niemand –</option>
                    {#each members.discord_mitglieder as m}<option value={m.id}>{m.name}</option>{/each}
                  </select>
                </td>
                <td class="muted">{(row as any).zugeordnet?.length ? "gespeichert" : (row as any).vorschlag ? "Vorschlag" : ""}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="hint">Spielen mehrere Leute einen Account, weitere Personen über Claude ergänzen.</p>
        <ActionButton label="Zuordnung speichern" primary run={saveMapping} done="Gespeichert." />
      {/if}
    </div>
  {/if}
{:else if tab === "google"}
  <div class="card">
    <p>Das Spieler-Dokument wird als Google Doc angelegt, für alle mit Link lesbar freigegeben und bei jeder Änderung neu befüllt (gleicher Link).</p>
    {#if !appSettings.google.eingebaut}
      <p class="msg-warn">In dieser Version ist noch kein Google-Zugang eingebaut.</p>
      <p>
        Damit die App Docs selbst anlegen darf, braucht sie <b>einmalig</b> einen eigenen Google-Zugang
        (OAuth-Client) im Google-Konto des Betreuers. Das muss der Betreuer selbst anlegen, weil es eine
        Anmeldung bei Google und das Akzeptieren der Google-Bedingungen braucht – Anleitung in
        <code>docs/google.md</code> (ca. 10 Minuten). Danach klicken alle Spieler nur noch „Mit Google anmelden“.
      </p>
      <p>Bis dahin geht das Doc von Hand: Operation → SF-Review → „Dokument im Browser öffnen“. Oder über Claude.</p>
    {:else if appSettings.google.angemeldet}
      <p><span class="pill ok">angemeldet</span> Der Planer sieht nur die Docs, die er selbst anlegt.</p>
      <ActionButton label="Abmelden" run={async () => { await call("google_logout"); await load(); }} />
    {:else}
      <p>Im Browser öffnet sich die Google-Anmeldung. Danach hierher zurückkommen.</p>
      <ActionButton label="Mit Google anmelden" primary run={async () => { await call("google_login"); await load(); }} done="Bei Google angemeldet." />
    {/if}
  </div>
{:else if tab === "ordner"}
  <div class="card">
    <p>Hier liegen Weltdaten, Truppen, Operationen und Zugänge:</p>
    <pre>{appSettings.datenordner}</pre>
    <p>
      <b>Gemeinsam mit Claude:</b> Claude Desktop (AP-Planner-Plugin) nutzt standardmäßig denselben Ordner
      <code>{folder?.default ?? "~/ap-planner"}</code>. Operationen, die du mit Claude planst, siehst du hier – und umgekehrt.
      Hast du in Claude einen anderen Datenordner eingestellt, wähle hier denselben.
    </p>
    {#if isTauri()}
      <div class="row">
        <input bind:value={newFolder} style="min-width: 28rem" />
        <ActionButton label="Ordner verwenden (App startet neu)" run={() => setDataFolder(newFolder)} disabled={!newFolder || newFolder === folder?.current} />
        {#if folder && folder.current !== folder.default}
          <ActionButton label="Standard" run={() => setDataFolder("")} />
        {/if}
      </div>
    {/if}
  </div>
{/if}
