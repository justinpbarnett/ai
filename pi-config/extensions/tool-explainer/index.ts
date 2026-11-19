import { readFileSync } from "node:fs";
import { join } from "node:path";
import { getAgentDir, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DEFAULT_OLLAMA_MODEL, isLocalOllamaModel } from "../shared/ollama.js";
import { manualRows, pairCalls, purposeCall, purposeExcerpt, recentCalls, toolActivity, type PurposeCall } from "./evidence.js";
import { ExplanationError } from "./explain.js";
import { loadBatches, saveBatch, visibleToolResults } from "./history.js";
import { batchTitle, InlineToolOutput, type Batch, type InlineRow } from "./inline.js";
import { collectExplanation, explanationText, preview, showView } from "./view.js";
import { operationHints, DEFAULT_OPENROUTER_MODEL, writeSummary, type Writer, type WritingRequest } from "./writer.js";

const COUNT_FLAG = "explain-tools-count";
const NO_AUTO_FLAG = "explain-tools-no-auto";
const DEFAULT_COUNT = 3;
const MAX_HISTORY = 12;
const MAX_AUTO_REQUESTS = MAX_HISTORY;
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

type PendingRow = { row: InlineRow; call?: PurposeCall; hints?: string[]; request?: string; assistantNote?: string };
type Job = { batch: Batch; request: WritingRequest };

type MessageContent = string | ReadonlyArray<{ type: string; text?: string }>;

function textExcerpt(content: MessageContent): string | undefined {
	if (typeof content === "string") return purposeExcerpt(content);
	if (content.some((block) => block.type === "image")) return;
	return purposeExcerpt(content.flatMap((block) => block.type === "text" && block.text ? [block.text] : []).join("\n"));
}

function state() {
	return {
		controller: new AbortController(), pending: [] as PendingRow[], history: [] as Batch[],
		queue: [] as Job[], running: false, manual: false, persistenceWarningShown: false,
	};
}

function writingRequest(pending: PendingRow[], writer: Writer): WritingRequest | undefined {
	if (writer.kind === "ollama") {
		const calls = pending.flatMap(({ call }) => call ? [call] : []);
		const singleCall = calls.length === 1 ? calls[0] : undefined;
		const hasSpecificSingleTarget = singleCall && (singleCall.target || singleCall.command || singleCall.search);
		const context = pending.findLast(({ assistantNote }) => assistantNote)?.assistantNote ?? pending.at(-1)?.request;
		const evidence = { background: hasSpecificSingleTarget ? undefined : context, calls };
		if (calls.length && Buffer.byteLength(JSON.stringify(evidence), "utf8") <= MAX_LOCAL_EVIDENCE_BYTES) return { ...writer, evidence };
	} else if (writer.kind === "openrouter") {
		const hints = pending.flatMap((item) => item.hints ? [item.hints] : []);
		if (hints.length) return { ...writer, hints };
	}
}

