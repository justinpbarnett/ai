import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { UserMessage } from "@earendil-works/pi-ai";
import { getAgentDir, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { installSummaryBorder } from "./editor.js";
import { earlierExcerpts, formatSummary, previewPrompt, SLOTS, type Labels, type Slot } from "./labels.js";
import { openRouterBlocker, summarize } from "./openrouter.js";
import { RemoteRefresh } from "./refresh.js";

const SETTINGS_FILE = "working-summary.json";
const DEFAULTS = { session: true, prompt: true, remote: false };
const SWITCHES = [...SLOTS, "remote"] as const;
const COMMAND = "working-summary";
const COMMAND_ARGS = ["status", ...SWITCHES.flatMap((name) => [`${name} on`, `${name} off`])];
const REMOTE_NOTICE = "Remote summaries on. On the next eligible prompt, OpenRouter and its model providers may receive up to four 384-character prompt excerpts. Use /working-summary remote off to stop.";

type Settings = typeof DEFAULTS;
type Setting = (typeof SWITCHES)[number];

function isSetting(key: string): key is Setting {
	return SWITCHES.some((setting) => setting === key);
}

function loadSettings(): Settings | undefined {
	try {
		const parsed: unknown = JSON.parse(readFileSync(join(getAgentDir(), SETTINGS_FILE), "utf8"));
		if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
		const settings = { ...DEFAULTS };
		for (const [key, value] of Object.entries(parsed)) {
			if (!isSetting(key) || typeof value !== "boolean") return;
			settings[key] = value;
		}
		return settings;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return { ...DEFAULTS };
	}
}

function parseCommand(args: string) {
	const input = args.trim();
	if (!input || input === "status") return "status";
	const [key, value, extra] = input.split(/\s+/);
	if (key && isSetting(key) && (value === "on" || value === "off") && !extra) return { key, value };
}

function branchPrompts(ctx: ExtensionContext): UserMessage["content"][] {
	return ctx.sessionManager.getBranch().flatMap((entry) =>
		entry.type === "message" && entry.message.role === "user" ? [entry.message.content] : []);
}

class WorkingSummary {
	private settings: Settings = { ...DEFAULTS };
	private configInvalid = false;
	private local: Labels = {};
	private remote: Labels = {};
	private displayedLabels: Labels = {};
	private redrawBorder?: () => void;
	private readonly refresh = new RemoteRefresh();

	start(ctx: ExtensionContext) {
		const loaded = loadSettings();
		this.settings = loaded ?? { ...DEFAULTS };
		this.configInvalid = !loaded;
		this.refresh.reset();
		this.restore(ctx);
		this.redrawBorder = installSummaryBorder(ctx, () => this.displayedLabels);
		if (this.configInvalid) ctx.ui.notify(`Invalid ${SETTINGS_FILE}; use boolean session, prompt, and remote settings. Remote is off.`, "warning");
	}

	restore(ctx: ExtensionContext) {
		this.refresh.cancel();
		this.remote = {};
		const prompts = branchPrompts(ctx);
		const latest = prompts.at(-1);
		this.local = { prompt: latest === undefined ? undefined : previewPrompt(latest).label };
		for (const content of prompts) {
			this.local.session = previewPrompt(content).topicSeed;
			if (this.local.session) break;
		}
		this.render(ctx);
	}

	shutdown() {
		this.refresh.cancel();
		this.displayedLabels = {};
		this.redrawBorder = undefined;
	}

	settle(aborted: boolean) {
		if (aborted) this.refresh.cancel();
		this.redrawBorder?.();
	}

	deliver(ctx: ExtensionContext, content: UserMessage["content"]) {
		this.refresh.cancel();
		const preview = previewPrompt(content);
		this.local.session ??= preview.topicSeed;
		this.local.prompt = preview.label;
		delete this.remote.prompt;
		this.render(ctx);
		if (preview.excerpt) this.queueSummary(ctx, preview.excerpt);
	}

	private queueSummary(ctx: ExtensionContext, latest: string) {
		if (this.refresh.coolingDown || this.remoteDisabled(ctx)) return;
		const { session, prompt } = this.settings;
		this.refresh.start(ctx.signal, (signal) => {
			const evidence = session
				? { latest, earlier: earlierExcerpts(branchPrompts(ctx), latest), previousTopic: this.remote.session }
				: { latest };
			return summarize(ctx.modelRegistry, { session, prompt }, evidence, signal);
		}, (labels) => {
			this.remote = { ...this.remote, ...labels };
			this.render(ctx);
		});
	}

	private displayed(slot: Slot): string | undefined {
		return this.settings[slot] ? this.remote[slot] ?? this.local[slot] : undefined;
	}

	private render(ctx: ExtensionContext) {
		this.displayedLabels = { session: this.displayed("session"), prompt: this.displayed("prompt") };
		const summary = formatSummary(this.displayedLabels);
		ctx.ui.setWorkingMessage(summary ? `Working · ${summary}` : undefined);
		this.redrawBorder?.();
	}

	private remoteDisabled(ctx: ExtensionContext): string | undefined {
		if (this.configInvalid) return "invalid settings";
		if (!this.settings.remote) return "disabled";
		if (!this.settings.session && !this.settings.prompt) return "both slots disabled";
		return openRouterBlocker(ctx);
	}

	private slotStatus(slot: Slot): string {
		if (!this.settings[slot]) return "off";
		if (this.remote[slot]) return "on (remote)";
		return this.local[slot] ? "on (local)" : "on (no label)";
	}

	private status(ctx: ExtensionContext): string {
		const slots = SLOTS.map((slot) => `${slot}: ${this.slotStatus(slot)}`);
		const disabled = this.remoteDisabled(ctx);
		const route = disabled ? `off (${disabled})` : this.refresh.status();
		return `Working summaries: ${slots.join(" · ")} · remote: ${route}`;
	}

	command(ctx: ExtensionContext, args: string) {
		const command = parseCommand(args);
		if (command === "status") return ctx.ui.notify(this.status(ctx), "info");
		if (!command) return ctx.ui.notify(`Use /${COMMAND} status or /${COMMAND} <session|prompt|remote> <on|off>.`, "warning");
		const { key, value } = command;
		const enabled = value === "on";
		if (key === "remote" && enabled && this.configInvalid) {
			return ctx.ui.notify(`Fix ${SETTINGS_FILE} and reload Pi before enabling remote summaries.`, "warning");
		}
		if (this.settings[key] !== enabled) this.setSwitch(ctx, key, enabled);
		ctx.ui.notify(key === "remote" && enabled ? REMOTE_NOTICE : `Working summary ${key} ${value} for this session.`, "info");
	}

	private setSwitch(ctx: ExtensionContext, key: Setting, enabled: boolean) {
		if (key === "remote") {
			this.refresh.reset();
			this.remote = {};
		} else {
			this.refresh.cancel();
		}
		this.settings[key] = enabled;
		this.render(ctx);
	}
}

export default function (pi: ExtensionAPI) {
	const summary = new WorkingSummary();
	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode === "tui") summary.start(ctx);
	});
	pi.on("session_tree", (_event, ctx) => {
		if (ctx.mode === "tui") summary.restore(ctx);
	});
	pi.on("session_shutdown", () => summary.shutdown());
	pi.on("agent_settled", (event) => summary.settle(event.aborted));
	pi.on("message_start", (event, ctx) => {
		if (ctx.mode === "tui" && event.message.role === "user") summary.deliver(ctx, event.message.content);
	});

	pi.registerCommand(COMMAND, {
		description: "Show or toggle Working summaries: status, session on/off, prompt on/off, remote on/off",
		getArgumentCompletions: (prefix) => COMMAND_ARGS.filter((arg) => arg !== prefix && arg.startsWith(prefix))
			.map((arg) => ({ value: arg, label: arg })),
		async handler(args, ctx) {
			if (ctx.mode === "tui") summary.command(ctx, args);
		},
	});
}
