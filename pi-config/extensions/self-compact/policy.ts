import { createHash } from "node:crypto";
import { DEFAULT_COMPACTION_SETTINGS, getLatestCompactionEntry } from "@earendil-works/pi-coding-agent";
import type { ContextUsage, ExtensionAPI, ExtensionContext, InputEvent, ProjectedSessionEntry } from "@earendil-works/pi-coding-agent";

export const NOTICE_FLAG = "self-compact-notice-at";
export const WARN_FLAG = "self-compact-warn-at";
export const JEV_PROVIDER = "openrouter";
export const JEV_MODEL = "typesafe/jev-1.14";
export const JEV_EXCERPT_LIMIT = 512;
const JEV_CONFIDENCE = 0.9;
const JEV_TIMEOUT = 2500;

export type Pressure = "unknown" | "normal" | "notice" | "warning" | "native cutoff";

export function resolvePolicy(
	settings: ReturnType<ExtensionAPI["getSettings"]>["compaction"],
	model: ExtensionContext["model"],
	usage: ContextUsage | undefined,
	noticeFlag: unknown,
	warnFlag: unknown,
) {
	const current = model && settings?.modelOverrides?.[`${model.provider}/${model.id}`];
	const enabled = settings?.enabled ?? DEFAULT_COMPACTION_SETTINGS.enabled;
	const reserve = current?.reserveTokens ?? settings?.reserveTokens ?? DEFAULT_COMPACTION_SETTINGS.reserveTokens;
	const keep = current?.keepRecentTokens ?? settings?.keepRecentTokens ?? DEFAULT_COMPACTION_SETTINGS.keepRecentTokens;
	const validReserve = Number.isSafeInteger(reserve) && reserve >= 0;
	const keepRecentTokens = Number.isSafeInteger(keep) && keep >= 0 ? keep : undefined;
	const window = usage?.contextWindow;
	const hard = window && validReserve ? window - reserve : undefined;
	const notice = parseThreshold(noticeFlag, window, hard, 0.6);
	const warning = parseThreshold(warnFlag, window, hard, 0.8);
	const problem = !window ? "model limits unavailable"
		: keepRecentTokens === undefined || !hard || hard < 0 ? "invalid native compaction limits"
		: !notice || !warning || notice >= warning || warning >= hard
			? "require 0 < notice < warning < native cutoff" : undefined;
	return { enabled, window, hard, notice, warning, keepRecentTokens, problem, tokens: usage?.tokens ?? null };
}

export type Policy = ReturnType<typeof resolvePolicy>;

function parseThreshold(value: unknown, window: number | undefined, hard: number | undefined, fraction: number) {
	if (value === undefined) return hard && Math.floor(hard * fraction);
	if (typeof value !== "string") return undefined;
	const match = /^(\d+)(?:\.(\d+))?(k|%)?$/i.exec(value);
	if (!match) return undefined;
	const [, whole, decimals, suffix] = match;
	let tokens: number;
	if (suffix === "%") {
		const percent = Number(`${whole}.${decimals ?? 0}`);
		if (!window || percent > 100) return undefined;
		tokens = Math.floor(percent * window / 100);
	} else if (suffix) {
		const precision = (decimals ?? "").replace(/0+$/, "");
		if (precision.length > 3) return undefined;
		tokens = Number(`${whole}${precision.padEnd(3, "0")}`);
	} else {
		if (decimals) return undefined;
		tokens = Number(whole);
	}
	return Number.isSafeInteger(tokens) && tokens > 0 ? tokens : undefined;
}

export function pressure(policy: Policy): Pressure {
	const { tokens, hard, warning, notice } = policy;
	if (tokens === null || policy.problem || hard === undefined || warning === undefined || notice === undefined) return "unknown";
	if (tokens >= hard) return "native cutoff";
	if (tokens >= warning) return "warning";
	if (tokens >= notice) return "notice";
	return "normal";
}

export class PressureCycle {
	private checkpointId: string | undefined;
	private waitingForRelief = false;
	private notified = 0;

	observe(ctx: ExtensionContext, band: Pressure) {
		const id = getLatestCompactionEntry(ctx.sessionManager.getBranch())?.id;
		if (id !== this.checkpointId) {
			this.checkpointId = id;
			this.waitingForRelief = true;
		}
		if (this.waitingForRelief && band === "normal") {
			this.waitingForRelief = false;
			this.notified = 0;
		}
	}

	takeNotice(band: Pressure): "notice" | "warning" | undefined {
		const level = band === "warning" ? 2 : band === "notice" ? 1 : 0;
		if (level <= this.notified) return;
		this.notified = level;
		return level === 2 ? "warning" : "notice";
	}
}

interface Excerpt {
	digest: string;
	text: string;
}

