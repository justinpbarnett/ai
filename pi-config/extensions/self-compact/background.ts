import { getLatestCompactionEntry } from "@earendil-works/pi-coding-agent";
import type { ExtensionContext, TurnEndEvent } from "@earendil-works/pi-coding-agent";
import { checkpointDraft, minimumSavings, preservesCut, selectCut, summarizeCut, tokenCount } from "./checkpoint.js";
import type { CheckpointRequest, Cut, SummaryResult } from "./checkpoint.js";
import type { Jev } from "./jev.js";
import type { Policy, Pressure } from "./policy.js";

export const SELF_COMPACT_TOOL = "self_compact";
export const MAX_HANDOFF = 2000;

type Model = ExtensionContext["model"];
interface BackgroundJob {
	cut: Cut;
	anchor: string;
	model: Model;
	controller: AbortController;
	result?: SummaryResult;
	handoff?: string;
	jevRequest?: AbortSignal;
}

interface Turn {
	event: TurnEndEvent;
	ctx: ExtensionContext;
	settings: Policy;
	model: Model;
	underPressure: boolean;
	nativeCutoff: boolean;
	band: Pressure;
	mode: ReturnType<Jev["mode"]>;
}

function completed(event: TurnEndEvent, ctx: ExtensionContext) {
	return event.outcome === "completed" && event.message.role === "assistant" &&
		event.message.stopReason !== "length" && !ctx.signal?.aborted;
}

function modelForTurn(event: TurnEndEvent, ctx: ExtensionContext) {
	if (ctx.model?.api !== "pi-virtual" || event.message.role !== "assistant") return ctx.model;
	return ctx.modelRegistry.find(event.message.provider, event.message.model);
}

function autoEnabled(settings: Policy) { return settings.enabled && !settings.problem; }
function canUseJev(turn: Turn) { return turn.underPressure && turn.mode === "on" && !turn.ctx.hasPendingMessages(); }

function requestForTurn(turn: Turn, job: BackgroundJob): CheckpointRequest | undefined {
	if (job.handoff) return { source: "tool", handoff: job.handoff };
	if (job.jevRequest && !job.jevRequest.aborted && canUseJev(turn)) return { source: "jev" };
	if (autoEnabled(turn.settings) && (turn.band === "warning" || turn.nativeCutoff)) return { source: "background" };
}

export class BackgroundCompaction {
	private job?: BackgroundJob;
	private automaticAttempted = false;
	private observedCheckpoint?: string;
	private staged?: { toolCallId: string; handoff: string };

	constructor(private readonly jev: Jev, private readonly onStatusChange: (ctx: ExtensionContext) => void) {}

	status() {
		if (!this.job) return "idle";
		if (!this.job.result) return "summarizing";
		return "reason" in this.job.result ? "failed" : "ready";
	}

	queue(toolCallId: string, text: string, signal: AbortSignal | undefined, ctx: ExtensionContext, settings: Policy) {
		const handoff = text.trim();
		if (!handoff || handoff.length > MAX_HANDOFF) throw new Error(`Supply a handoff of 1 to ${MAX_HANDOFF} characters.`);
		if (signal?.aborted) throw new Error("Self-compaction request was cancelled.");
		if (this.staged || this.job?.handoff) throw new Error("A self-compaction request is already queued.");
		const total = tokenCount(ctx.sessionManager.buildSessionProjection().entries);
		if (settings.keepRecentTokens === undefined || !ctx.model ||
			total - settings.keepRecentTokens <= minimumSavings(settings.tokens ?? total)) {
			throw new Error("Not enough older context to compact while keeping the recent tail.");
		}
		this.staged = { toolCallId, handoff };
	}

	discard() {
		this.job?.controller.abort();
		this.job = undefined;
		this.jev.cancelCheck();
	}

	reset() {
		this.discard();
		this.automaticAttempted = false;
		this.observedCheckpoint = undefined;
		this.staged = undefined;
	}

	settle(aborted: boolean) {
		this.staged = undefined;
		if (aborted) {
			this.jev.clearInput();
			this.discard();
		}
	}

