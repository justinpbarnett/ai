import { Type } from "typebox";
import { getLatestCompactionEntry } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext, TurnEndEvent } from "@earendil-works/pi-coding-agent";
import { CHECKPOINT_TYPE, checkpointDraft, minimumSavings, preservesCut, selectCut, summarizeCut, tokenCount } from "./checkpoint.js";
import type { CheckpointRequest, Cut, SummaryResult } from "./checkpoint.js";
import { JEV_EXCERPT_LIMIT, JEV_MODEL, JEV_PROVIDER, NOTICE_FLAG, PressureCycle, TaskSwitchCandidates, WARN_FLAG, classifySwitch, pressure, resolvePolicy } from "./policy.js";

const TOOL = "self_compact";
const MAX_HANDOFF = 2000;
const JEV_OFF_FLAG = "no-self-compact-jev";
const USAGE = "/self-compact [status | now [focus] | jev on|off]";

interface BackgroundJob {
	cut: Cut;
	anchor: string;
	model: ExtensionContext["model"];
	controller: AbortController;
	result?: SummaryResult;
	handoff?: string;
	checking?: boolean;
	jevRequest?: AbortSignal;
}

function note(event: TurnEndEvent, text: string) {
	return { entries: [...event.entries, { type: "custom_message" as const, customType: CHECKPOINT_TYPE, content: text, display: false }] };
}

function lastSource(ctx: ExtensionContext) {
	const last = getLatestCompactionEntry(ctx.sessionManager.getBranch());
	if (!last) return "none";
	const details = last.details as { [CHECKPOINT_TYPE]?: { source?: string } } | undefined;
	const source = details?.[CHECKPOINT_TYPE]?.source;
	return source === "tool" ? TOOL : source === "jev" ? "JEV" : source === "background" ? "background pressure"
		: last.fromHook ? "other extension" : "native Pi";
}

