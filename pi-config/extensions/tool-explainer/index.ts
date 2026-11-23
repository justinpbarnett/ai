import type { AssistantMessage } from "@earendil-works/pi-ai";
import { sessionEntryToContextMessages, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { requireModels } from "./explain.js";
import { manualRows, purposeCall, recentCalls, type Invocation } from "./evidence.js";
import { ExplanationError } from "./errors.js";
import { InlineToolOutput, shownNatively } from "./inline.js";
import { TranscriptPresentation } from "./presentation.js";
import { plain, purposeExcerpt, safeLabel } from "./screening.js";
import { DEFAULT_COUNT, MAX_COUNT, config, defaults, parseCount } from "./settings.js";
import { THINKING_ENTRY, ThinkingSummaries, thinkingRuns, type SavedThought } from "./thinking.js";
import { collectExplanation, confirmPreview, explanationText, preview, showView } from "./view.js";
import { hostedWriterBlocked, operationHints, writeSummary, writeThinkingSummary, type Writer, type WritingRequest } from "./writer.js";

const COUNT_FLAG = "explain-tools-count";
const NO_AUTO_FLAG = "explain-tools-no-auto";
const MAX_HISTORY = 12;
const MAX_THOUGHT_TAIL = 600;
const MAX_LOCAL_EVIDENCE_BYTES = 6 * 1024;
const USAGE = `/explain-tools [1–${MAX_COUNT} | on | off | status | recent]`;
const NOTE_MARK = "●";
const BLOCK_START = /^(?:\s|#|>|\||<|```|~~~|[*+-]\s|[*_-]{3}|\d+[.)]\s)/u;
const PROGRESS_NOTES = "Keep the user posted with short notes in plain text while you work. Before your first tool call, say in one sentence what you will do first. After that, write one or two sentences when you find something that matters, change direction, or start a new step: say what you found, naming the file, command or fact, and what you will do next. Skip notes between routine calls.";

type MessageContent = string | ReadonlyArray<{ type: string; text?: string }>;
type Summary = { label: string; route: string };

function textExcerpt(content: MessageContent): string | undefined {
	if (typeof content === "string") return purposeExcerpt(content);
	if (content.some((block) => block.type === "image")) return;
	return purposeExcerpt(content.flatMap((block) => block.type === "text" && block.text ? [block.text] : []).join("\n"));
}

function thoughtTail(message: AssistantMessage | undefined): string | undefined {
	const run = message && thinkingRuns(message).at(-1)?.text;
	if (!run || /```|~~~/.test(run)) return;
	const tail = plain(run).replace(/\s+/gu, " ").trim().slice(-MAX_THOUGHT_TAIL);
	if (tail && safeLabel(tail)) return tail;
}

function state() {
	return {
		controller: new AbortController(), tool: new AbortController(),
		manual: false, persistenceWarningShown: false, request: undefined as string | undefined,
		assistant: undefined as AssistantMessage | undefined,
	};
}

type Background = { request?: string; note?: string; reasoning?: string };

function writingRequest(call: Invocation, cwd: string, background: Background, writer: Writer): WritingRequest | undefined {
	const evidence = purposeCall(call, cwd);
	if (writer.kind === "ollama") {
		const payload = { ...background, calls: [evidence] };
		if (Buffer.byteLength(JSON.stringify(payload), "utf8") <= MAX_LOCAL_EVIDENCE_BYTES) return { ...writer, evidence: payload };
	} else if (writer.kind === "openrouter" && !hostedWriterBlocked(writer)) return { ...writer, hints: [operationHints(evidence)] };
}

function skippedRoute(writer: Writer): string {
	if (writer.kind === "off") return "writer off";
	return hostedWriterBlocked(writer) ? "no summary: writer disabled offline" : "no summary: insufficient evidence";
}

function shownMessages(ctx: ExtensionContext) {
	return ctx.sessionManager.buildContextEntries().flatMap((entry) => sessionEntryToContextMessages(entry));
}

async function showManualExplanation(ctx: ExtensionContext, rows: ReturnType<typeof manualRows>, signal: AbortSignal) {
	const evidence = rows.flatMap((row) => row.evidence ? [row.evidence] : []);
	const heading = `Tool explanation · ${rows.length} ${rows.length === 1 ? "call" : "calls"}`;
	if (!evidence.length) {
		await showView(ctx, heading, explanationText(rows), signal);
		return;
	}
	try {
		requireModels(ctx.modelRegistry);
	} catch (error) {
		if (!(error instanceof ExplanationError)) throw error;
		await showView(ctx, heading, explanationText(rows, undefined, error.message), signal);
		return;
	}
	const leaf = ctx.sessionManager.getLeafId();
	const current = () => !signal.aborted && leaf === ctx.sessionManager.getLeafId();
	if (!await confirmPreview(ctx, "Preview tool excerpts", preview(evidence, rows.length - evidence.length), signal) || !current()) return;
	const outcome = await collectExplanation(ctx, evidence, signal);
	if (outcome && current()) await showView(ctx, heading, explanationText(rows, outcome.result, outcome.error), signal);
}

async function showRecentHistory(ctx: ExtensionContext, session: ReturnType<typeof state>, history: Summary[]) {
	if (!history.length) {
		ctx.ui.notify("No call summaries since Pi started or reloaded.");
		return;
	}
	session.manual = true;
	try {
		const text = history.map(({ label, route }) => `${label} · ${route}`).join("\n\n");
		await showView(ctx, "Recent tool summaries", text, session.controller.signal);
	} finally { session.manual = false; }
}

function writerStatus(writer: Writer, trusted: boolean): string {
	if (!trusted) return "untrusted project";
	if (writer.kind === "off") return "off";
	return `${writer.kind}/${writer.model}${hostedWriterBlocked(writer) ? " (disabled offline)" : ""}`;
}

class ToolExplainer {
	private active = state();
	private readonly history: Summary[] = [];
	private settings = defaults;
	private auto = true;
	private attached?: ExtensionContext;
	// Pi can rebuild tool rows before session_start during /reload.
	private renderInline = true;
	private detachPresentation?: () => void;

	private readonly presentation = new TranscriptPresentation();
	private readonly inline = new InlineToolOutput(() => this.attached?.ui.getToolsExpanded());
	private readonly thinking = new ThinkingSummaries({
		enabled: () => this.attached !== undefined && this.autoEnabled(this.attached),
		expanded: () => this.presentation.thinkingExpanded ?? this.attached?.ui.getToolsExpanded() ?? false,
		refresh: () => this.refreshThinking(),
		write: (text, signal) => this.settings.writer.kind === "ollama" ? writeThinkingSummary(this.settings.writer.model, text, signal) : undefined,
		save: (record) => this.persist(record),
	});

	constructor(private readonly pi: ExtensionAPI) {}

	register() {
		this.registerPresentation();
		this.registerSessionEvents();
		this.registerTurnEvents();
		this.registerCommand();
	}

	private registerPresentation() {
		this.pi.registerFlag(COUNT_FLAG, { type: "string", description: `Tool calls per manual explanation (1–${MAX_COUNT})` });
		this.pi.registerFlag(NO_AUTO_FLAG, { type: "boolean", description: "Start with automatic tool and thinking summaries off" });
		this.pi.registerToolRenderer((name, next) => this.renderInline ? this.inline.wrap(name, next()) : next());
		this.pi.registerMarkdownTransformer((markdown, context) => {
			if (context.messageType === "assistant-thinking") return this.thinking.transform(markdown, context);
			return this.attached && this.autoEnabled(this.attached) && markdown.trim() && !BLOCK_START.test(markdown) ? `${NOTE_MARK} ${markdown}` : markdown;
		}, { messageTypes: ["assistant", "assistant-thinking"] });
	}

	private refreshThinking() {
		this.attached?.ui.setHiddenThinkingLabel(undefined);
	}

	private count(): number | undefined {
		const flag = this.pi.getFlag(COUNT_FLAG);
		return flag === undefined ? this.settings.count : parseCount(flag);
	}

	private autoEnabled(ctx: ExtensionContext) {
		return this.auto && ctx.mode === "tui" && ctx.isProjectTrusted();
	}

	private reset(redraw = false) {
		this.active.controller.abort();
		this.active.tool.abort();
		this.active = state();
		this.thinking.reset();
		this.presentation.resetThinking();
		this.inline.reset(redraw);
	}

	private persist(record: SavedThought) {
		try {
			this.pi.appendEntry(THINKING_ENTRY, record);
		} catch {
			if (this.active.persistenceWarningShown) return;
			this.active.persistenceWarningShown = true;
			this.attached?.ui.notify("Could not save thinking summaries. New summaries may not survive a reload.", "warning");
		}
	}

	private restore(ctx: ExtensionContext) {
		if (ctx.mode !== "tui" || !ctx.isProjectTrusted()) return;
		this.thinking.restore(ctx.sessionManager.getBranch());
		this.inline.rebuild(this.autoEnabled(ctx) ? shownMessages(ctx) : [], ctx.cwd);
		setTimeout(() => this.refreshThinking(), 0);
	}

	private remember(label: string, route: string) {
		const { history } = this;
		history.unshift({ label, route });
		if (history.length > MAX_HISTORY) history.pop();
	}

	private async summarizeCall(ctx: ExtensionContext, id: string, call: Invocation) {
		const run = this.active;
		run.tool.abort();
		run.tool = new AbortController();
		const { signal } = run.tool;
		const background = { request: run.request, note: textExcerpt(run.assistant?.content ?? []), reasoning: thoughtTail(run.assistant) };
		const { writer } = this.settings;
		const request = writer.kind === "off" ? undefined : writingRequest(call, ctx.cwd, background, writer);
		if (!request) {
			this.remember(this.inline.label(id) ?? call.toolName, skippedRoute(writer));
			return;
		}
		this.inline.pending(id);
		let purpose: string | undefined;
		let route = `${request.kind}/${request.model}`;
		try {
			purpose = await writeSummary(ctx.modelRegistry, request, signal);
		} catch (error) {
			route = signal.aborted ? "no summary: replaced by the next call"
				: `no summary: ${error instanceof ExplanationError ? error.message : `Could not reach ${request.kind}.`}`;
		}
		if (run !== this.active) return;
		this.inline.describe(id, signal.aborted ? undefined : purpose);
		this.remember(this.inline.label(id) ?? call.toolName, route);
	}

	private registerSessionEvents() {
		this.pi.on("session_start", (_event, ctx) => {
			this.renderInline = ctx.mode === "tui";
			if (!this.renderInline) return;
			this.attached = ctx;
			this.detachPresentation = this.presentation.attach(() => this.autoEnabled(ctx), () => ctx.ui.getToolsExpanded());
			const loaded = config();
			this.settings = loaded;
			this.auto = loaded.auto && !this.pi.getFlag(NO_AUTO_FLAG);
			this.restore(ctx);
			if (loaded.warning) ctx.ui.notify(loaded.warning, "warning");
			if (this.count() === undefined) ctx.ui.notify(`--${COUNT_FLAG} must be 1 to ${MAX_COUNT}. Manual explanations use ${DEFAULT_COUNT}.`, "warning");
		});
		this.pi.on("session_shutdown", () => {
			this.detachPresentation?.();
			this.detachPresentation = undefined;
			this.history.length = 0;
			this.reset();
			this.attached = undefined;
		});
		this.pi.on("session_tree", (_event, ctx) => {
			this.reset(true);
			this.restore(ctx);
		});
		this.pi.on("session_compact", (_event, ctx) => {
			if (this.autoEnabled(ctx)) this.inline.rebuild(shownMessages(ctx), ctx.cwd);
		});
	}

	private registerTurnEvents() {
		this.pi.on("message_start", (event, ctx) => {
			if (!this.autoEnabled(ctx)) return;
			if (event.message.role === "user") this.active.request = textExcerpt(event.message.content);
			this.inline.observe(event.message, ctx.cwd);
		});
		this.pi.on("message_update", (event, ctx) => {
			if (!this.autoEnabled(ctx) || event.message.role !== "assistant") return;
			this.active.assistant = event.message;
			this.inline.observe(event.message, ctx.cwd);
			this.thinking.observe(event.message, false);
		});
		this.pi.on("message_end", (event, ctx) => {
			if (!this.autoEnabled(ctx)) return;
			this.inline.observe(event.message, ctx.cwd);
			if (event.message.role !== "assistant") return;
			this.active.assistant = event.message;
			this.thinking.observe(event.message, true);
		});
		this.pi.on("tool_execution_start", (event, ctx) => {
			if (!this.autoEnabled(ctx) || event.parentToolCallId) return;
			const call = { toolName: event.toolName, args: event.args };
			this.inline.start(event.toolCallId, call, ctx.cwd);
			if (!shownNatively(call.toolName)) void this.summarizeCall(ctx, event.toolCallId, call);
		});
		this.pi.on("tool_execution_end", (event, ctx) => {
			if (this.autoEnabled(ctx) && !event.parentToolCallId) this.inline.finish(event.toolCallId, event.isError);
		});
		this.pi.on("agent_settled", () => this.inline.close());
		this.pi.on("before_agent_start", (event, ctx) => {
			const { promptGuidelines } = event.systemPromptOptions;
			if (this.autoEnabled(ctx) && !promptGuidelines.includes(PROGRESS_NOTES)) promptGuidelines.push(PROGRESS_NOTES);
		});
	}

	private setAutomatic(ctx: ExtensionContext, enabled: boolean) {
		if (enabled && !ctx.isProjectTrusted()) {
			ctx.ui.notify("Automatic summaries require a trusted project.", "warning");
			return;
		}
		this.auto = enabled;
		this.reset(true);
		this.restore(ctx);
		ctx.ui.notify(`Automatic summaries ${enabled ? "on" : "off"} for this session.`);
	}

	private registerCommand() {
		this.pi.registerCommand("explain-tools", {
			description: "Explain recent tool output, turn automatic summaries on or off, or list recent tool summaries",
			getArgumentCompletions: (prefix) => ["1", "2", "3", "on", "off", "status", "recent"]
				.filter((value) => prefix && value.startsWith(prefix) && value !== prefix).map((value) => ({ value, label: value })),
			handler: (args, ctx) => this.handleCommand(args, ctx),
		});
	}

	private async handleCommand(args: string, ctx: ExtensionContext) {
		if (ctx.mode !== "tui") return;
		const input = args.trim();
		if (input === "status") {
			const { writer } = this.settings;
			const route = writerStatus(writer, ctx.isProjectTrusted());
			ctx.ui.notify(`Automatic summaries: ${this.autoEnabled(ctx) ? "on" : "off"} · manual count: ${this.count() ?? "invalid"} · writer: ${route}${writer.kind === "ollama" ? "" : " · thinking: headers only"}`);
			return;
		}
		if (input === "on" || input === "off") return this.setAutomatic(ctx, input === "on");
		if (!ctx.isIdle() || ctx.hasPendingMessages() || this.active.manual) {
			ctx.ui.notify("Wait until Pi is idle to open tool explanations.", "warning");
			return;
		}
		const session = this.active;
		const { signal } = session.controller;
		if (input === "recent") return showRecentHistory(ctx, session, this.history);
		if (!ctx.isProjectTrusted()) { ctx.ui.notify("Tool explanations require a trusted Pi session.", "warning"); return; }
		const requested = input ? parseCount(input) : this.count() ?? DEFAULT_COUNT;
		if (!requested) { ctx.ui.notify(`Use ${USAGE}.`, "warning"); return; }
		const calls = recentCalls(ctx, requested);
		if (!calls.length) { ctx.ui.notify("No completed tool calls on this session branch."); return; }
		session.manual = true;
		try {
			await showManualExplanation(ctx, manualRows(calls, ctx.cwd), signal);
		} finally { session.manual = false; }
	}
}

export default function (pi: ExtensionAPI) {
	new ToolExplainer(pi).register();
}
