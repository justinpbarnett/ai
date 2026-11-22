import {
  CustomEditor,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import type {
  AutocompleteItem,
  AutocompleteProvider,
  EditorComponent,
} from "@earendil-works/pi-tui";

type CommandToken = { name: string; start: number; end: number };

type InlineEditor = EditorComponent & {
  getLines?(): string[];
  getCursor?(): { line: number; col: number };
  isShowingAutocomplete?(): boolean;
  requestAutocomplete?(options: { force: boolean }): void;
};

function commandTokens(text: string): CommandToken[] {
  const tokens: CommandToken[] = [];
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (char === "\\") {
      index++;
      continue;
    }

    const boundary = index === 0 || /\s/.test(text[index - 1]!);
    const fence =
      char === "~" &&
      /^[ \t]*$/.test(text.slice(text.lastIndexOf("\n", index - 1) + 1, index));
    if (char === "`" || (fence && text.slice(index).startsWith("~~~"))) {
      let end = index + 1;
      while (text[end] === char) end++;
      const marker = text.slice(index, end);
      const closing = text.indexOf(marker, end);
      if (closing === -1) break;
      index = closing + marker.length - 1;
      continue;
    }

    if ((char === '"' || char === "'") && boundary) {
      let closing = index + 1;
      for (; closing < text.length; closing++) {
        if (text[closing] === "\\") closing++;
        else if (text[closing] === char) break;
      }
      index = closing;
      continue;
    }

    if (char !== "/" || !boundary) continue;
    const name = text.slice(index + 1).match(/^[^\s/\\]*/u)?.[0] ?? "";
    const end = index + name.length + 1;
    if (end < text.length && !/\s/.test(text[end]!)) continue;
    tokens.push({ name, start: index, end });
    index = end - 1;
  }
  return tokens;
}

function completionStart(
  lines: string[],
  cursorLine: number,
  cursorCol: number,
): number | undefined {
  const beforeCursor = [
    ...lines.slice(0, cursorLine),
    (lines[cursorLine] ?? "").slice(0, cursorCol),
  ].join("\n");
  if (beforeCursor.trimStart().startsWith("!")) return undefined;
  const tokens = commandTokens(beforeCursor);
  const token = tokens.at(-1);
  if (!token) return undefined;
  const lineStart = beforeCursor.lastIndexOf("\n") + 1;
  if (token.start < lineStart) return undefined;
  // File and attachment completion inside command arguments still belong to Pi.
  if (
    /\s/.test(beforeCursor.slice(token.end)) &&
    /(?:^|\s)[@/~.]\S*$/.test(beforeCursor.slice(token.end))
  ) {
    return undefined;
  }
  return token.start - lineStart;
}

function inlineAutocomplete(
  current: AutocompleteProvider,
): AutocompleteProvider {
  const offsets = new WeakMap<AutocompleteItem, number>();
  return {
    triggerCharacters: current.triggerCharacters,
    async getSuggestions(lines, cursorLine, cursorCol, options) {
      const start = completionStart(lines, cursorLine, cursorCol);
      if (start === undefined)
        return current.getSuggestions(lines, cursorLine, cursorCol, options);
      const suffix = (lines[cursorLine] ?? "").slice(start);
      const suggestions = await current.getSuggestions(
        [suffix],
        0,
        cursorCol - start,
        { ...options, force: false },
      );
      if (!suggestions || options.signal.aborted) {
        return current.getSuggestions(lines, cursorLine, cursorCol, options);
      }
      return {
        ...suggestions,
        items: suggestions.items.map((item) => {
          const copy = { ...item };
          offsets.set(copy, start);
          return copy;
        }),
      };
    },
    applyCompletion(lines, cursorLine, cursorCol, item, prefix) {
      const start = offsets.get(item);
      if (start === undefined)
        return current.applyCompletion(
          lines,
          cursorLine,
          cursorCol,
          item,
          prefix,
        );
      const line = lines[cursorLine] ?? "";
      const result = current.applyCompletion(
        [line.slice(start)],
        0,
        cursorCol - start,
        item,
        prefix,
      );
      const updated = [...lines];
      updated[cursorLine] = line.slice(0, start) + result.lines[0];
      return {
        lines: updated,
        cursorLine,
        cursorCol: start + result.cursorCol,
      };
    },
    shouldTriggerFileCompletion(lines, cursorLine, cursorCol) {
      if (completionStart(lines, cursorLine, cursorCol) !== undefined)
        return true;
      return (
        current.shouldTriggerFileCompletion?.(lines, cursorLine, cursorCol) ??
        true
      );
    },
  };
}