export default function (pi: ExtensionAPI) {
	let jevOverride: "on" | "off" | "unavailable" | undefined;
	let jevStatus: "on" | "checking" | "deferred" = "on";
	let cycle = new PressureCycle();
	let job: BackgroundJob | undefined;
	let automaticAttempted = false;
	let observedCheckpoint: string | undefined;
	let staged: { toolCallId: string; handoff: string } | undefined;
	const candidates = new TaskSwitchCandidates();

	pi.registerFlag(NOTICE_FLAG, { type: "string", description: "Self-compaction notice threshold in tokens (6000, 6k) or percent (60%)" });
	pi.registerFlag(WARN_FLAG, { type: "string", description: "Self-compaction warning threshold in tokens (10000, 10k) or percent (80%)" });
	pi.registerFlag(JEV_OFF_FLAG, { type: "boolean", description: "Start Pi with JEV task-switch detection off" });

	function policy(ctx: ExtensionContext) {
		return resolvePolicy(pi.getSettings().compaction, ctx.model, ctx.getContextUsage(), pi.getFlag(NOTICE_FLAG), pi.getFlag(WARN_FLAG));
	}

	function jevMode(ctx: ExtensionContext) {
		if (ctx.mode !== "tui" || !ctx.isProjectTrusted()) return "off";
		const preference = jevOverride ?? (pi.getFlag(JEV_OFF_FLAG) === true ? "off" : "on");
		if (preference !== "on") return preference;
		return ctx.modelRegistry.getProviderAuthStatus(JEV_PROVIDER).configured &&
			ctx.modelRegistry.findOfType("classifier", JEV_PROVIDER, JEV_MODEL) ? "on" : "unavailable";
	}

	function backgroundStatus() {
		return !job ? "idle" : !job.result ? "summarizing" : "reason" in job.result ? "failed" : "ready";
	}

	function refresh(ctx: ExtensionContext) {
		const settings = policy(ctx);
		const band = pressure(settings);
		cycle.observe(ctx, band);
		const mode = jevMode(ctx);
		const jevLabel = mode === "unavailable" ? "off (unavailable)" : mode === "off" ? "off"
			: !settings.enabled || settings.problem ? "on (paused)" : jevStatus === "on" ? "on" : `on (${jevStatus})`;
		if (ctx.mode === "tui") {
			const pressureLabel = !settings.enabled ? "auto off" : settings.problem ? "policy unavailable" : band;
			const background = job ? ` (${backgroundStatus()})` : "";
			ctx.ui.setStatus(CHECKPOINT_TYPE, `compact: ${pressureLabel}${background} | JEV ${jevLabel}`);
		}
		return { settings, band, mode, jevLabel };
	}

	function discardJob() {
		job?.controller.abort();
		job = undefined;
		if (jevStatus === "checking") jevStatus = "on";
	}

	function reset() {
		discardJob();
		automaticAttempted = false;
		observedCheckpoint = undefined;
		cycle = new PressureCycle();
		staged = undefined;
		candidates.clear();
		jevStatus = "on";
	}

	function refreshTui(ctx: ExtensionContext) {
		if (ctx.mode === "tui") refresh(ctx);
	}

	pi.on("session_start", (_event, ctx) => { reset(); refreshTui(ctx); });
	pi.on("session_shutdown", () => { reset(); });
	pi.on("session_tree", (_event, ctx) => { reset(); refreshTui(ctx); });
	pi.on("model_select", (_event, ctx) => { reset(); refreshTui(ctx); });
	pi.on("session_before_compact", (_event, ctx) => { discardJob(); refreshTui(ctx); });
	pi.on("session_compact", (_event, ctx) => { refreshTui(ctx); });
	pi.on("session_compact_failed", (_event, ctx) => { refreshTui(ctx); });
	pi.on("turn_start", (_event, ctx) => { refreshTui(ctx); });
	pi.on("agent_settled", (event, ctx) => {
		staged = undefined;
		if (event.aborted) {
			candidates.clear();
			discardJob();
		}
		refreshTui(ctx);
	});

	pi.on("input", (event, ctx) => {
		if (jevMode(ctx) === "on") candidates.observeInput(event, ctx.isIdle());
		else if (ctx.mode === "tui") candidates.clear();
	});
	pi.on("before_agent_start", (event, ctx) => {
		if (jevMode(ctx) === "on") candidates.start(event.messageType === "user" && !event.images?.length ? event.prompt : undefined, ctx);
	});
	pi.on("user_bash", () => { candidates.clear(); });

	pi.registerTool({
		name: TOOL,
		label: "Self-compact",
		description: "Request a background context checkpoint without pausing work. Pi applies it at a safe turn boundary when ready.",
		promptSnippet: "Request an early context checkpoint with a short handoff when older context is no longer needed verbatim",
		promptGuidelines: ["When using self_compact, give the active goal, completion criteria or constraints, progress and blockers, and the immediate next action. Do not paste secrets, raw output, or entire files."],
		parameters: Type.Object({ handoff: Type.String({ minLength: 1, maxLength: MAX_HANDOFF }) }),
		async execute(toolCallId, params, signal, _onUpdate, ctx) {
			const handoff = params.handoff.trim();
			if (!handoff || handoff.length > MAX_HANDOFF) throw new Error(`Supply a handoff of 1 to ${MAX_HANDOFF} characters.`);
			if (signal?.aborted) throw new Error("Self-compaction request was cancelled.");
			if (staged || job?.handoff) throw new Error("A self-compaction request is already queued.");
			const settings = policy(ctx);
			const total = tokenCount(ctx.sessionManager.buildSessionProjection().entries);
			if (settings.keepRecentTokens === undefined || !ctx.model ||
				total - settings.keepRecentTokens <= minimumSavings(settings.tokens ?? total)) {
				throw new Error("Not enough older context to compact while keeping the recent tail.");
			}
			staged = { toolCallId, handoff };
			return {
				content: [{ type: "text", text: "Checkpoint requested. Keep working; Pi will apply it at a safe turn boundary when the summary is ready." }],
				details: { queued: true },
			};
		},
	});

	function startSummary(cut: Cut, anchor: string, model: BackgroundJob["model"], ctx: ExtensionContext, handoff?: string) {
		const started: BackgroundJob = { cut, anchor, model, controller: new AbortController(), handoff };
		job = started;
		automaticAttempted = true;
		void summarizeCut(cut, model, ctx.modelRegistry, started.controller.signal).then((result) => {
			if (job !== started) return;
			started.result = result;
			refreshTui(ctx);
		});
		refreshTui(ctx);
	}

	function checkTaskSwitch(started: BackgroundJob, ctx: ExtensionContext, pair: NonNullable<ReturnType<TaskSwitchCandidates["complete"]>>) {
		const candidate = candidates.signal;
		started.checking = true;
		jevStatus = "checking";
		refreshTui(ctx);
		void classifySwitch(ctx, pair, AbortSignal.any([started.controller.signal, candidate])).then((decision) => {
			if (job !== started) return;
			started.checking = false;
			if (candidate.aborted || jevMode(ctx) !== "on") {
				if (jevStatus === "checking") jevStatus = "on";
			} else if (decision === "unavailable") {
				jevOverride = "unavailable";
				jevStatus = "on";
				candidates.clear();
				ctx.ui.notify("JEV is unavailable and has switched off. Pi can still compact normally. Use /self-compact jev on to retry.", "info");
			} else {
				jevStatus = decision === "switch" ? "on" : "deferred";
				if (decision === "switch") started.jevRequest = candidate;
			}
			refreshTui(ctx);
		});
	}

	pi.on("turn_end", (event, ctx) => {
		const pending = staged;
		staged = undefined;
		const { settings, band, mode } = refresh(ctx);
		if (event.outcome !== "completed" || event.message.role !== "assistant" || event.message.stopReason === "length" || ctx.signal?.aborted) {
			candidates.clear();
			return;
		}
		const pair = mode === "on" ? candidates.complete(event.context.contextEntries) : undefined;
		const explicit = pending && event.toolResults.some((result) =>
			result.toolCallId === pending.toolCallId && result.toolName === TOOL && !result.isError) ? pending.handoff : undefined;
		const canContinueNaturally = event.continue || event.toolResults.length > 0 || event.context.pendingMessages.length > 0;
		const auto = settings.enabled && !settings.problem;
		const underPressure = auto && (band === "notice" || band === "warning");
		const nativeCutoff = auto && band === "native cutoff";
		const model = ctx.model?.api === "pi-virtual" ? ctx.modelRegistry.find(event.message.provider, event.message.model) : ctx.model;
		const latest = getLatestCompactionEntry(ctx.sessionManager.getBranch())?.id;
		if (latest !== observedCheckpoint || band === "normal") {
			automaticAttempted = false;
			observedCheckpoint = latest;
		}
		let failure: string | undefined;
		if (job && (!model || job.model?.provider !== model.provider || job.model.id !== model.id ||
			settings.keepRecentTokens === undefined || !preservesCut(job.cut, job.anchor, event, ctx, settings.keepRecentTokens))) {
			if (job.handoff) failure = "the saved cut is no longer safe";
			discardJob();
		}
		if (job && !job.handoff && !explicit && (!auto || band === "normal")) discardJob();
		if (job?.result && "reason" in job.result) {
			if (job.handoff) failure = job.result.reason;
			discardJob();
		}
		if (job && explicit) job.handoff = explicit;

		if (job?.result) {
			const requested: CheckpointRequest | undefined = job.handoff ? { source: "tool", handoff: job.handoff }
				: underPressure && mode === "on" && job.jevRequest && !job.jevRequest.aborted && !ctx.hasPendingMessages() ? { source: "jev" }
				: auto && (band === "warning" || nativeCutoff) ? { source: "background" } : undefined;
			if (requested) {
				const draft = checkpointDraft(job.cut, job.result, requested, settings.tokens ?? tokenCount(event.context.contextEntries));
				discardJob();
				if ("type" in draft) return { entries: [...event.entries, draft] };
				if (requested.source === "tool") failure = draft.reason;
			}
		}

		if (!job && !nativeCutoff && (explicit || (underPressure && !automaticAttempted))) {
			const anchor = ctx.sessionManager.getLeafId();
			const cut = settings.keepRecentTokens === undefined ? undefined : selectCut(event, ctx, settings.keepRecentTokens, settings.tokens);
			if (anchor && cut) startSummary(cut, anchor, model, ctx, explicit);
			else if (explicit) failure = "no safe cut with enough reclaimable context";
		} else if (explicit && !job && nativeCutoff) {
			failure = "the native cutoff has been reached";
		}
		if (job && !job.handoff && !job.checking && (!job.jevRequest || job.jevRequest.aborted) &&
			pair && underPressure && !ctx.hasPendingMessages()) checkTaskSwitch(job, ctx, pair);
		if (failure && canContinueNaturally) return note(event, `Self-compaction skipped: ${failure}.`);
		if (!underPressure || !canContinueNaturally || !pi.getActiveTools().includes(TOOL) ||
			event.entries.some((entry) => entry.type === "compaction")) return;
		const notice = cycle.takeNotice(band);
		if (notice === "warning") return note(event, "Context warning: Pi can apply a ready background checkpoint at a safe boundary. Native compaction remains the backstop.");
		if (notice === "notice") return note(event, "Context notice: Pi can prepare a background checkpoint. Call self_compact to request an early swap with a handoff.");
	});

	pi.registerCommand("self-compact", {
		description: "Show context pressure, compact while idle, or toggle JEV task-switch detection",
		getArgumentCompletions: (prefix) => ["status", "now", "jev on", "jev off"].filter((arg) => arg.startsWith(prefix))
			.map((arg) => ({ value: arg, label: arg })),
		async handler(args, ctx) {
			const [command, ...rest] = args.trim().split(/\s+/);
			if (!command || (command === "status" && !rest.length)) {
				const { settings, band, mode, jevLabel } = refresh(ctx);
				const threshold = (tokens: number | null | undefined) => tokens == null ? "unknown" :
					`${tokens.toLocaleString()} tokens${settings.window ? ` (${(100 * tokens / settings.window).toFixed(1)}%)` : ""}`;
				ctx.ui.notify([
					`Context: ${threshold(settings.tokens)}${band === "unknown" ? "" : ` (${band})`}`,
					`Notice: ${threshold(settings.notice)} | Warning: ${threshold(settings.warning)} | Native cutoff: ${threshold(settings.hard)}`,
					`Native auto-compaction: ${settings.enabled ? "on" : "off"}${settings.problem ? ` | Extension automation paused: ${settings.problem}` : ""}`,
					`Background: ${backgroundStatus()} | Last checkpoint: ${lastSource(ctx)} | JEV: ${jevLabel}`,
					...(mode === "on" ? [`JEV can send up to ${JEV_EXCERPT_LIMIT} characters from each of two new prompts to OpenRouter under context pressure. Use /self-compact jev off to disable.`] : []),
				].join("\n"), "info");
				return;
			}
			if (command === "now") {
				if (!ctx.isIdle() || ctx.hasPendingMessages()) {
					ctx.ui.notify("Pi is busy. Wait until it is idle to compact manually.", "warning");
					return;
				}
				const focus = args.trim().slice(command.length).trim();
				ctx.compact({
					customInstructions: focus || undefined,
					onComplete: () => ctx.ui.notify("Native compaction complete.", "info"),
					onError: () => ctx.ui.notify("Native compaction did not complete.", "warning"),
				});
				return;
			}
			if (command === "jev" && rest.length === 1 && (rest[0] === "on" || rest[0] === "off")) {
				const enable = rest[0] === "on";
				if (enable && (ctx.mode !== "tui" || !ctx.isProjectTrusted())) {
					ctx.ui.notify("JEV requires a trusted TUI session.", "warning");
					return;
				}
				jevOverride = enable ? "on" : "off";
				candidates.clear();
				jevStatus = "on";
				const { mode } = refresh(ctx);
				ctx.ui.notify(!enable ? "JEV off. Stored prompt excerpts cleared."
					: mode === "unavailable" ? `JEV stays off: OpenRouter credentials or ${JEV_MODEL} are unavailable. Pi can still compact normally.`
					: `JEV on: OpenRouter / ${JEV_MODEL} can receive up to ${JEV_EXCERPT_LIMIT} characters each of two consecutive new user prompts under context pressure. Turn it off for sensitive work.`, "info");
				return;
			}
			ctx.ui.notify(`Usage: ${USAGE}`, "warning");
		},
	});
}
