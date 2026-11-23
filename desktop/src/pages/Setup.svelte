<script lang="ts">
  import { onMount } from "svelte";
  import { call } from "../lib/api";
  import { toast, errorText } from "../lib/stores";
  import ActionButton from "../lib/ActionButton.svelte";
  import Value from "../lib/Value.svelte";

  let appSettings = $state<any>(null);
  let profile = $state<any>(null);
  let check = $state<any>(null);

  // first setup
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
  let reviewChannel = $state("");
  let announceChannel = $state("");
  let commandsChannel = $state("");
  let members = $state<any>(null);
  let mapping = $state<Record<string, string>>({});
  let initial: Record<string, string> = {};

  const tags = (s: string) => s.split(/[,\s]+/).map((t) => t.trim()).filter(Boolean);

  async function load() {
    appSettings = await call("app_settings");
    if (appSettings.welt) {
      profile = await call("get_profile");
      check = await call("setup_check");
    }
  }

  onMount(() => load().catch((e) => toast(errorText(e), "error")));

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
    const p = { ...profile };
    p.own_tribes = typeof p.own_tribes === "string" ? tags(p.own_tribes) : p.own_tribes;
    p.allied_tribes = typeof p.allied_tribes === "string" ? tags(p.allied_tribes) : p.allied_tribes;
    p.preferences = typeof p.preferences === "string"
      ? p.preferences.split("\n").map((x: string) => x.trim()).filter(Boolean)
      : p.preferences;
    await call("save_profile", { profile_yaml: JSON.stringify(p) });
    await load();
  }

  async function saveAccess() {
    const args: Record<string, string> = {};
    if (discordToken) args.discord_bot_token = discordToken;
    if (dsuKey) args.dsu_api_key = dsuKey;
    appSettings = await call("save_app_settings", args);
    discordToken = "";
    dsuKey = "";
  }

  async function discordSetup() {
    discord = await call("discord_setup", {
      server: server || null,
      review_channel: reviewChannel || null,
      announce_channel: announceChannel || null,
      commands_channel: commandsChannel || null,
    });
  }

  async function loadMembers() {
    members = await call("discord_members");
    mapping = {};
    for (const [name, row] of Object.entries<any>(members.stammesmitglieder ?? {})) {
      const ids = (row.zugeordnet ?? []).map((x: any) => x.id);
      mapping[name] = ids[0] ?? row.vorschlag?.id ?? "";
      initial[name] = ids[0] ?? "";
    }
  }

  async function saveMapping() {
    // only changed rows (keeps extra people of shared accounts); empty = remove
    const changed = Object.fromEntries(
      Object.entries(mapping).filter(([name, id]) => id !== initial[name]),
    );
    if (Object.keys(changed).length) await call("discord_assign", { mapping: changed });
    await loadMembers();
  }
</script>

<h1>Einrichtung</h1>

