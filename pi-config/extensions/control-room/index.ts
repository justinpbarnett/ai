import { basename } from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@mariozechner/pi-tui";

type FooterState = {
	repoName: string;
	enabled: boolean;
};

const STATUS_ID = "control-room";
const HIDDEN_STATUS_KEYS = new Set([STATUS_ID, "just-commands"]);

function getThinkingToken(level: string): string {
	switch (level) {
		case "minimal":
			return "thinkingMinimal";
		case "low":
			return "thinkingLow";
		case "medium":
			return "thinkingMedium";
		case "high":
			return "thinkingHigh";
		case "xhigh":
			return "thinkingXhigh";
		default:
			return "thinkingOff";
	}
}

function sanitizeInlineText(text: string): string {
	return text.replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim();
}

function formatFooterHint(theme: { fg: (token: string, text: string) => string }, label: string, value: string): string {
	return `${theme.fg("dim", label)} ${value}`;
}

function composeFooterLine(width: number, separator: string, segments: string[]): string {
	if (width <= 0) return "";
	const visibleSeparatorWidth = visibleWidth(separator);
	let line = "";

	for (const segment of segments.filter(Boolean)) {
		const candidate = line ? `${line}${separator}${segment}` : segment;
		if (visibleWidth(candidate) <= width) {
			line = candidate;
			continue;
		}

		if (!line) return truncateToWidth(segment, width);
		const remainingWidth = width - visibleWidth(line) - visibleSeparatorWidth;
		if (remainingWidth > 0) return `${line}${separator}${truncateToWidth(segment, remainingWidth)}`;
		return truncateToWidth(line, width);
	}

	return line;
}

function estimateUsageCost(
	usage: { input?: number; output?: number; cacheRead?: number; cacheWrite?: number; cost?: { total?: number } } | undefined,
	model: { cost?: { input?: number; output?: number; cacheRead?: number; cacheWrite?: number } } | undefined,
): number {
	if (!usage) return 0;
	const explicitCost = usage.cost?.total;
	if (typeof explicitCost === "number" && explicitCost > 0) return explicitCost;
	const rates = model?.cost;
	if (!rates) return 0;
	return (
		((usage.input ?? 0) * (rates.input ?? 0) +
			(usage.output ?? 0) * (rates.output ?? 0) +
			(usage.cacheRead ?? 0) * (rates.cacheRead ?? 0) +
			(usage.cacheWrite ?? 0) * (rates.cacheWrite ?? 0)) /
		1_000_000
	);
}

function formatSessionSpend(amount: number): string {
	if (amount < 0.001) return "$0";
	if (amount < 1) return `$${amount.toFixed(3)}`;
	return `$${amount.toFixed(2)}`;
}

function parseModelRef(modelRef: string | undefined): { provider: string; id: string } | undefined {
	if (!modelRef) return undefined;
	const slash = modelRef.indexOf("/");
	if (slash <= 0 || slash >= modelRef.length - 1) return undefined;
	return {
		provider: modelRef.slice(0, slash),
		id: modelRef.slice(slash + 1),
	};
}

function estimateSubagentSpend(
	details: { results?: Array<{ usage?: any; model?: string }> } | undefined,
	ctx: Parameters<Parameters<ExtensionAPI["on"]>[1]>[1],
): number {
	if (!details?.results || details.results.length === 0) return 0;
	let total = 0;
	for (const result of details.results) {
		const explicitCost = result.usage?.cost;
		if (typeof explicitCost === "number" && explicitCost > 0) {
			total += explicitCost;
			continue;
		}
		const modelRef = parseModelRef(result.model);
		if (!modelRef) continue;
		const model = ctx.modelRegistry.find(modelRef.provider, modelRef.id);
		total += estimateUsageCost(result.usage, model);
	}
	return total;
}

