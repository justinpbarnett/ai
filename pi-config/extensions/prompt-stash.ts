import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  let stash: string | undefined;

  function restore(ctx: ExtensionContext) {
    if (stash === undefined) return;
    const current = ctx.ui.getEditorText();
    ctx.ui.setEditorText(current ? `${current}\n${stash}` : stash);
    stash = undefined;
    ctx.ui.setStatus("prompt-stash", undefined);
  }

  pi.registerShortcut("ctrl+alt+s", {
    description: "Stash or restore the current prompt",
    handler: async (ctx) => {
      if (stash !== undefined) {
        restore(ctx);
        return;
      }
      const text = ctx.ui.getEditorText();
      if (!text) return;
      stash = text;
      ctx.ui.setEditorText("");
      ctx.ui.setStatus("prompt-stash", "Prompt stashed (Ctrl+Alt+S to restore)");
    },
  });

  pi.on("input", (event, ctx) => {
    if (event.source === "interactive" && stash !== undefined) restore(ctx);
  });
}
