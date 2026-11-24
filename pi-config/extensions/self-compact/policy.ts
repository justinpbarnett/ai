import { DEFAULT_COMPACTION_SETTINGS } from "@earendil-works/pi-coding-agent";
import type { ContextUsage, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export const NOTICE_FLAG = "self-compact-notice-at";
export const WARN_FLAG = "self-compact-warn-at";

export type Pressure = "unknown" | "normal" | "notice" | "warning" | "native cutoff";
type CompactionSettings = ReturnType<ExtensionAPI["getSettings"]>["compaction"];

export function readPolicy(pi: ExtensionAPI, ctx: ExtensionContext) {
	return resolvePolicy(pi.getSettings().compaction, ctx.model, ctx.getContextUsage(), pi.getFlag(NOTICE_FLAG), pi.getFlag(WARN_FLAG));
}

function nativeTokenSetting(settings: CompactionSettings, modelKey: string | undefined, key: "reserveTokens" | "keepRecentTokens") {
	const override = modelKey === undefined ? undefined : settings?.modelOverrides?.[modelKey]?.[key];
	const tokens = override ?? settings?.[key] ?? DEFAULT_COMPACTION_SETTINGS[key];
	return Number.isSafeInteger(tokens) && tokens >= 0 ? tokens : undefined;
}

function policyProblem(window: number | undefined, keepRecentTokens: number | undefined, thresholds: {
	hard: number | undefined;
	notice: number | undefined;
	warning: number | undefined;
}, flags: { notice: unknown; warning: unknown }) {
	const { hard, notice, warning } = thresholds;
	if (!window) return "model limits unavailable";
	if (keepRecentTokens === undefined || !hard || hard < 0) return "invalid native compaction limits";
	if (flags.notice !== undefined && !notice) return `invalid --${NOTICE_FLAG} value`;
	if (flags.warning !== undefined && !warning) return `invalid --${WARN_FLAG} value`;
	if (!notice || !warning || notice >= warning || warning >= hard) return "require 0 < notice < warning < native cutoff";
}

function resolvePolicy(settings: CompactionSettings, model: ExtensionContext["model"], usage: ContextUsage | undefined, noticeFlag: unknown, warnFlag: unknown) {
	const modelKey = model && `${model.provider}/${model.id}`;
	const enabled = settings?.enabled ?? DEFAULT_COMPACTION_SETTINGS.enabled;
	const reserve = nativeTokenSetting(settings, modelKey, "reserveTokens");
	const keepRecentTokens = nativeTokenSetting(settings, modelKey, "keepRecentTokens");
	const window = usage?.contextWindow;
	const hard = window && reserve !== undefined ? window - reserve : undefined;
	const thresholds = {
		hard,
		notice: parseThreshold(noticeFlag, window, hard, 0.6),
		warning: parseThreshold(warnFlag, window, hard, 0.8),
	};
	const problem = policyProblem(window, keepRecentTokens, thresholds, { notice: noticeFlag, warning: warnFlag });
	return { enabled, window, ...thresholds, keepRecentTokens, problem, tokens: usage?.tokens ?? null };
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

export const autoEnabled = (settings: Policy) => settings.enabled && !settings.problem;

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
	private automaticAttempted = false;

	get automaticAlreadyAttempted() { return this.automaticAttempted; }

	recordAutomaticAttempt() { this.automaticAttempted = true; }

	reset() {
		this.checkpointId = undefined;
		this.waitingForRelief = false;
		this.notified = 0;
		this.automaticAttempted = false;
	}

	observe(checkpointId: string | undefined, band: Pressure) {
		const checkpointChanged = checkpointId !== this.checkpointId;
		if (checkpointChanged || band === "normal") this.automaticAttempted = false;
		if (checkpointChanged) {
			this.checkpointId = checkpointId;
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
