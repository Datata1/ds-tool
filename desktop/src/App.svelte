<script lang="ts">
  import { onMount } from "svelte";
  import { page, toasts } from "./lib/stores";
  import { health } from "./lib/api";
  import { interceptLinks } from "./lib/native";
  import Start from "./pages/Start.svelte";
  import Setup from "./pages/Setup.svelte";
  import Troops from "./pages/Troops.svelte";
  import Operations from "./pages/Operations.svelte";
  import Operation from "./pages/Operation.svelte";

  let ready = $state(false);
  let failed = $state("");
  let version = $state("");

  onMount(() => interceptLinks());

  onMount(async () => {
    for (let i = 0; i < 60; i++) {
      try {
        version = (await health()).version;
        ready = true;
        return;
      } catch (err) {
        failed = err instanceof Error ? err.message : String(err);
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
  });

  const nav = [
    { name: "start", label: "Übersicht" },
    { name: "ops", label: "Operationen" },
    { name: "troops", label: "Truppen" },
    { name: "setup", label: "Einrichtung" },
  ] as const;
</script>

<div class="shell">
  <aside>
    <div class="brand">AP-Planer</div>
    {#each nav as item}
      <button
        class="nav"
        class:active={$page.name === item.name ||
          (item.name === "ops" && $page.name === "op")}
        onclick={() => page.set({ name: item.name } as any)}>{item.label}</button
      >
    {/each}
    <div class="foot muted">{version ? `Version ${version}` : ""}</div>
  </aside>
  <main>
    {#if !ready}
      <div class="card">
        <p>Planer wird gestartet …</p>
        {#if failed}<p class="muted">{failed}</p>{/if}
      </div>
    {:else if $page.name === "start"}
      <Start />
    {:else if $page.name === "setup"}
      <Setup />
    {:else if $page.name === "troops"}
      <Troops />
    {:else if $page.name === "ops"}
      <Operations />
    {:else if $page.name === "op"}
      {#key `${$page.op}:${$page.step ?? ""}`}<Operation op={$page.op} step={$page.step} />{/key}
    {/if}
  </main>
</div>

<div class="toasts">
  {#each $toasts as t (t.id)}
    <div class="toast {t.kind}">{t.text}</div>
  {/each}
</div>

<style>
  /* fixed sidebar + offset content: works the same in WebKit (Linux/macOS) and WebView2 */
  .shell { min-height: 100vh; }
  aside {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 200px;
    overflow-y: auto;
    overflow-x: hidden;
    background: var(--panel);
    border-right: 1px solid var(--border);
    padding: 1rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    z-index: 5;
  }
  .brand { font-weight: 700; font-size: 1.2rem; color: var(--accent); margin: 0 0.5rem 1rem; }
  .nav { text-align: left; border: none; background: none; padding: 0.55rem 0.75rem; }
  .nav.active { background: var(--bg); font-weight: 600; }
  .foot { margin-top: auto; font-size: 0.8rem; padding: 0 0.5rem; }
  main { margin-left: 200px; padding: 1.5rem 2rem; max-width: 1400px; }
  .toasts { position: fixed; right: 1rem; bottom: 1rem; display: flex; flex-direction: column; gap: 0.5rem; z-index: 10; }
  .toast { background: var(--panel); border: 1px solid var(--border); border-left: 4px solid var(--accent); padding: 0.6rem 0.9rem; border-radius: 6px; max-width: 420px; box-shadow: 0 2px 8px rgba(0,0,0,.15); }
  .toast.ok { border-left-color: var(--ok); }
  .toast.error { border-left-color: var(--error); }
</style>