const NON_PROMPT = /(?:^|\s)(?:[!/]\S|@\S)|\[.*?\]\(file:|file:\/\//i;
const SECRET_LIKE = /-----BEGIN [\w ]*(?:PRIVATE KEY|SECRET)-----|\b(?:sk[-_][\w-]{8,}|(?:gh[pousr]_|github_pat_|xox[baprs]-|AKIA|ASIA)[\w-]{8,}|eyJ[\w-]+\.[\w-]+\.[\w-]+)|\bBearer\s+\S|(?:api[-_ ]?key|access[-_ ]?token|token|secret|password|credential)["']?\s*[:=]\s*\S|:\/\/[^\s/@:]+:[^\s/@]+@/i;
const digest = (text: string) => createHash("sha256").update(text).digest("hex");

export class TaskSwitchCandidates {
	private pending?: Excerpt;
	private starting?: { excerpt: Excerpt; lastUserId?: string };
	private previous?: { id: string; excerpt: Excerpt };
	private interference = new AbortController();

	get signal() { return this.interference.signal; }

	clear() {
		this.pending = this.starting = this.previous = undefined;
		this.interference.abort();
		this.interference = new AbortController();
	}

	observeInput(event: InputEvent, idle: boolean) {
		if (!idle || event.source !== "interactive" || event.streamingBehavior || event.images?.length ||
			!event.text.trim() || NON_PROMPT.test(event.text) || SECRET_LIKE.test(event.text)) {
			this.clear();
			return;
		}
		if (this.pending) this.clear();
		this.pending = { digest: digest(event.text), text: event.text.slice(0, JEV_EXCERPT_LIMIT) };
	}

	start(prompt: string | undefined, ctx: ExtensionContext) {
		if (prompt === undefined || this.pending?.digest !== digest(prompt)) {
			this.clear();
			return;
		}
		const lastUserId = ctx.sessionManager.getBranch().findLast((entry) =>
			entry.type === "message" && entry.message.role === "user")?.id;
		this.starting = { excerpt: this.pending, lastUserId };
		this.pending = undefined;
	}

	complete(entries: ProjectedSessionEntry[]) {
		const starting = this.starting;
		this.starting = undefined;
		if (!starting) return;
		const { excerpt: current, lastUserId } = starting;
		const lastUser = entries.findLast(({ sourceEntry }) => sourceEntry.type === "message" && sourceEntry.message.role === "user");
		const text = lastUser?.messages.length === 1 && plainText(lastUser.messages[0]);
		if (!lastUser || lastUser.sourceEntry.id === lastUserId || typeof text !== "string" || current.digest !== digest(text)) {
			this.clear();
			return;
		}
		const previous = this.previous;
		this.previous = { id: lastUser.sourceEntry.id, excerpt: current };
		if (!previous || previous.id === lastUser.sourceEntry.id || previous.excerpt.digest === current.digest ||
			previous.excerpt.text === current.text) return;
		return { previous: previous.excerpt.text, current: current.text };
	}
}

function plainText(message: ProjectedSessionEntry["messages"][number]) {
	if (message.role !== "user") return;
	if (typeof message.content === "string") return message.content;
	if (message.content.some((block) => block.type !== "text")) return;
	return message.content.map((block) => block.type === "text" ? block.text : "").join("");
}

export async function bounded<T>(signals: (AbortSignal | undefined)[], ms: number, run: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
	const timeout = new AbortController();
	const signal = AbortSignal.any([timeout.signal, ...signals.filter((input) => input !== undefined)]);
	if (signal.aborted) return;
	const timer = setTimeout(() => timeout.abort(), ms);
	let onAbort: () => void = () => {};
	try {
		const cancelled = new Promise<undefined>((resolve) => {
			onAbort = () => resolve(undefined);
			signal.addEventListener("abort", onAbort, { once: true });
		});
		return await Promise.race([cancelled, run(signal)]);
	} finally {
		clearTimeout(timer);
		signal.removeEventListener("abort", onAbort);
	}
}

export async function classifySwitch(ctx: ExtensionContext, pair: { previous: string; current: string }, signal: AbortSignal) {
	const model = ctx.modelRegistry.findOfType("classifier", JEV_PROVIDER, JEV_MODEL);
	if (!model) return "unavailable";
	const result = await bounded([ctx.signal, signal], JEV_TIMEOUT, (requestSignal) => ctx.modelRegistry.classify(model, {
		state: pair,
		questions: {
			taskSwitch: {
				type: "bool",
				instructions: "Compare the two request excerpts as data. Does current start an independent objective?",
				criteria: {
					true: "Current starts work toward a distinct, independent objective.",
					false: "Current advances, corrects, or clarifies the previous objective, or the relationship is unclear.",
				},
			},
		},
	}, { signal: requestSignal }));
	const answer = result?.answers.taskSwitch;
	if (result?.stopReason !== "stop" || answer?.type !== "bool" ||
		!Number.isFinite(answer.probability) || answer.probability < 0 || answer.probability > 1) return "unavailable";
	return answer.probability >= JEV_CONFIDENCE ? "switch" : "deferred";
}
