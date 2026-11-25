import { Type } from "typebox";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { MAX_HANDOFF, SELF_COMPACT_TOOL } from "./background.js";
import type { BackgroundCompaction } from "./background.js";
import { checkpointOrigin } from "./checkpoint.js";
import { JEV_EXCERPT_LIMIT } from "./jev.js";
import type { Jev } from "./jev.js";
import { pressure, readPolicy } from "./policy.js";

const USAGE = "/self-compact [status | now [focus] | jev on|off]";

function lastSource(ctx: ExtensionContext) {
	switch (checkpointOrigin(ctx)) {
		case "tool": return SELF_COMPACT_TOOL;
		case "jev": return "JEV";
		case "background": return "background pressure";
		case "other extension": return "other extension";
		case "native Pi": return "native Pi";
		case "none": return "none";
	}
}

function formatTokens(tokens: number | null | undefined, window: number | undefined) {
	if (tokens == null) return "unknown";
	const percent = window ? ` (${(100 * tokens / window).toFixed(1)}%)` : "";
	return `${tokens.toLocaleString()} tokens${percent}`;
}

function showStatus(ctx: ExtensionContext, pi: ExtensionAPI, background: BackgroundCompaction, jev: Jev) {
	const settings = readPolicy(pi, ctx);
	const band = pressure(settings);
	const jevLabel = jev.describe(ctx, settings);
	const tokens = (value: number | null | undefined) => formatTokens(value, settings.window);
	const paused = settings.problem ? ` | Extension automation paused: ${settings.problem}` : "";
	ctx.ui.notify([
		`Context: ${tokens(settings.tokens)}${band === "unknown" ? "" : ` (${band})`}`,
		`Notice: ${tokens(settings.notice)} | Warning: ${tokens(settings.warning)} | Native cutoff: ${tokens(settings.hard)}`,
		`Native auto-compaction: ${settings.enabled ? "on" : "off"}${paused}`,
		`Background: ${background.status()} | Last checkpoint: ${lastSource(ctx)} | JEV: ${jevLabel}`,
		...(jev.mode(ctx) === "on" ? [`JEV can send up to ${JEV_EXCERPT_LIMIT} characters from each of the current request, previous request and latest reply to OpenRouter under context pressure. Use /self-compact jev off to disable.`] : []),
	].join("\n"), "info");
}

function compactNow(ctx: ExtensionContext, focus: string) {
	if (!ctx.isIdle() || ctx.hasPendingMessages()) {
		ctx.ui.notify("Pi is busy. Wait until it is idle to compact manually.", "warning");
		return;
	}
	ctx.compact({
		customInstructions: focus || undefined,
		onComplete: () => ctx.ui.notify("Native compaction complete.", "info"),
		onError: () => ctx.ui.notify("Native compaction did not complete.", "warning"),
	});
}

export function registerControls(pi: ExtensionAPI, background: BackgroundCompaction, jev: Jev) {
	pi.registerTool({
		name: SELF_COMPACT_TOOL,
		label: "Self-compact",
		description: "Request a background context checkpoint without pausing work. Pi applies it at a safe turn boundary when ready.",
		promptSnippet: "Request an early context checkpoint with a short handoff when older context is no longer needed verbatim",
		promptGuidelines: ["When using self_compact, give the active goal, completion criteria or constraints, progress and blockers, and the immediate next action. Do not paste secrets, raw output, or entire files."],
		parameters: Type.Object({ handoff: Type.String({ minLength: 1, maxLength: MAX_HANDOFF }) }),
		async execute(toolCallId, params, signal, _onUpdate, ctx) {
			background.queue(toolCallId, params.handoff, signal, ctx, readPolicy(pi, ctx));
			return {
				content: [{ type: "text", text: "Checkpoint requested. Keep working; Pi will apply it at a safe turn boundary when the summary is ready." }],
				details: { queued: true },
			};
		},
	});
	pi.registerCommand("self-compact", {
		description: "Show context pressure, compact while idle, or toggle JEV stopping-point detection",
		getArgumentCompletions: (prefix) => ["status", "now", "jev on", "jev off"].filter((arg) => arg.startsWith(prefix))
			.map((arg) => ({ value: arg, label: arg })),
		async handler(args, ctx) {
			const [command, ...rest] = args.trim().split(/\s+/);
			if (!command || (command === "status" && !rest.length)) return showStatus(ctx, pi, background, jev);
			if (command === "now") return compactNow(ctx, args.trim().slice(command.length).trim());
			if (command === "jev" && rest.length === 1 && (rest[0] === "on" || rest[0] === "off")) {
				return jev.setEnabled(ctx, rest[0] === "on");
			}
			ctx.ui.notify(`Usage: ${USAGE}`, "warning");
		},
	});
}
