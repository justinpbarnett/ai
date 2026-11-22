import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { ToolRenderers } from "@earendil-works/pi-coding-agent";
import { Box, Container, Text, truncateToWidth, visibleWidth, wrapTextWithAnsi, type Component } from "@earendil-works/pi-tui";
import { genericActivity, plain, toolActivity, type Invocation, type ToolActivity } from "./evidence.js";

type RenderCall = NonNullable<ToolRenderers["renderCall"]>;
type Context = Parameters<RenderCall>[2];
type Theme = Parameters<RenderCall>[1];

type CallState = { activity: ToolActivity; purpose?: string; pending?: boolean; phase: "queued" | "running" | "done" | "failed" };
type Group = { ids: string[] };
type BatchStatus = { running: number; done: number; failed: number };
type LiveBatch = { id: string; status: BatchStatus; rows: Set<string> };
type View = { tui: boolean; call?: Component; result?: Component; redraw?: () => void };

const VIEW = Symbol("tool-explainer-row");
const CALL_LINES = 3;
const NATIVE_TOOLS = new Set(["edit", "write"]);

export function shownNatively(toolName: string): boolean {
	return NATIVE_TOOLS.has(toolName);
}

export function activityLabel({ singular, target }: ToolActivity = genericActivity): string {
	return `${singular.charAt(0).toUpperCase()}${singular.slice(1)}${target ? `: ${target}` : ""}`;
}

function callLabel(state: CallState): string {
	const text = state.purpose ?? activityLabel(state.activity);
	return state.phase === "failed" ? `Tool failed: ${text}` : text;
}

function shown(message: AgentMessage): boolean {
	if (message.role === "toolResult") return false;
	if (message.role === "custom") return message.display;
	if (message.role !== "assistant") return true;
	return message.content.some((block) =>
		(block.type === "text" && block.text.trim()) || (block.type === "thinking" && block.thinking.trim()));
}

function withHint(text: string, theme: Theme, context: Context): string {
	const hint = context.keyHint("app.tools.expand", "to expand");
	return hint ? `${text}${theme.fg("muted", " · ")}${hint}` : text;
}

function liveView(state: CallState, status: BatchStatus, call: Component, theme: Theme, context: Context): Component {
	const box = new Box(context.outputPad, 0, (text) => theme.bg("toolPendingBg", text));
	const label = theme.fg("accent", `${state.phase === "running" ? "Running: " : ""}${callLabel(state)}${state.pending ? "…" : ""}`);
	const separator = theme.fg("muted", " · ");
	const progress = [
		status.running > 1 ? theme.fg("muted", `${status.running} running`) : "",
		status.done ? theme.fg("muted", `${status.done} done`) : "",
		status.failed ? theme.fg("error", `${status.failed} failed`) : "",
	].filter(Boolean).join(separator);
	const head = progress ? label + separator + progress : label;
	const hinted = withHint(head, theme, context);
	const headingLines = (width: number) => {
		if (visibleWidth(hinted) <= width) return [hinted];
		if (visibleWidth(head) <= width) return [head];
		return progress ? [...wrapTextWithAnsi(label, width), ...wrapTextWithAnsi(progress, width)] : wrapTextWithAnsi(label, width);
	};
	box.addChild({
		render(width) {
			const lines = call.render(Math.max(1, width - 2)).map((line) => plain(line).trimEnd()).filter((line) => line.trim());
			return [
				...headingLines(width),
				...lines.slice(0, CALL_LINES).map((line) => theme.fg("dim", truncateToWidth(`  ${line}`, width))),
			];
		},
		invalidate() {
			call.invalidate();
		},
	});
	return box;
}

function closedView(count: number, failed: number, theme: Theme, context: Context): Component {
	const label = theme.fg("muted", `Called ${count} ${count === 1 ? "tool" : "tools"}`);
	const separator = failed ? theme.fg("muted", ", ") : "";
	const failures = failed ? theme.fg("error", `${failed} failed`) : "";
	const box = new Box(context.outputPad, 0);
	const text = withHint(label + separator + failures, theme, context);
	box.addChild({
		render: (width) => [visibleWidth(text) <= width ? text : truncateToWidth(label + separator + failures, width)],
		invalidate() {},
	});
	return box;
}

