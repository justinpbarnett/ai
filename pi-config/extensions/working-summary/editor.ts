import { CustomEditor, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { sliceByColumn, stripTerminalSequences, visibleWidth } from "@earendil-works/pi-tui";
import { formatSummary } from "./display.js";
import type { Labels } from "./labels.js";

type EditorFactory = NonNullable<ReturnType<ExtensionContext["ui"]["getEditorComponent"]>>;

const PREFIX = "Summary · ";
const BORDER_LEAD = "── ";
const BORDER_TRAIL = " ";
const SPARE_RULE_CELLS = 1;

export function installSummaryBorder(ctx: ExtensionContext, getLabels: () => Labels): () => void {
	const previous = ctx.ui.getEditorComponent();
	let redraw: (() => void) | undefined;
	const factory: EditorFactory = (tui, theme, keybindings) => {
		redraw = () => tui.requestRender();
		const editor = previous?.(tui, theme, keybindings) ?? new CustomEditor(tui, theme, keybindings, { embedWorkingStatus: true });
		const render = editor.render.bind(editor);
		editor.render = (width) => {
			const lines = render(width);
			const top = lines[0];
			if (!top || !ctx.isIdle() || !("borderColor" in editor) || typeof editor.borderColor !== "function") return lines;

			const emptyRuleCells = /^(─+)(?: ↑ \d+ more ─+)?$/u.exec(stripTerminalSequences(top))?.[1];
			const available = (emptyRuleCells?.length ?? 0) - BORDER_LEAD.length - BORDER_TRAIL.length - SPARE_RULE_CELLS;
			if (available < 1) return lines;
			const labels = getLabels();
			const first = labels.session ?? labels.prompt;
			if (!first) return lines;
			const prefix = visibleWidth(first) + PREFIX.length <= available ? PREFIX : "";
			const summary = formatSummary(labels, available - prefix.length);
			const end = BORDER_LEAD.length + BORDER_TRAIL.length + visibleWidth(prefix + summary);
			const border = editor.borderColor(`${BORDER_LEAD}${prefix}${summary}${BORDER_TRAIL}`) + sliceByColumn(top, end, width - end);
			return [border, ...lines.slice(1)];
		};
		return editor;
	};
	ctx.ui.setEditorComponent(factory);
	return () => redraw?.();
}
