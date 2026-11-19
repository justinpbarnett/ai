import { readFileSync } from "node:fs";
import { join } from "node:path";
import { getAgentDir, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DEFAULT_OLLAMA_MODEL, isLocalOllamaModel } from "../shared/ollama.js";
import { autoRow, manualRows, pairCalls, recentCalls, shellCommand, summarizeBatch } from "./evidence.js";
import { ExplanationError } from "./explain.js";
import { batchTitle, InlineToolOutput, type Batch, type InlineRow } from "./inline.js";
import { collectExplanation, explanationText, preview, showView } from "./view.js";
import { commandHints, DEFAULT_OPENROUTER_MODEL, writeSummary, type Writer, type WritingRequest } from "./writer.js";

const COUNT_FLAG = "explain-tools-count";
const NO_AUTO_FLAG = "explain-tools-no-auto";
const DEFAULT_COUNT = 2;
const MAX_HISTORY = 12;
const MAX_AUTO_REQUESTS = 4;
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

type PendingRow = { row: InlineRow; command?: string; hints?: string[] };
type Job = { batch: Batch; request: WritingRequest; targets: Set<InlineRow> };

function state() {
	return {
		controller: new AbortController(), pending: [] as PendingRow[], history: [] as Batch[],
		queue: [] as Job[], running: false, manual: false,
	};
}

function prepareJob(batch: Batch, pending: PendingRow[], writer: Writer): Job | undefined {
	if (writer.kind === "off") return;
	if (writer.kind === "ollama") {
		const candidates = pending.filter((item): item is PendingRow & { command: string } => Boolean(item.command));
		const commands = candidates.map(({ command }) => command);
		if (!commands.length || Buffer.byteLength(JSON.stringify(commands), "utf8") > 2_048) return;
		return { batch, request: { ...writer, kind: "ollama", commands }, targets: new Set(candidates.map(({ row }) => row)) };
	}
	const candidates = pending.filter((item): item is PendingRow & { hints: string[] } => Boolean(item.hints?.length));
	if (!candidates.length) return;
	return { batch, request: { ...writer, kind: "openrouter", hints: candidates.map(({ hints }) => hints) }, targets: new Set(candidates.map(({ row }) => row)) };
}

export default function (pi: ExtensionAPI) {
	const inline = new InlineToolOutput();
	let active = state();
	let settings = defaults;
	let auto = true;
	let renderInline = false;

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

	async function drain(ctx: ExtensionContext, session: ReturnType<typeof state>) {
		if (session.running) return;
		session.running = true;
		const { signal } = session.controller;
		const registry = ctx.modelRegistry;
		try {
			while (!signal.aborted && session.queue.length) {
				const { batch, request, targets } = session.queue.shift()!;
				try {
					const text = await writeSummary(registry, request, signal);
					if (signal.aborted) break;
					batch.summary = summarizeBatch(batch.rows, { rows: targets, text });
					batch.route = `${request.kind}/${request.model}`;
					inline.update(batch);
				} catch (error) {
					const reason = error instanceof ExplanationError ? error.message : `Could not reach ${request.kind}.`;
					batch.route = `no model: ${reason}`;
				}
			}
		} finally {
			session.running = false;
		}
	}

	function queueBatch(ctx: ExtensionContext, pending: PendingRow[]) {
		if (!pending.length) return;
		const session = active;
		const rows = pending.map(({ row }) => row);
		const batch: Batch = { rows, summary: summarizeBatch(rows), route: "no model" };
		const job = prepareJob(batch, pending, settings.writer);
		if (job?.request.kind === "openrouter" && offline()) batch.route = "no model: Pi is offline";
		else if (job && session.queue.length + Number(session.running) >= MAX_AUTO_REQUESTS) batch.route = "no model: writer queue is full";
		else if (job) {
			batch.route = `${job.request.kind}/${job.request.model} pending`;
			session.queue.push(job);
		}
		session.history.unshift(batch);
		if (session.history.length > MAX_HISTORY) session.history.pop();
		inline.place(batch);
		if (session.queue.length) void drain(ctx, session);
	}

	function autoEnabled(ctx: ExtensionContext) {
		return auto && ctx.mode === "tui" && ctx.isProjectTrusted() && count() !== undefined;
	}

	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		const loaded = config();
		settings = loaded;
		auto = settings.auto && !pi.getFlag(NO_AUTO_FLAG);
		renderInline = autoEnabled(ctx);
		if (loaded.warning) ctx.ui.notify(loaded.warning, "warning");
		if (count() === undefined) ctx.ui.notify(`--${COUNT_FLAG} must be 1 to 10. Automatic explanations are disabled.`, "warning");
	});
	pi.on("session_shutdown", () => { renderInline = false; reset(); });
	pi.on("session_tree", () => reset(true));
	pi.on("session_compact", (_event, ctx) => {
		if (!autoEnabled(ctx)) return;
		const retained = new Set(ctx.sessionManager.buildContextEntries().flatMap((entry) =>
			entry.type === "message" && entry.message.role === "toolResult" ? [entry.message.toolCallId] : []));
		inline.retain(retained);
		active.pending = active.pending.filter(({ row }) => retained.has(row.callId));
		active.queue = active.queue.filter(({ batch }) => {
			if (batch.rows.every(({ callId }) => retained.has(callId))) return true;
			batch.route = "no model: batch compacted";
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
	pi.on("turn_end", (event, ctx) => {
		if (!autoEnabled(ctx) || event.message.role !== "assistant") return;
		const size = count()!;
		const calls = event.message.content.filter((block) => block.type === "toolCall");
		for (const call of pairCalls(event.toolResults, calls)) {
			const row = { ...autoRow(call, ctx.cwd), callId: call.result.toolCallId };
			const writer = settings.writer.kind;
			const command = row.facts.action === "shell" && !row.facts.failed && writer !== "off"
				? shellCommand(call) : undefined;
			active.pending.push({
				row,
				command: writer === "ollama" ? command : undefined,
				hints: writer === "openrouter" && command ? commandHints(command) : undefined,
			});
			if (active.pending.length === size) queueBatch(ctx, active.pending.splice(0));
		}
	});
	pi.on("agent_settled", (_event, ctx) => {
		const rows = active.pending.splice(0);
		if (autoEnabled(ctx)) queueBatch(ctx, rows);
		inline.releaseUnfinished();
	});

	pi.registerCommand("explain-tools", {
		description: "Explain recent tool output, control automatic explanations, or show batch history",
		getArgumentCompletions: (prefix) => ["1", "2", "on", "off", "status", "recent"]
			.filter((value) => prefix && value.startsWith(prefix) && value !== prefix).map((value) => ({ value, label: value })),
		async handler(args, ctx) {
			if (ctx.mode !== "tui") return;
			const input = args.trim();
			if (input === "status") {
				const { writer } = settings;
				const route = !ctx.isProjectTrusted() ? "untrusted project"
					: writer.kind === "off" ? "no model"
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
				renderInline = autoEnabled(ctx);
				reset(true);
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
					const text = session.history.map((batch) => [batchTitle(batch), ...batch.rows.map(({ text }) => `  ${text}`)].join("\n")).join("\n\n");
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
