import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import { getAgentDir, sessionEntryToContextMessages, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DEFAULT_OLLAMA_MODEL, isLocalOllamaModel } from "../shared/ollama.js";
import { manualRows, plain, purposeCall, purposeExcerpt, recentCalls, safeLabel, type Invocation } from "./evidence.js";
import { ExplanationError } from "./explain.js";
import { InlineToolOutput, shownNatively } from "./inline.js";
import { THINKING_ENTRY, ThinkingSummaries, thinkingRuns, type SavedThought } from "./thinking.js";
import { collectExplanation, explanationText, preview, showView } from "./view.js";
import { operationHints, DEFAULT_OPENROUTER_MODEL, writeSummary, writeThinkingSummary, type Writer, type WritingRequest } from "./writer.js";

const COUNT_FLAG = "explain-tools-count";
const NO_AUTO_FLAG = "explain-tools-no-auto";
const DEFAULT_COUNT = 3;
const MAX_HISTORY = 12;
const MAX_THOUGHT_TAIL = 600;
const MAX_LOCAL_EVIDENCE_BYTES = 6 * 1024;
const USAGE = "/explain-tools [1–10 | on | off | status | recent]";

function parseCount(value: unknown): number | undefined {
	if (typeof value === "number") return Number.isInteger(value) && value >= 1 && value <= 10 ? value : undefined;
	if (typeof value === "string" && /^(?:[1-9]|10)$/.test(value)) return Number(value);
}

type Settings = { count: number; auto: boolean; writer: Writer; warning?: string };
const defaults: Settings = { count: DEFAULT_COUNT, auto: true, writer: { kind: "ollama", model: DEFAULT_OLLAMA_MODEL } };

function validModel(value: unknown): boolean {
	return typeof value === "string" && value.length <= 150 && /^(?:[\w.-]+\/)?[\w.-]+(?::[\w.-]+)?$/.test(value);
}

function config(): Settings {
	try {
		const value = JSON.parse(readFileSync(join(getAgentDir(), "tool-explainer.json"), "utf8"));
		if (!value || Array.isArray(value) || typeof value !== "object" ||
			(value.count !== undefined && (typeof value.count !== "number" || !parseCount(value.count))) ||
			(value.auto !== undefined && typeof value.auto !== "boolean") ||
			(value.ollamaModel !== undefined && !isLocalOllamaModel(value.ollamaModel)) ||
			(value.openrouterModel !== undefined && !validModel(value.openrouterModel))) throw new Error("Invalid settings");
		const kind = value.writer === undefined ? "ollama" : value.writer;
		let writer: Writer;
		if (kind === "ollama") writer = { kind, model: value.ollamaModel ?? DEFAULT_OLLAMA_MODEL };
		else if (kind === "openrouter") writer = { kind, model: value.openrouterModel ?? DEFAULT_OPENROUTER_MODEL };
		else if (kind === "off") writer = { kind };
		else throw new Error("Invalid writer");
		return { count: value.count ?? DEFAULT_COUNT, auto: value.auto ?? true, writer };
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return defaults;
		return { ...defaults, auto: false, writer: { kind: "off" }, warning: "Invalid tool-explainer.json. Check auto (boolean), count (1–10), writer (ollama, openrouter, or off), and model IDs. Automatic explanations are disabled." };
	}
}

function offline(): boolean {
	return /^(?:1|true|yes)$/i.test(process.env.PI_OFFLINE ?? "");
}

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
		controller: new AbortController(), tool: new AbortController(), history: [] as Summary[],
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
	} else if (writer.kind === "openrouter" && !offline()) return { ...writer, hints: [operationHints(evidence)] };
}

function shownMessages(ctx: ExtensionContext) {
	return ctx.sessionManager.buildContextEntries().flatMap((entry) => sessionEntryToContextMessages(entry));
}