function getSessionSpend(ctx: Parameters<Parameters<ExtensionAPI["on"]>[1]>[1]): number {
	let total = 0;
	for (const entry of ctx.sessionManager.getEntries()) {
		if (entry.type !== "message") continue;
		const message = entry.message as any;
		if (message.role === "assistant") {
			const model = ctx.modelRegistry.find(message.provider, message.model);
			total += estimateUsageCost(message.usage, model);
			continue;
		}
		if (message.role === "toolResult" && message.toolName === "subagent") {
			total += estimateSubagentSpend(message.details, ctx);
		}
	}
	return total;
}

export default function controlRoom(pi: ExtensionAPI) {
	const state: FooterState = {
		repoName: basename(process.cwd()),
		enabled: true,
	};

	async function refreshProjectState(ctx: Parameters<Parameters<ExtensionAPI["on"]>[1]>[1]) {
		try {
			const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], { timeout: 3000 });
			const root = result.stdout.trim();
			state.repoName = root ? basename(root) : basename(ctx.cwd);
		} catch {
			state.repoName = basename(ctx.cwd);
		}
	}

	function mountFooter(ctx: Parameters<Parameters<ExtensionAPI["on"]>[1]>[1]) {
		if (!ctx.hasUI) return;
		ctx.ui.setStatus(STATUS_ID, undefined);
		if (!state.enabled) {
			ctx.ui.setFooter(undefined);
			return;
		}

		ctx.ui.setFooter((tui, _theme, footerData) => {
			const unsubscribe = footerData.onBranchChange(() => tui.requestRender());
			return {
				dispose: unsubscribe,
				invalidate() {},
				render(width: number): string[] {
					const theme = ctx.ui.theme;
					const branch = footerData.getGitBranch() ?? "no git";
					const currentModel = ctx.model;
					const thinkingLevel = pi.getThinkingLevel();
					const modelLabel = currentModel
						? footerData.getAvailableProviderCount() > 1
							? `${theme.fg("muted", currentModel.provider)}/${theme.fg("text", currentModel.id)}`
							: theme.fg("text", currentModel.id)
						: theme.fg("muted", "no-model");

					const sessionSpend = getSessionSpend(ctx);

					const isSubscriptionModel = Boolean(
						currentModel &&
							(currentModel.provider === "claude-bridge" ||
								(ctx.modelRegistry.isUsingOAuth(currentModel) && currentModel.provider !== "anthropic")),
					);
					const spendLabel =
						sessionSpend > 0
							? theme.fg("muted", formatSessionSpend(sessionSpend))
							: isSubscriptionModel
								? theme.fg("muted", "sub")
								: "";
					const thinkingLabel =
						thinkingLevel !== "off" ? formatFooterHint(theme, "think", theme.fg(getThinkingToken(thinkingLevel), thinkingLevel)) : "";
					const externalStatuses = Array.from(footerData.getExtensionStatuses().entries())
						.filter(([key]) => !HIDDEN_STATUS_KEYS.has(key))
						.sort(([a], [b]) => a.localeCompare(b))
						.map(([, text]) => theme.fg("muted", sanitizeInlineText(text)));
					const separator = theme.fg("border", " │ ");
					const footer = composeFooterLine(width, separator, [
						theme.fg("accent", state.repoName),
						branch === "no git" ? theme.fg("dim", branch) : theme.fg("muted", branch),
						modelLabel,
						thinkingLabel,
						spendLabel,
						...externalStatuses,
					]);
					return [footer];
				},
			};
		});
	}

	pi.on("session_start", async (_event, ctx) => {
		await refreshProjectState(ctx);
		mountFooter(ctx);
	});

	pi.on("model_select", async (_event, ctx) => {
		if (!ctx.hasUI || !state.enabled) return;
		mountFooter(ctx);
	});

	pi.registerCommand("control-room", {
		description: "Toggle global schematic footer",
		handler: async (_args, ctx) => {
			state.enabled = !state.enabled;
			mountFooter(ctx);
			if (state.enabled) {
				ctx.ui.notify("Global control room enabled", "info");
			} else {
				ctx.ui.notify("Global control room disabled", "info");
			}
		},
	});
}