export class InlineToolOutput {
	private readonly groups = new Map<string, Group>();
	private readonly calls = new Map<string, CallState>();
	private readonly views = new Map<string, WeakRef<View>>();
	private openGroup?: Group;
	private message?: number;
	private readonly messageCalls = new Set<string>();
	private readonly nativeCalls = new Set<string>();
	private live?: LiveBatch;
	private lastExpanded?: boolean;

	constructor(private readonly expandedChanged: () => void) {}

	reset(redraw: boolean) {
		const ids = [...this.groups.keys()];
		this.groups.clear();
		this.calls.clear();
		this.openGroup = undefined;
		this.message = undefined;
		this.messageCalls.clear();
		this.nativeCalls.clear();
		this.live = undefined;
		if (redraw) for (const id of ids) this.redraw(id);
		else this.views.clear();
	}

	rebuild(messages: Iterable<AgentMessage>, cwd: string) {
		const before = [...this.groups.keys()];
		this.reset(false);
		for (const message of messages) this.observe(message, cwd);
		this.close();
		for (const id of new Set([...before, ...this.groups.keys()])) this.redraw(id);
	}

	observe(message: AgentMessage, cwd: string) {
		if (message.role === "toolResult") {
			this.finish(message.toolCallId, message.isError);
			return;
		}
		if (message.role !== "assistant") {
			if (shown(message)) this.close();
			return;
		}
		if (this.message !== message.timestamp) {
			this.message = message.timestamp;
			this.messageCalls.clear();
			this.refreshLive();
		}
		if (shown(message) && this.openGroup?.ids.some((id) => !this.messageCalls.has(id))) this.split(this.openGroup);
		for (const block of message.content) {
			if (block.type !== "toolCall") continue;
			if (shownNatively(block.name)) {
				this.passNative(block.id);
				continue;
			}
			const activity = toolActivity({ toolName: block.name, args: block.arguments }, cwd);
			const state = this.calls.get(block.id);
			if (state) {
				if (!state.purpose && activityLabel(state.activity) !== activityLabel(activity)) {
					state.activity = activity;
					if (this.live?.id === block.id) this.redraw(block.id);
				}
				continue;
			}
			this.add(block.id, { activity, phase: "queued" });
		}
	}

	start(id: string, call: Invocation, cwd: string) {
		if (shownNatively(call.toolName)) {
			this.passNative(id);
			return;
		}
		const activity = toolActivity(call, cwd);
		const state = this.calls.get(id);
		if (!state) {
			this.add(id, { activity, phase: "running" });
			return;
		}
		state.activity = activity;
		state.phase = "running";
		this.refreshLive();
	}

	finish(id: string, failed: boolean) {
		const state = this.calls.get(id);
		const phase = failed ? "failed" : "done";
		if (!state || state.phase === phase) return;
		state.phase = phase;
		if (this.messageCalls.has(id)) this.refreshLive();
		this.redraw(this.groups.get(id)?.ids.at(-1));
	}

	pending(id: string) {
		const state = this.calls.get(id);
		if (!state) return;
		state.pending = true;
		this.redraw(id);
	}

	describe(id: string, purpose: string | undefined) {
		const state = this.calls.get(id);
		if (!state) return;
		state.pending = false;
		if (purpose) state.purpose = purpose;
		this.redraw(id);
	}

	label(id: string): string | undefined {
		const state = this.calls.get(id);
		return state && callLabel(state);
	}

	close() {
		this.openGroup = undefined;
		this.messageCalls.clear();
		this.refreshLive();
	}

	private passNative(id: string) {
		if (this.nativeCalls.has(id)) return;
		this.nativeCalls.add(id);
		this.openGroup = undefined;
	}

	private noteExpanded(expanded: boolean) {
		if (expanded === this.lastExpanded) return;
		this.lastExpanded = expanded;
		setTimeout(this.expandedChanged, 0);
	}

