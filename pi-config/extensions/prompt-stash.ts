import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const STASH_ENTRY = "prompt-stash";
const STASH_STATUS = "Prompt stashed (Ctrl+S to restore)";

type StashEntry = { text: string | null };

export default function (pi: ExtensionAPI) {
  let stash: string | undefined;

  function setStash(ctx: ExtensionContext, text: string | undefined) {
    stash = text;
    pi.appendEntry<StashEntry>(STASH_ENTRY, { text: text ?? null });
    ctx.ui.setStatus("prompt-stash", text === undefined ? undefined : STASH_STATUS);
  }

  function restore(ctx: ExtensionContext) {
    if (stash === undefined) return;
    const current = ctx.ui.getEditorText();
    ctx.ui.setEditorText(current ? `${current}\n${stash}` : stash);
    setStash(ctx, undefined);
  }

  pi.on("session_start", (_event, ctx) => {
    const saved = ctx.sessionManager
      .getBranch()
      .findLast((entry) => entry.type === "custom" && entry.customType === STASH_ENTRY);
    const text = saved?.type === "custom" ? (saved.data as StashEntry | undefined)?.text : undefined;
    stash = typeof text === "string" ? text : undefined;
    ctx.ui.setStatus("prompt-stash", stash === undefined ? undefined : STASH_STATUS);
  });

  pi.registerShortcut("ctrl+s", {
    description: "Stash or restore the current prompt",
    handler: async (ctx) => {
      if (stash !== undefined) {
        restore(ctx);
        return;
      }
      const text = ctx.ui.getEditorText();
      if (!text) return;
      setStash(ctx, text);
      ctx.ui.setEditorText("");
    },
  });

  pi.on("input", (event, ctx) => {
    if (event.source === "interactive" && stash !== undefined) restore(ctx);
  });
}