{#if appSettings && !appSettings.welt}
  <div class="card">
    <h2>1. Welt und Stamm</h2>
    <div class="grid">
      <label>Welt<input bind:value={world} placeholder="de260" /></label>
      <label>Eigener Stamm (Tag)<input bind:value={ownTribes} placeholder="RAK" /></label>
      <label>Wing (Tags, mit Komma)<input bind:value={wingTribes} placeholder="RAKK, RAKKK" /></label>
      <label>Dein Spielername (optional)<input bind:value={player} /></label>
    </div>
    <p class="muted">Die Weltdaten werden einmal geladen (öffentliche Karte, höchstens 1× pro Stunde).</p>
    <ActionButton label="Einrichten" primary run={setupWorld} done="Welt eingerichtet." disabled={!world || !ownTribes} />
    {#if setupResult}<div style="margin-top: 1rem"><Value value={setupResult} /></div>{/if}
  </div>
{/if}

{#if profile && !profile.error}
  <div class="card">
    <h2>Vorgaben (gelten für jede Operation)</h2>
    <div class="grid">
      <label>Eigener Stamm<input value={(profile.own_tribes ?? []).join(", ")} oninput={(e) => (profile.own_tribes = (e.target as HTMLInputElement).value)} /></label>
      <label>Wing<input value={(profile.allied_tribes ?? []).join(", ")} oninput={(e) => (profile.allied_tribes = (e.target as HTMLInputElement).value)} /></label>
      <label>Volle Off ab (Off-Einwohner)<input type="number" bind:value={profile.off_min_pop} /></label>
      <label>Fusions-Off ab<input type="number" bind:value={profile.fusion_min_pop} /></label>
      <label>Fake-Einheit
        <select bind:value={profile.fake_unit}>
          <option value="ram">Ramme</option>
          <option value="catapult">Katapult</option>
        </select>
      </label>
      <label>Abschicken ab<input type="time" step="1" bind:value={profile.send_window.start} /></label>
      <label>Abschicken bis<input type="time" step="1" bind:value={profile.send_window.end} /></label>
      <label>Truppendaten max. Alter (h)<input type="number" bind:value={profile.max_troop_age_hours} /></label>
      <label>Abstand Offs (s)<input type="number" bind:value={profile.off_send_gap_s} /></label>
      <label>Weltstart<input type="date" bind:value={profile.world_start} /></label>
    </div>
    <label style="margin-top: 0.75rem">Strategie-Vorlieben (eine pro Zeile)
      <textarea value={(profile.preferences ?? []).join("\n")} oninput={(e) => (profile.preferences = (e.target as HTMLTextAreaElement).value)}></textarea>
    </label>
    <ActionButton label="Vorgaben speichern" primary run={saveProfile} done="Gespeichert." />
  </div>
{/if}

{#if appSettings}
  <div class="card">
    <h2>Zugänge</h2>
    <p class="muted">Werden nur auf diesem Rechner gespeichert ({appSettings.datenordner}).</p>
    <div class="grid">
      <label>Discord-Bot-Token {appSettings.discord_bot_token ? "✓ eingetragen" : ""}
        <input type="password" bind:value={discordToken} placeholder="neu eintragen" />
      </label>
      <label>DS-Ultimate-API-Key (optional) {appSettings.dsu_api_key ? "✓ eingetragen" : ""}
        <input type="password" bind:value={dsuKey} placeholder="neu eintragen" />
      </label>
    </div>
    <ActionButton label="Speichern" run={saveAccess} done="Zugänge gespeichert." disabled={!discordToken && !dsuKey} />

    <h3>Google (für das Spieler-Dokument)</h3>
    {#if !appSettings.google.eingebaut}
      <p class="muted">In dieser Version ist kein Google-Zugang eingebaut.</p>
    {:else if appSettings.google.angemeldet}
      <p><span class="pill ok">angemeldet</span> Der Planer sieht nur die Docs, die er selbst anlegt.</p>
      <ActionButton label="Abmelden" run={async () => { await call("google_logout"); await load(); }} />
    {:else}
      <p>Im Browser öffnet sich die Google-Anmeldung. Danach hierher zurückkommen.</p>
      <ActionButton label="Mit Google anmelden" primary run={async () => { await call("google_login"); await load(); }} done="Bei Google angemeldet." />
    {/if}
  </div>

  {#if appSettings.discord_bot_token}
    <div class="card">
      <h2>Discord</h2>
      <p class="muted">Server und Kanäle einfach per Name. Ohne Angaben zeigt der Planer, was es gibt.</p>
      <div class="grid">
        <label>Server<input bind:value={server} /></label>
        <label>Kanal SF-Review<input bind:value={reviewChannel} /></label>
        <label>Kanal Ankündigung<input bind:value={announceChannel} /></label>
        <label>Kanal private Threads<input bind:value={commandsChannel} placeholder="befehle" /></label>
      </div>
      <ActionButton label="Discord prüfen / speichern" run={discordSetup} />
      {#if discord}<div style="margin-top: 1rem"><Value value={discord} /></div>{/if}

      <h3>Spieler zuordnen (DS-Name → Discord)</h3>
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
                    {#each members.discord_mitglieder as m}
                      <option value={m.id}>{m.name}</option>
                    {/each}
                  </select>
                </td>
                <td class="muted">
                  {#if (row as any).zugeordnet?.length}gespeichert{:else if (row as any).vorschlag}Vorschlag{/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="muted">Spielen mehrere Leute einen Account, die weiteren Personen über Claude oder die Konsole ergänzen.</p>
        <ActionButton label="Zuordnung speichern" primary run={saveMapping} done="Gespeichert." />
      {/if}
    </div>
  {/if}
{/if}

{#if check}
  <div class="card">
    <h2>Stand der Einrichtung</h2>
    <Value value={check} />
  </div>
{/if}
