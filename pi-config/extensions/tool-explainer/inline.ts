import type { ToolRenderers } from "@earendil-works/pi-coding-agent";
import { Box, Container, Text, truncateToWidth, visibleWidth, type Component } from "@earendil-works/pi-tui";
import { genericActivity, plain, type ToolActivity } from "./evidence.js";

export type InlineRow = { callId: string; failed: boolean; activity?: ToolActivity };
export type Batch = { rows: InlineRow[]; purpose?: string; pending?: boolean; route: string };
type RenderCall = NonNullable<ToolRenderers["renderCall"]>;
type Context = Parameters<RenderCall>[2];
type Theme = Parameters<RenderCall>[1];

type View = { tui: boolean; call?: Component; result?: Component; redraw?: () => void };
const VIEW = Symbol("tool-explainer-row");

function activityLabel(rows: InlineRow[]): string {
	if (rows.length === 1) {
		const { failed, activity = genericActivity } = rows[0]!;
		const { singular, target } = activity;
		const action = singular.charAt(0).toUpperCase() + singular.slice(1);
		const status = failed ? " failed" : target ? "" : " completed";
		return `${action}${status}${target ? `: ${target}` : ""}`;
	}
	const groups = new Map<string, { count: number; plural: string }>();
	for (const { activity = genericActivity } of rows) {
		const { singular, plural } = activity;
		const group = groups.get(singular);
		if (group) group.count++;
		else groups.set(singular, { count: 1, plural });
	}
	return Array.from(groups, ([singular, { count, plural }]) => `${count} ${count === 1 ? singular : plural}`).join(", ");
}

function summaryLabel({ rows, purpose, pending }: Batch): string {
	if (purpose) return rows[0]?.failed ? `Tool failed: ${purpose}` : purpose;
	if (pending && !rows[0]?.failed) return `Summarizing purpose of ${rows.length} ${rows.length === 1 ? "tool call" : "tool calls"}…`;
	return activityLabel(rows);
}

export function batchTitle(batch: Batch) {
	return `${summaryLabel(batch)} · ${batch.route}`;
}

function summary(batch: Batch, theme: Theme, context: Context): Component {
	const background = batch.rows[0]?.failed ? "toolErrorBg" : "toolSuccessBg";
	const box = new Box(context.outputPad, 0, (text) => theme.bg(background, text));
	const hint = context.keyHint("app.tools.expand", "to expand");
	const suffix = hint ? `${theme.fg("muted", " · ")}${hint}` : "";
	const suffixWidth = visibleWidth(suffix);
	const text = theme.fg(background === "toolErrorBg" ? "error" : "accent", summaryLabel(batch));
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
	private readonly rows = new Map<string, Batch | null>();
	private readonly views = new Map<string, WeakRef<View>>();
	private readonly unfinished = new Set<string>();

	track(id: string) {
		if (this.rows.has(id)) return;
		this.rows.set(id, null);
		this.unfinished.add(id);
	}

	place(batch: Batch) {
		for (const { callId } of batch.rows) {
			this.rows.set(callId, batch);
			this.unfinished.delete(callId);
		}
		for (const { callId } of batch.rows) this.redraw(callId);
	}

	update(batch: Batch) {
		const anchor = batch.rows.at(-1)?.callId;
		if (anchor !== undefined && this.rows.get(anchor) === batch) this.redraw(anchor);
	}

	releaseUnfinished() {
		for (const id of this.unfinished) this.remove(id);
	}

	retain(callIds: Set<string>) {
		for (const [id, batch] of this.rows) {
			if (!callIds.has(id) || batch?.rows.some(({ callId }) => !callIds.has(callId))) this.remove(id);
		}
		for (const id of this.views.keys()) if (!callIds.has(id)) this.views.delete(id);
	}

	clear(redraw: boolean) {
		if (redraw) for (const id of this.rows.keys()) this.remove(id);
		else {
			this.rows.clear();
			this.views.clear();
		}
		this.unfinished.clear();
	}

	private redraw(id: string) {
		this.views.get(id)?.deref()?.redraw?.();
	}

	private remove(id: string) {
		this.rows.delete(id);
		this.unfinished.delete(id);
		this.redraw(id);
	}

	wrap(name: string, native: ToolRenderers | undefined): ToolRenderers {
		const viewFor = (context: Context): View => {
			// Real TUI rows first render before execution starts. HTML export starts with executionStarted set.
			return context.state[VIEW] ??= { tui: context.isPartial && !context.executionStarted } satisfies View;
		};
		const batchFor = (view: View, context: Context): Batch | null | undefined => {
			if (!view.tui) return;
			if (this.views.get(context.toolCallId)?.deref() !== view) {
				view.redraw = context.invalidate;
				this.views.set(context.toolCallId, new WeakRef(view));
			}
			return this.rows.get(context.toolCallId);
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
				const batch = batchFor(view, context);
				if (batch !== undefined && !context.expanded) {
					return batch?.rows.at(-1)?.callId === context.toolCallId
						? summary(batch, theme, context) : new Container();
				}
				const raw = native?.renderCall?.(args, theme, { ...context, lastComponent: view.call })
					?? new Text(`${theme.fg("toolTitle", theme.bold(plain(name)))}${args ? ` ${plain(JSON.stringify(args, null, context.expanded ? 2 : undefined))}` : ""}`, 0, 0);
				view.call = raw;
				return rawShell(raw, theme, context, view);
			},
			renderResult: (result, options, theme, context) => {
				const view = viewFor(context);
				if (batchFor(view, context) !== undefined && !options.expanded) return new Container();
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