export default function (pi: ExtensionAPI) {
	const inline = new InlineToolOutput();
	let active = state();
	let settings = defaults;
	let auto = true;
	// Pi can rebuild tool rows before session_start during /reload.
	let renderInline = true;

	pi.registerFlag(COUNT_FLAG, { type: "string", description: "Completed tool calls per explanation (1–10)" });
	pi.registerFlag(NO_AUTO_FLAG, { type: "boolean", description: "Start with automatic tool explanations off" });
	pi.registerToolRenderer((name, next) => renderInline ? inline.wrap(name, next()) : next());

	function count(): number | undefined {
		const flag = pi.getFlag(COUNT_FLAG);
		return flag === undefined ? settings.count : parseCount(flag);
	}

	function reset(redraw = false) {
		active.controller.abort();
		active = state();
		inline.clear(redraw);
	}

	function persist(ctx: ExtensionContext, batch: Batch) {
		try {
			saveBatch(pi, batch);
		} catch {
			if (active.persistenceWarningShown) return;
			active.persistenceWarningShown = true;
			ctx.ui.notify("Could not save tool summaries. New summaries may not survive a reload.", "warning");
		}
	}

	function restore(ctx: ExtensionContext) {
		if (ctx.mode !== "tui" || !ctx.isProjectTrusted()) return;
		const batches = loadBatches(ctx);
		active.history = batches.slice(-MAX_HISTORY).reverse();
		const visible = visibleToolResults(ctx);
		inline.retain(visible);
		if (!autoEnabled(ctx)) return;
		for (const batch of batches) {
			if (batch.rows.every(({ callId }) => visible.has(callId))) inline.place(batch);
		}
	}

	async function drain(ctx: ExtensionContext, session: ReturnType<typeof state>) {
		if (session.running) return;
		session.running = true;
		const { signal } = session.controller;
		const registry = ctx.modelRegistry;
		try {
			while (!signal.aborted && session.queue.length) {
				const { batch, request } = session.queue.shift()!;
				try {
					const purpose = await writeSummary(registry, request, signal);
					if (signal.aborted) break;
					batch.purpose = purpose;
					batch.route = `${request.kind}/${request.model}`;
				} catch (error) {
					if (signal.aborted) break;
					const reason = error instanceof ExplanationError ? error.message : `Could not reach ${request.kind}.`;
					batch.route = `no summary: ${reason}`;
				}
				batch.pending = false;
				inline.update(batch);
				persist(ctx, batch);
			}
		} finally {
			session.running = false;
		}
	}

	function queueBatch(ctx: ExtensionContext, pending: PendingRow[]) {
		if (!pending.length) return;
		const session = active;
		const rows = pending.map(({ row }) => row);
		const batch: Batch = { rows, route: settings.writer.kind === "off" ? "writer off" : "no summary: insufficient evidence" };
		const request = writingRequest(pending, settings.writer);
		if (request?.kind === "openrouter" && offline()) batch.route = "no summary: Pi is offline";
		else if (request && session.queue.length + Number(session.running) >= MAX_AUTO_REQUESTS) batch.route = "no summary: writer queue is full";
		else if (request) {
			batch.pending = true;
			batch.route = `${request.kind}/${request.model} pending`;
			session.queue.push({ batch, request });
		}
		session.history.unshift(batch);
		if (session.history.length > MAX_HISTORY) session.history.pop();
		inline.place(batch);
		persist(ctx, batch);
		if (session.queue.length) void drain(ctx, session);
	}

	function autoEnabled(ctx: ExtensionContext) {
		return auto && ctx.mode === "tui" && ctx.isProjectTrusted() && count() !== undefined;
	}

	pi.on("session_start", (_event, ctx) => {
		renderInline = ctx.mode === "tui";
		if (!renderInline) return;
		const loaded = config();
		settings = loaded;
		auto = settings.auto && !pi.getFlag(NO_AUTO_FLAG);
		restore(ctx);
		if (loaded.warning) ctx.ui.notify(loaded.warning, "warning");
		if (count() === undefined) ctx.ui.notify(`--${COUNT_FLAG} must be 1 to 10. Automatic explanations are disabled.`, "warning");
	});
	pi.on("session_shutdown", () => reset());
	pi.on("session_tree", (_event, ctx) => {
		reset(true);
		restore(ctx);
	});
	pi.on("session_compact", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		const retained = visibleToolResults(ctx);
		inline.retain(retained);
		active.pending = active.pending.filter(({ row }) => retained.has(row.callId));
		active.queue = active.queue.filter(({ batch }) => {
			if (batch.rows.every(({ callId }) => retained.has(callId))) return true;
			batch.pending = false;
			batch.route = "no summary: batch compacted";
			return false;
		});
	});
	pi.on("message_update", (event, ctx) => {
		if (!autoEnabled(ctx) || event.message.role !== "assistant") return;
		for (const block of event.message.content) if (block.type === "toolCall") inline.track(block.id);
	});
	pi.on("tool_execution_start", (event, ctx) => {
		if (autoEnabled(ctx) && !event.parentToolCallId) inline.track(event.toolCallId);
	});
	pi.on("message_start", (event, ctx) => {
		if (autoEnabled(ctx) && event.message.role === "user") queueBatch(ctx, active.pending.splice(0));
	});
	pi.on("turn_end", (event, ctx) => {
		if (!autoEnabled(ctx) || event.message.role !== "assistant" || !event.toolResults.length) return;
		const size = count()!;
		const writer = settings.writer.kind;
		const local = writer === "ollama";
		const latestUser = local ? event.context.contextMessages.findLast((message) => message.role === "user") : undefined;
		const request = latestUser ? textExcerpt(latestUser.content) : undefined;
		const assistantNote = local ? textExcerpt(event.message.content) : undefined;
		const calls = event.message.content.filter((block) => block.type === "toolCall");
		for (const call of pairCalls(event.toolResults, calls)) {
			const row = { callId: call.result.toolCallId, failed: call.result.isError, activity: toolActivity(call, ctx.cwd) };
			const evidence = writer === "off" ? undefined : purposeCall(call, ctx.cwd);
			const pending: PendingRow = writer === "openrouter" && evidence
				? { row, hints: operationHints(evidence) }
				: { row, call: evidence, request, assistantNote };
			if (row.failed) {
				queueBatch(ctx, active.pending.splice(0));
				queueBatch(ctx, [pending]);
			} else {
				active.pending.push(pending);
				if (active.pending.length === size) queueBatch(ctx, active.pending.splice(0));
			}
		}
	});
	pi.on("agent_settled", (_event, ctx) => {
		const rows = active.pending.splice(0);
		if (autoEnabled(ctx)) queueBatch(ctx, rows);
		inline.releaseUnfinished();
	});

	pi.registerCommand("explain-tools", {
		description: "Explain recent tool output, control automatic explanations, or show batch history",
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
				ctx.ui.notify(`Automatic explanations: ${autoEnabled(ctx) ? "on" : "off"} · batch size: ${count() ?? "invalid"} · writer: ${route}`);
				return;
			}
			if (input === "on" || input === "off") {
				if (input === "on" && (!ctx.isProjectTrusted() || count() === undefined)) {
					ctx.ui.notify("Automatic explanations require a trusted project and a valid batch size.", "warning");
					return;
				}
				auto = input === "on";
				reset(true);
				restore(ctx);
				ctx.ui.notify(`Automatic tool explanations ${auto ? "on" : "off"} for this session.`);
				return;
			}
			if (!ctx.isIdle() || ctx.hasPendingMessages() || active.manual) {
				ctx.ui.notify("Wait until Pi is idle to open tool explanations.", "warning");
				return;
			}
			const session = active;
			const { signal } = session.controller;
			if (input === "recent") {
				if (!session.history.length) { ctx.ui.notify("No automatic explanations in this session yet."); return; }
				session.manual = true;
				try {
					const text = session.history.map(batchTitle).join("\n\n");
					await showView(ctx, "Recent tool explanations", text, signal);
				} finally { session.manual = false; }
				return;
			}
			if (!ctx.isProjectTrusted()) { ctx.ui.notify("Tool explanations require a trusted Pi session.", "warning"); return; }
			const requested = input ? parseCount(input) : count();
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
