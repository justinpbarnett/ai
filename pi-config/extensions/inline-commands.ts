import {
  CustomEditor,
  type ExtensionAPI,
  type ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import type {
  AutocompleteItem,
  AutocompleteProvider,
  EditorComponent,
} from "@earendil-works/pi-tui";

type CommandToken = { name: string; start: number; end: number };

interface AutocompleteEditor extends EditorComponent {
  getLines(): string[];
  getCursor(): { line: number; col: number };
  isShowingAutocomplete(): boolean;
  requestAutocomplete(options: { force: boolean }): void;
}

function skipFence(text: string, start: number): number | undefined {
  const marker = text[start];
  if (marker !== "`" && marker !== "~") return;
  let lineStart = start;
  while (start - lineStart < 4 && text[lineStart - 1] === " ") lineStart--;
  if (start - lineStart === 4 || (lineStart > 0 && text[lineStart - 1] !== "\n")) return;
  let markerEnd = start;
  while (text[markerEnd] === marker) markerEnd++;
  const length = markerEnd - start;
  if (length < 3) return;
  const openingEnd = text.indexOf("\n", markerEnd);
  const info = text.slice(markerEnd, openingEnd === -1 ? text.length : openingEnd);
  if (marker === "`" && info.includes("`")) return;
  if (openingEnd === -1) return text.length;
  const closing = new RegExp(`^ {0,3}${marker}{${length},}[ \\t]*\\r?$`, "gm");
  closing.lastIndex = openingEnd + 1;
  const match = closing.exec(text);
  return match ? closing.lastIndex : text.length;
}

function skipInlineCode(text: string, start: number): number {
  const runs = /`+/g;
  runs.lastIndex = start;
  const length = runs.exec(text)![0].length;
  const openingEnd = runs.lastIndex;
  for (let match = runs.exec(text); match; match = runs.exec(text)) {
    if (match[0].length === length) return runs.lastIndex;
  }
  return openingEnd;
}

function skipQuotedWord(text: string, start: number): number {
  const quote = text[start];
  for (let index = start + 1; index < text.length; index++) {
    if (text[index] === "\\") index++;
    else if (text[index] === quote) return index + 1;
  }
  return start + 1;
}

function skipLiteral(text: string, start: number, boundary: boolean): number | undefined {
  const char = text[start];
  if (char === "\\") return start + 2;
  const fenceEnd = skipFence(text, start);
  if (fenceEnd !== undefined) return fenceEnd;
  if (char === "`") return skipInlineCode(text, start);
  if (boundary && (char === '"' || char === "'")) return skipQuotedWord(text, start);
}

function commandTokens(text: string): CommandToken[] {
  const tokens: CommandToken[] = [];
  const commandName = /[^\s/\\]*/uy;
  for (let index = 0; index < text.length; index++) {
    const boundary = index === 0 || /\s/.test(text[index - 1]!);
    const literalEnd = skipLiteral(text, index, boundary);
    if (literalEnd !== undefined) {
      index = literalEnd - 1;
      continue;
    }
    if (text[index] !== "/" || !boundary) continue;
    commandName.lastIndex = index + 1;
    const name = commandName.exec(text)![0];
    const end = commandName.lastIndex;
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
  const afterCommand = beforeCursor.slice(token.end);
  const completingFileArgument =
    /\s/.test(afterCommand) && /(?:^|\s)[@/~.]\S*$/.test(afterCommand);
  if (completingFileArgument) {
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

function wrapSubmit(
  editor: EditorComponent,
  promote: (text: string) => Promise<string>,
  ui: ExtensionContext["ui"],
): void {
  let submit = editor.onSubmit;
  Object.defineProperty(editor, "onSubmit", {
    configurable: true,
    get: () => async (text: string) => {
      let promoted: string;
      try {
        promoted = await promote(text);
      } catch (error) {
        editor.setText(text);
        ui.notify(
          `Inline command failed: ${error instanceof Error ? error.message : String(error)}`,
          "error",
        );
        return;
      }
      await submit?.(promoted);
    },
    set: (handler: EditorComponent["onSubmit"]) => {
      submit = handler;
    },
  });
}

function supportsAutocomplete(editor: EditorComponent): editor is AutocompleteEditor {
  const candidate = editor as Partial<AutocompleteEditor>;
  return Boolean(
    candidate.requestAutocomplete && candidate.getLines &&
    candidate.getCursor && candidate.isShowingAutocomplete,
  );
}

function enableInlineMenu(editor: AutocompleteEditor): void {
  // Pi excludes '/' from custom natural triggers; this adapter only requests its existing menu.
  const handleInput = editor.handleInput.bind(editor);
  editor.handleInput = (data) => {
    const before = editor.getText();
    const wasShowingAutocomplete = editor.isShowingAutocomplete();
    handleInput(data);
    if (
      wasShowingAutocomplete ||
      editor.getText() === before ||
      editor.isShowingAutocomplete()
    ) return;
    const { line, col } = editor.getCursor();
    if (completionStart(editor.getLines(), line, col) !== undefined) {
      editor.requestAutocomplete({ force: false });
    }
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
        }));
      wrapSubmit(editor, (text) => promoteCommand(text, true), ctx.ui);
      if (supportsAutocomplete(editor)) {
        enableInlineMenu(editor);
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