export default function (pi: ExtensionAPI) {
	let active = state();
	let settings = defaults;
	let auto = true;
	let attached: ExtensionContext | undefined;
	// Pi can rebuild tool rows before session_start during /reload.
	let renderInline = true;
	let shownExpanded = false;

	function refreshThinking() {
		attached?.ui.setHiddenThinkingLabel(undefined);
	}

	function expandedChanged() {
		const expanded = attached?.ui.getToolsExpanded() ?? false;
		if (expanded === shownExpanded) return;
		shownExpanded = expanded;
		refreshThinking();
	}

	const inline = new InlineToolOutput(expandedChanged);
	const thinking = new ThinkingSummaries({
		enabled: () => attached !== undefined && autoEnabled(attached),
		expanded: () => attached?.ui.getToolsExpanded() ?? false,
		refresh: refreshThinking,
		write: (text, signal) => settings.writer.kind === "ollama" ? writeThinkingSummary(settings.writer.model, text, signal) : undefined,
		save: (record) => persist(record),
	});

	pi.registerFlag(COUNT_FLAG, { type: "string", description: "Tool calls per manual explanation (1–10)" });
	pi.registerFlag(NO_AUTO_FLAG, { type: "boolean", description: "Start with automatic tool and thinking summaries off" });
	pi.registerToolRenderer((name, next) => renderInline ? inline.wrap(name, next()) : next());
	pi.registerMarkdownTransformer(thinking.transform, { messageTypes: ["assistant-thinking"] });

	function count(): number | undefined {
		const flag = pi.getFlag(COUNT_FLAG);
		return flag === undefined ? settings.count : parseCount(flag);
	}

	function autoEnabled(ctx: ExtensionContext) {
		return auto && ctx.mode === "tui" && ctx.isProjectTrusted();
	}

	function reset(redraw = false) {
		active.controller.abort();
		active.tool.abort();
		active = state();
		thinking.reset();
		inline.reset(redraw);
	}

	function persist(record: SavedThought) {
		try {
			pi.appendEntry(THINKING_ENTRY, record);
		} catch {
			if (active.persistenceWarningShown) return;
			active.persistenceWarningShown = true;
			attached?.ui.notify("Could not save thinking summaries. New summaries may not survive a reload.", "warning");
		}
	}

	function restore(ctx: ExtensionContext) {
		if (ctx.mode !== "tui" || !ctx.isProjectTrusted()) return;
		thinking.restore(ctx.sessionManager.getBranch());
		inline.rebuild(autoEnabled(ctx) ? shownMessages(ctx) : [], ctx.cwd);
		shownExpanded = ctx.ui.getToolsExpanded();
		setTimeout(refreshThinking, 0);
	}

	function remember(label: string, route: string) {
		active.history.unshift({ label, route });
		if (active.history.length > MAX_HISTORY) active.history.pop();
	}

	async function summarizeCall(ctx: ExtensionContext, id: string, call: Invocation) {
		const run = active;
		run.tool.abort();
		run.tool = new AbortController();
		const { signal } = run.tool;
		const background = { request: run.request, note: textExcerpt(run.assistant?.content ?? []), reasoning: thoughtTail(run.assistant) };
		const request = settings.writer.kind === "off" ? undefined : writingRequest(call, ctx.cwd, background, settings.writer);
		if (!request) {
			remember(inline.label(id) ?? call.toolName, settings.writer.kind === "off" ? "writer off" : "no summary: insufficient evidence");
			return;
		}
		inline.pending(id);
		let purpose: string | undefined;
		let route = `${request.kind}/${request.model}`;
		try {
			purpose = await writeSummary(ctx.modelRegistry, request, signal);
		} catch (error) {
			route = signal.aborted ? "no summary: replaced by the next call"
				: `no summary: ${error instanceof ExplanationError ? error.message : `Could not reach ${request.kind}.`}`;
		}
		if (run !== active) return;
		inline.describe(id, signal.aborted ? undefined : purpose);
		remember(inline.label(id) ?? call.toolName, route);
	}

	pi.on("session_start", (_event, ctx) => {
		renderInline = ctx.mode === "tui";
		if (!renderInline) return;
		attached = ctx;
		const loaded = config();
		settings = loaded;
		auto = settings.auto && !pi.getFlag(NO_AUTO_FLAG);
		restore(ctx);
		if (loaded.warning) ctx.ui.notify(loaded.warning, "warning");
		if (count() === undefined) ctx.ui.notify(`--${COUNT_FLAG} must be 1 to 10. Manual explanations use ${DEFAULT_COUNT}.`, "warning");
	});
	pi.on("session_shutdown", () => {
		reset();
		attached = undefined;
	});
	pi.on("session_tree", (_event, ctx) => {
		reset(true);
		restore(ctx);
	});
	pi.on("session_compact", (_event, ctx) => {
		if (ctx.mode === "tui" && autoEnabled(ctx)) inline.rebuild(shownMessages(ctx), ctx.cwd);
	});
	pi.on("message_start", (event, ctx) => {
		if (!autoEnabled(ctx)) return;
		if (event.message.role === "user") active.request = textExcerpt(event.message.content);
		inline.observe(event.message, ctx.cwd);
	});
	pi.on("message_update", (event, ctx) => {
		if (!autoEnabled(ctx) || event.message.role !== "assistant") return;
		active.assistant = event.message;
		inline.observe(event.message, ctx.cwd);
		thinking.observe(event.message, false);
	});
	pi.on("message_end", (event, ctx) => {
		if (!autoEnabled(ctx)) return;
		inline.observe(event.message, ctx.cwd);
		if (event.message.role !== "assistant") return;
		active.assistant = event.message;
		thinking.observe(event.message, true);
	});
	pi.on("tool_execution_start", (event, ctx) => {
		if (!autoEnabled(ctx) || event.parentToolCallId) return;
		const call = { toolName: event.toolName, args: event.args };
		inline.start(event.toolCallId, call, ctx.cwd);
		if (!shownNatively(call.toolName)) void summarizeCall(ctx, event.toolCallId, call);
	});
	pi.on("tool_execution_end", (event, ctx) => {
		if (autoEnabled(ctx) && !event.parentToolCallId) inline.finish(event.toolCallId, event.isError);
	});
	pi.on("agent_settled", () => inline.close());

	pi.registerCommand("explain-tools", {
		description: "Explain recent tool output, turn automatic summaries on or off, or list recent tool summaries",
		getArgumentCompletions: (prefix) => ["1", "2", "3", "on", "off", "status", "recent"]
			.filter((value) => prefix && value.startsWith(prefix) && value !== prefix).map((value) => ({ value, label: value })),
		async handler(args, ctx) {
			if (ctx.mode !== "tui") return;
			const input = args.trim();
			if (input === "status") {
				const { writer } = settings;
				const route = !ctx.isProjectTrusted() ? "untrusted project"
					: writer.kind === "off" ? "off"
						: `${writer.kind}/${writer.model}${writer.kind === "openrouter" && offline() ? " (disabled offline)" : ""}`;
				ctx.ui.notify(`Automatic summaries: ${autoEnabled(ctx) ? "on" : "off"} · manual count: ${count() ?? "invalid"} · writer: ${route}${writer.kind === "ollama" ? "" : " · thinking: headers only"}`);
				return;
			}
			if (input === "on" || input === "off") {
				if (input === "on" && !ctx.isProjectTrusted()) {
					ctx.ui.notify("Automatic summaries require a trusted project.", "warning");
					return;
				}
				auto = input === "on";
				reset(true);
				restore(ctx);
				ctx.ui.notify(`Automatic summaries ${auto ? "on" : "off"} for this session.`);
				return;
			}
			if (!ctx.isIdle() || ctx.hasPendingMessages() || active.manual) {
				ctx.ui.notify("Wait until Pi is idle to open tool explanations.", "warning");
				return;
			}
			const session = active;
			const { signal } = session.controller;
			if (input === "recent") {
				if (!session.history.length) { ctx.ui.notify("No call summaries since Pi started or reloaded."); return; }
				session.manual = true;
				try {
					const text = session.history.map(({ label, route }) => `${label} · ${route}`).join("\n\n");
					await showView(ctx, "Recent tool summaries", text, signal);
				} finally { session.manual = false; }
				return;
			}
			if (!ctx.isProjectTrusted()) { ctx.ui.notify("Tool explanations require a trusted Pi session.", "warning"); return; }
			const requested = input ? parseCount(input) : count() ?? DEFAULT_COUNT;
			if (!requested) { ctx.ui.notify(`Use ${USAGE}.`, "warning"); return; }
			const calls = recentCalls(ctx, requested);
			if (!calls.length) { ctx.ui.notify("No completed tool calls on this session branch."); return; }
			session.manual = true;
			try {
				const rows = manualRows(calls, ctx.cwd);
				const evidence = rows.flatMap((row) => row.evidence ? [row.evidence] : []);
				const heading = `Tool explanation · ${rows.length} ${rows.length === 1 ? "call" : "calls"}`;
				if (!evidence.length) { await showView(ctx, heading, explanationText(rows), signal); return; }
				if (!ctx.modelRegistry.getProviderAuthStatus("openrouter").configured) {
					await showView(ctx, heading, explanationText(rows, undefined, "OpenRouter sign-in needed. Use /login or OPENROUTER_API_KEY."), signal);
					return;
				}
				const leaf = ctx.sessionManager.getLeafId();
				const current = () => !signal.aborted && leaf === ctx.sessionManager.getLeafId();
				if (!await showView(ctx, "Preview tool excerpts", preview(evidence, rows.length - evidence.length), signal, true) || !current()) return;
				const outcome = await collectExplanation(ctx, evidence, signal);
				if (outcome && current()) await showView(ctx, heading, explanationText(rows, outcome.result, outcome.error), signal);
			} finally { session.manual = false; }
		},
	});
}