	advance(event: TurnEndEvent, ctx: ExtensionContext, settings: Policy, band: Pressure, checkpointId: string | undefined) {
		const explicit = this.takeHandoff(event);
		if (!completed(event, ctx)) {
			this.jev.clearInput();
			return;
		}

		const auto = autoEnabled(settings);
		const mode = this.jev.mode(ctx);
		const pair = this.jev.takePair(event.context.contextEntries, mode);
		const turn: Turn = {
			event, ctx, settings, band, mode,
			model: modelForTurn(event, ctx),
			underPressure: auto && (band === "notice" || band === "warning"),
			nativeCutoff: auto && band === "native cutoff",
		};
		this.observePressure(checkpointId, band);
		const previousFailure = this.reconcile(turn, explicit);
		const draft = this.publishReady(turn);
		if (draft && "type" in draft) return { draft };
		const schedulingFailure = this.schedule(turn, explicit);
		this.checkTaskSwitch(turn, pair);
		return { failure: schedulingFailure ?? draft?.reason ?? previousFailure };
	}

	private takeHandoff(event: TurnEndEvent) {
		const pending = this.staged;
		this.staged = undefined;
		if (pending && event.toolResults.some((result) =>
			result.toolCallId === pending.toolCallId && result.toolName === SELF_COMPACT_TOOL && !result.isError)) return pending.handoff;
	}

	private observePressure(checkpointId: string | undefined, band: Pressure) {
		if (checkpointId !== this.observedCheckpoint || band === "normal") {
			this.automaticAttempted = false;
			this.observedCheckpoint = checkpointId;
		}
	}

	private stillSafe(job: BackgroundJob, { event, ctx, model, settings }: Turn) {
		return model && job.model?.provider === model.provider && job.model.id === model.id && settings.keepRecentTokens !== undefined &&
			preservesCut(job.cut, job.anchor, event, ctx, settings.keepRecentTokens);
	}

	private reconcile(turn: Turn, explicit: string | undefined) {
		const job = this.job;
		if (!job) return;
		if (!this.stillSafe(job, turn)) {
			this.discard();
			return job.handoff ? "the saved cut is no longer safe" : undefined;
		}
		if (!job.handoff && !explicit && (!autoEnabled(turn.settings) || turn.band === "normal")) {
			this.discard();
			return;
		}
		if (job.result && "reason" in job.result) {
			this.discard();
			return job.handoff ? job.result.reason : undefined;
		}
		if (explicit) job.handoff = explicit;
	}

	private publishReady(turn: Turn) {
		const job = this.job;
		if (!job?.result) return;
		const request = requestForTurn(turn, job);
		if (!request) return;
		const usage = turn.settings.tokens ?? tokenCount(turn.event.context.contextEntries);
		const draft = checkpointDraft(job.cut, job.result, request, usage);
		this.discard();
		if ("type" in draft || request.source === "tool") return draft;
	}

	private schedule(turn: Turn, explicit: string | undefined) {
		if (this.job) return;
		if (turn.nativeCutoff) return explicit ? "the native cutoff has been reached" : undefined;
		if (!explicit && (!turn.underPressure || this.automaticAttempted)) return;
		const anchor = turn.ctx.sessionManager.getLeafId();
		const { keepRecentTokens, tokens } = turn.settings;
		const cut = keepRecentTokens === undefined ? undefined : selectCut(turn.event, turn.ctx, keepRecentTokens, tokens);
		if (anchor && cut) this.startSummary(turn, cut, anchor, explicit);
		else if (explicit) return "no safe cut with enough reclaimable context";
	}

	private startSummary({ model, ctx }: Turn, cut: Cut, anchor: string, handoff?: string) {
		const started: BackgroundJob = { cut, anchor, model, controller: new AbortController(), handoff };
		this.job = started;
		this.automaticAttempted = true;
		void summarizeCut(cut, model, ctx.modelRegistry, started.controller.signal).then((result) => {
			if (this.job !== started) return;
			started.result = result;
			this.onStatusChange(ctx);
		});
	}

	private checkTaskSwitch(turn: Turn, pair: ReturnType<Jev["takePair"]>) {
		const job = this.job;
		if (!pair || !job || job.handoff || (job.jevRequest && !job.jevRequest.aborted) || !canUseJev(turn)) return;
		this.jev.check(turn.ctx, pair, job.controller.signal, (candidate) => { job.jevRequest = candidate; });
	}
}

export function currentCheckpoint(ctx: ExtensionContext) {
	return getLatestCompactionEntry(ctx.sessionManager.getBranch());
}
