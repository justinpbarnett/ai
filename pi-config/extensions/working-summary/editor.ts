import { CustomEditor, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { sliceByColumn, stripTerminalSequences, visibleWidth } from "@earendil-works/pi-tui";
import { formatSummary, type Labels } from "./labels.js";

const PREFIX = "Summary · ";

export function installSummaryBorder(ctx: ExtensionContext, getLabels: () => Labels): () => void {
	const previous = ctx.ui.getEditorComponent();
	let redraw: (() => void) | undefined;
	ctx.ui.setEditorComponent((tui, theme, keybindings) => {
		redraw = () => tui.requestRender();
		const editor = previous?.(tui, theme, keybindings) ?? new CustomEditor(tui, theme, keybindings, { embedWorkingStatus: true });
		const render = editor.render.bind(editor);
		editor.render = (width) => {
			const lines = render(width);
			const top = lines[0];
			if (!top || !ctx.isIdle() || !("borderColor" in editor) || typeof editor.borderColor !== "function") return lines;

			// Only replace empty rule cells; leave native indicators and the scroll marker alone.
			const rule = /^(─+)(?: ↑ \d+ more ─+)?$/u.exec(stripTerminalSequences(top))?.[1];
			const available = (rule?.length ?? 0) - 5;
			if (available < 1) return lines;
			const labels = getLabels();
			const first = labels.session ?? labels.prompt;
			if (!first) return lines;
			const prefix = visibleWidth(first) + PREFIX.length <= available ? PREFIX : "";
			const summary = formatSummary(labels, available - prefix.length);
			const end = 4 + visibleWidth(prefix + summary);
			const border = editor.borderColor(`── ${prefix}${summary} `) + sliceByColumn(top, end, width - end);
			return [border, ...lines.slice(1)];
		};
		return editor;
	});
	return () => redraw?.();
}
