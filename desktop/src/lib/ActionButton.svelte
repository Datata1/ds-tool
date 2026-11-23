<script lang="ts">
  import { toast, errorText } from "./stores";

  let {
    label,
    run,
    primary = false,
    danger = false,
    disabled = false,
    done = "",
  }: {
    label: string;
    run: () => Promise<unknown>;
    primary?: boolean;
    danger?: boolean;
    disabled?: boolean;
    done?: string;
  } = $props();

  let busy = $state(false);

  async function click() {
    busy = true;
    try {
      await run();
      if (done) toast(done, "ok");
    } catch (err) {
      toast(errorText(err), "error");
    } finally {
      busy = false;
    }
  }
</script>

<button class:primary class:danger disabled={busy || disabled} onclick={click}>
  {busy ? "Bitte warten …" : label}
</button>
