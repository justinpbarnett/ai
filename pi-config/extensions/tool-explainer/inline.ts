import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { ToolRenderers } from "@earendil-works/pi-coding-agent";
import { Box, Container, Text, truncateToWidth, visibleWidth, wrapTextWithAnsi, type Component } from "@earendil-works/pi-tui";
import { genericActivity, plain, toolActivity, type Invocation, type ToolActivity } from "./evidence.js";

type RenderCall = NonNullable<ToolRenderers["renderCall"]>;
type Context = Parameters<RenderCall>[2];
type Theme = Parameters<RenderCall>[1];

type CallState = { activity: ToolActivity; purpose?: string; pending?: boolean; failed: boolean; running: boolean };
type Group = { ids: string[]; open: boolean };
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

export function callLabel(state: Pick<CallState, "activity" | "purpose" | "failed">): string {
	const text = state.purpose ?? activityLabel(state.activity);
	return state.failed ? `Tool failed: ${text}` : text;
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

function liveView(state: CallState, call: Component, theme: Theme, context: Context): Component {
	const background = state.failed ? "toolErrorBg" : state.running ? "toolPendingBg" : "toolSuccessBg";
	const box = new Box(context.outputPad, 0, (text) => theme.bg(background, text));
	const label = `${callLabel(state)}${state.pending && !state.purpose ? "…" : ""}`;
	const head = withHint(theme.fg(state.failed ? "error" : "accent", label), theme, context);
	box.addChild({
		render(width) {
			const lines = call.render(Math.max(1, width - 2)).map((line) => plain(line).trimEnd()).filter((line) => line.trim());
			return [
				...wrapTextWithAnsi(head, width),
				...lines.slice(0, CALL_LINES).map((line) => theme.fg("dim", truncateToWidth(`  ${line}`, width))),
			];
		},
		invalidate() {
			call.invalidate();
		},
	});
	return box;
}

function closedView(group: Group, failed: number, theme: Theme, context: Context): Component {
	const count = group.ids.length;
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
	private open?: Group;
	private message?: number;
	private readonly messageCalls = new Set<string>();
	private readonly nativeCalls = new Set<string>();
	private current?: string;
	private lastExpanded?: boolean;

	constructor(private readonly expandedChanged: () => void) {}

	reset(redraw: boolean) {
		const ids = [...this.groups.keys()];
		this.groups.clear();
		this.calls.clear();
		this.open = undefined;
		this.message = undefined;
		this.messageCalls.clear();
		this.nativeCalls.clear();
		this.current = undefined;
		if (redraw) for (const id of ids) this.redraw(id);
		else this.views.clear();
	}

	rebuild(messages: Iterable<AgentMessage>, cwd: string) {
		const before = [...this.groups.keys()];
		this.reset(false);
		for (const message of messages) this.observe(message, cwd);
		if (this.open) this.open.open = false;
		this.open = undefined;
		this.current = undefined;
		for (const id of new Set([...before, ...this.groups.keys()])) this.redraw(id);
	}

	observe(message: AgentMessage, cwd: string) {
		if (message.role === "toolResult") {
			const state = this.calls.get(message.toolCallId);
			if (state) {
				state.failed = message.isError;
				state.running = false;
			}
			return;
		}
		if (message.role !== "assistant") {
			if (shown(message)) this.close();
			return;
		}
		if (this.message !== message.timestamp) {
			this.message = message.timestamp;
			this.messageCalls.clear();
		}
		if (shown(message) && this.open?.ids.some((id) => !this.messageCalls.has(id))) this.split();
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
					if (this.current === block.id) this.redraw(block.id);
				}
				continue;
			}
			this.calls.set(block.id, { activity, failed: false, running: false });
			this.messageCalls.add(block.id);
			this.join(block.id);
		}
	}

	start(id: string, call: Invocation, cwd: string) {
		if (shownNatively(call.toolName)) {
			this.passNative(id);
			return;
		}
		const state = this.calls.get(id);
		if (state) {
			state.activity = toolActivity(call, cwd);
			state.running = true;
		} else {
			this.calls.set(id, { activity: toolActivity(call, cwd), failed: false, running: true });
			this.join(id);
		}
		this.focus(id);
	}

	finish(id: string, failed: boolean) {
		const state = this.calls.get(id);
		if (!state) return;
		state.failed = failed;
		state.running = false;
		this.redraw(id);
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
		const group = this.open;
		if (!group) return;
		group.open = false;
		this.open = undefined;
		this.current = undefined;
		for (const id of group.ids) this.redraw(id);
	}

	private passNative(id: string) {
		if (this.nativeCalls.has(id)) return;
		this.nativeCalls.add(id);
		this.close();
	}

	private noteExpanded(expanded: boolean) {
		if (expanded === this.lastExpanded) return;
		this.lastExpanded = expanded;
		setTimeout(this.expandedChanged, 0);
	}

	private join(id: string) {
		this.open ??= { ids: [], open: true };
		this.open.ids.push(id);
		this.groups.set(id, this.open);
		this.focus(id);
	}

	private split() {
		const group = this.open!;
		const moved = group.ids.filter((id) => this.messageCalls.has(id));
		group.ids = group.ids.filter((id) => !this.messageCalls.has(id));
		this.close();
		if (!moved.length) return;
		const next: Group = { ids: moved, open: true };
		for (const id of moved) this.groups.set(id, next);
		this.open = next;
		this.focus(moved.at(-1)!);
	}

	private focus(id: string) {
		const previous = this.current;
		this.current = id;
		if (previous && previous !== id) this.redraw(previous);
		this.redraw(id);
	}

	private redraw(id: string) {
		this.views.get(id)?.deref()?.redraw?.();
	}

	private failures(group: Group): number {
		return group.ids.filter((id) => this.calls.get(id)?.failed).length;
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
					if (group.open) {
						const state = this.calls.get(context.toolCallId);
						return state && this.current === context.toolCallId
							? liveView(state, nativeCall(args, theme, context, view), theme, context) : new Container();
					}
					return group.ids.at(-1) === context.toolCallId ? closedView(group, this.failures(group), theme, context) : new Container();
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
