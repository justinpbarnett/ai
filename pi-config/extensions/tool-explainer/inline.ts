import type { ToolRenderers } from "@earendil-works/pi-coding-agent";
import { Box, Container, Text, truncateToWidth, visibleWidth, type Component } from "@earendil-works/pi-tui";
import { plain, type AutoRow } from "./evidence.js";

export type InlineRow = AutoRow & { callId: string };
export type Batch = { rows: InlineRow[]; summary: string; route: string };
type RenderCall = NonNullable<ToolRenderers["renderCall"]>;
type Context = Parameters<RenderCall>[2];
type Theme = Parameters<RenderCall>[1];

type View = { tui: boolean; call?: Component; result?: Component; redraw?: () => void };
type Row = { batch?: Batch; view?: WeakRef<View> };
const VIEW = Symbol("tool-explainer-row");

export function batchTitle(batch: Batch) {
	return `${batch.summary} · ${batch.route}`;
}

function summary(batch: Batch, theme: Theme, context: Context): Component {
	const background = batch.rows.some(({ facts }) => facts.failed) ? "toolErrorBg" : "toolSuccessBg";
	const box = new Box(context.outputPad, 0, (text) => theme.bg(background, text));
	const hint = context.keyHint("app.tools.expand", "to expand");
	const suffix = hint ? `${theme.fg("muted", " · ")}${hint}` : "";
	const suffixWidth = visibleWidth(suffix);
	const text = theme.fg(background === "toolErrorBg" ? "error" : "accent", batch.summary);
	box.addChild({
		render(width) {
			const labelWidth = width - suffixWidth;
			return [labelWidth > 8 ? truncateToWidth(text, labelWidth) + suffix : truncateToWidth(text, width)];
		},
		invalidate() {},
	});
	return box;
}

export class InlineToolOutput {
	private readonly rows = new Map<string, Row>();
	private readonly unfinished = new Set<string>();

	track(id: string) {
		if (this.rows.has(id)) return;
		this.rows.set(id, {});
		this.unfinished.add(id);
	}

	place(batch: Batch) {
		for (const { callId } of batch.rows) {
			const row = this.rows.get(callId) ?? {};
			row.batch = batch;
			this.rows.set(callId, row);
			this.unfinished.delete(callId);
		}
		for (const { callId } of batch.rows) this.redraw(callId);
	}

	update(batch: Batch) {
		const anchor = batch.rows.at(-1)?.callId;
		if (anchor !== undefined && this.rows.get(anchor)?.batch === batch) this.redraw(anchor);
	}

	releaseUnfinished() {
		for (const id of this.unfinished) this.remove(id);
	}

	retain(callIds: Set<string>) {
		for (const [id, row] of this.rows) {
			if (!callIds.has(id) || row.batch?.rows.some(({ callId }) => !callIds.has(callId))) this.remove(id);
		}
	}

	clear(redraw: boolean) {
		if (redraw) for (const id of this.rows.keys()) this.remove(id);
		else this.rows.clear();
		this.unfinished.clear();
	}

	private redraw(id: string) {
		this.rows.get(id)?.view?.deref()?.redraw?.();
	}

	private remove(id: string) {
		const view = this.rows.get(id)?.view?.deref();
		this.rows.delete(id);
		this.unfinished.delete(id);
		view?.redraw?.();
	}

	wrap(name: string, native: ToolRenderers | undefined): ToolRenderers {
		const viewFor = (context: Context): View => {
			// Real TUI rows first render before execution starts. HTML export starts with executionStarted set.
			return context.state[VIEW] ??= { tui: context.isPartial && !context.executionStarted } satisfies View;
		};
		const rowFor = (view: View, context: Context): Row | undefined => {
			if (!view.tui) return;
			const row = this.rows.get(context.toolCallId);
			if (row) {
				view.redraw = context.invalidate;
				if (row.view?.deref() !== view) row.view = new WeakRef(view);
			}
			return row;
		};
		const rawShell = (component: Component, theme: Theme, context: Context, view: View) => {
			if (!view.tui || native?.renderShell === "self") return component;
			const background = context.isPartial ? "toolPendingBg" : context.isError ? "toolErrorBg" : "toolSuccessBg";
			const box = new Box(context.outputPad, 0, (text) => theme.bg(background, text));
			box.addChild(component);
			return box;
		};
		return {
			renderShell: "self",
			renderCall: (args, theme, context) => {
				const view = viewFor(context);
				const row = rowFor(view, context);
				if (row && !context.expanded) {
					return row.batch?.rows.at(-1)?.callId === context.toolCallId
						? summary(row.batch, theme, context) : new Container();
				}
				const raw = native?.renderCall?.(args, theme, { ...context, lastComponent: view.call })
					?? new Text(`${theme.fg("toolTitle", theme.bold(plain(name)))}${args ? ` ${plain(JSON.stringify(args, null, context.expanded ? 2 : undefined))}` : ""}`, 0, 0);
				view.call = raw;
				return rawShell(raw, theme, context, view);
			},
			renderResult: (result, options, theme, context) => {
				const view = viewFor(context);
				if (rowFor(view, context) && !options.expanded) return new Container();
				const raw = native?.renderResult?.(result, options, theme, { ...context, lastComponent: view.result });
				if (raw) {
					view.result = raw;
					return rawShell(raw, theme, context, view);
				}
				const output = result.content.flatMap((part) => part.type === "text" ? [plain(part.text)] : []).join("\n");
				if (!output) return new Container();
				const lines = output.split("\n");
				const text = options.expanded ? output : lines.slice(0, 10).join("\n");
				const more = !options.expanded && lines.length > 10 ? `\n… ${context.keyHint("app.tools.expand", "for raw output")}` : "";
				return rawShell(new Text(theme.fg("toolOutput", text + more), 0, 0), theme, context, view);
			},
		};
	}
}