	private add(id: string, state: CallState) {
		this.calls.set(id, state);
		this.messageCalls.add(id);
		const group = this.openGroup ??= { ids: [] };
		const previousAnchor = group.ids.at(-1);
		group.ids.push(id);
		this.groups.set(id, group);
		this.refreshLive();
		this.redraw(previousAnchor);
	}

	private split(group: Group) {
		const previousAnchor = group.ids.at(-1);
		const moved = group.ids.filter((id) => this.messageCalls.has(id));
		group.ids = group.ids.filter((id) => !this.messageCalls.has(id));
		const next = moved.length ? { ids: moved } : undefined;
		this.openGroup = next;
		if (next) for (const id of moved) this.groups.set(id, next);
		this.refreshLive();
		this.redraw(previousAnchor);
		this.redraw(group.ids.at(-1));
	}

	private refreshLive() {
		let running: string | undefined;
		let queued: string | undefined;
		const status = { running: 0, done: 0, failed: 0 };
		const rows = new Set<string>();
		for (const id of this.messageCalls) {
			const phase = this.calls.get(id)?.phase;
			if (phase === "running") running = id;
			else if (phase === "queued") queued = id;
			if (phase && phase !== "queued") status[phase]++;
			const anchor = this.groups.get(id)?.ids.at(-1);
			if (anchor !== undefined) rows.add(anchor);
		}
		const previous = this.live;
		const id = running ?? queued;
		if (id !== undefined) rows.add(id);
		this.live = id === undefined ? undefined : { id, status, rows };
		for (const row of new Set([...(previous?.rows ?? []), ...(this.live?.rows ?? [])])) this.redraw(row);
	}

	private redraw(id: string | undefined) {
		if (id !== undefined) this.views.get(id)?.deref()?.redraw?.();
	}

	wrap(name: string, native: ToolRenderers | undefined): ToolRenderers | undefined {
		if (shownNatively(name)) {
			const renderCall = native?.renderCall;
			return renderCall ? {
				...native,
				renderCall: (args, theme, context) => {
					this.noteExpanded(context.expanded);
					return renderCall(args, theme, context);
				},
			} : native;
		}
		const viewFor = (context: Context): View => {
			return context.state[VIEW] ??= { tui: context.isPartial && !context.executionStarted } satisfies View;
		};
		const groupFor = (view: View, context: Context): Group | undefined => {
			if (!view.tui) return;
			if (this.views.get(context.toolCallId)?.deref() !== view) {
				view.redraw = context.invalidate;
				this.views.set(context.toolCallId, new WeakRef(view));
			}
			return this.groups.get(context.toolCallId);
		};
		const nativeCall = (args: Parameters<RenderCall>[0], theme: Theme, context: Context, view: View): Component => {
			const raw = native?.renderCall?.(args, theme, { ...context, lastComponent: view.call })
				?? new Text(`${theme.fg("toolTitle", theme.bold(plain(name)))}${args ? ` ${plain(JSON.stringify(args, null, context.expanded ? 2 : undefined))}` : ""}`, 0, 0);
			view.call = raw;
			return raw;
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
				this.noteExpanded(context.expanded);
				const view = viewFor(context);
				const group = groupFor(view, context);
				if (group && !context.expanded) {
					const id = context.toolCallId;
					const state = this.calls.get(id);
					if (state && this.live?.id === id) {
						return liveView(state, this.live.status, nativeCall(args, theme, context, view), theme, context);
					}
					if (group.ids.at(-1) === id && (!this.live || this.groups.get(this.live.id) !== group)) {
						const ids = this.live ? group.ids.filter((callId) => !this.messageCalls.has(callId)) : group.ids;
						if (ids.length) {
							const failed = ids.filter((callId) => this.calls.get(callId)?.phase === "failed").length;
							return closedView(ids.length, failed, theme, context);
						}
					}
					return new Container();
				}
				return rawShell(nativeCall(args, theme, context, view), theme, context, view);
			},
			renderResult: (result, options, theme, context) => {
				const view = viewFor(context);
				if (groupFor(view, context) && !options.expanded) return new Container();
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