export default function (pi: ExtensionAPI) {
  let autocomplete: AutocompleteProvider | undefined;

  async function promoteCommand(
    text: string,
    includeInteractiveCommands: boolean,
  ): Promise<string> {
    if (text.trimStart().startsWith("!")) return text;
    const tokens = commandTokens(text);
    if (!tokens.length) return text;
    const commandNames = new Set(
      pi
        .getCommands()
        .filter(
          (command) =>
            includeInteractiveCommands || command.source !== "extension",
        )
        .map((command) => command.name),
    );
    const builtinNames = new Set<string>();
    if (includeInteractiveCommands && autocomplete) {
      const suggestions = await autocomplete.getSuggestions(["/"], 0, 1, {
        signal: new AbortController().signal,
      });
      for (const item of suggestions?.items ?? []) {
        if (!commandNames.has(item.value)) builtinNames.add(item.value);
      }
    }
    const token = tokens.find(
      (candidate) =>
        commandNames.has(candidate.name) || builtinNames.has(candidate.name),
    );
    if (!token || token.start === 0) return text;
    const before = text.slice(0, token.start).trim();
    const after = text.slice(token.end).trim();
    const args = builtinNames.has(token.name)
      ? after
      : [before, after].filter(Boolean).join("\n");
    return `/${token.name}${args ? ` ${args}` : ""}`;
  }

  pi.on("input", async (event) => {
    if (event.source === "extension") return;
    const text = await promoteCommand(event.text, false);
    if (text !== event.text) return { action: "transform", text };
  });

  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    ctx.ui.addAutocompleteProvider((current) => {
      autocomplete = current;
      return inlineAutocomplete(current);
    });

    const previous = ctx.ui.getEditorComponent();
    ctx.ui.setEditorComponent((tui, theme, keybindings) => {
      const editor = (previous?.(tui, theme, keybindings) ??
        new CustomEditor(tui, theme, keybindings, {
          embedWorkingStatus: true,
        })) as unknown as InlineEditor;
      let submit = editor.onSubmit;
      Object.defineProperty(editor, "onSubmit", {
        configurable: true,
        get: () => async (text: string) => {
          try {
            const promoted = await promoteCommand(text, true);
            await submit?.(promoted);
          } catch (error) {
            editor.setText(text);
            ctx.ui.notify(
              `Inline command failed: ${error instanceof Error ? error.message : String(error)}`,
              "error",
            );
          }
        },
        set: (handler: EditorComponent["onSubmit"]) => {
          submit = handler;
        },
      });

      // Pi 1.5 excludes '/' from custom natural triggers; this adapter only requests its existing menu.
      if (
        editor.requestAutocomplete &&
        editor.getLines &&
        editor.getCursor &&
        editor.isShowingAutocomplete
      ) {
        const handleInput = editor.handleInput.bind(editor);
        editor.handleInput = (data) => {
          const before = editor.getText();
          const wasShowingAutocomplete = editor.isShowingAutocomplete!();
          handleInput(data);
          if (
            wasShowingAutocomplete ||
            editor.getText() === before ||
            editor.isShowingAutocomplete!()
          )
            return;
          const cursor = editor.getCursor!();
          if (
            completionStart(editor.getLines!(), cursor.line, cursor.col) !==
            undefined
          ) {
            editor.requestAutocomplete!({ force: false });
          }
        };
      } else {
        ctx.ui.notify(
          "This editor does not support automatic inline slash menus; use Tab for completion.",
          "warning",
        );
      }
      return editor;
    });
  });
}
