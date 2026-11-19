import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { UserMessage } from "@earendil-works/pi-ai";
import { getAgentDir, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DEFAULT_OLLAMA_MODEL, isLocalOllamaModel } from "../shared/ollama.js";
import { installSummaryBorder } from "./editor.js";
import { earlierExcerpts, formatSummary, previewPrompt, SLOTS, type Labels, type Slot } from "./labels.js";
import { summarizeWithOllama } from "./ollama.js";
import { openRouterBlocker, summarizeWithOpenRouter } from "./openrouter.js";
import { SummaryRefresh } from "./refresh.js";

const SETTINGS_FILE = "working-summary.json";
const DEFAULTS = { session: true, prompt: true, ollama: true, remote: false, ollamaModel: DEFAULT_OLLAMA_MODEL };
const SWITCHES = [...SLOTS, "ollama", "remote"] as const;
const WRITER_NAMES = { ollama: "Ollama", openrouter: "OpenRouter" };
const COMMAND = "working-summary";
const COMMAND_ARGS = ["status", ...SWITCHES.flatMap((name) => [`${name} on`, `${name} off`])];
const REMOTE_NOTICE = "Remote summaries on. On the next eligible prompt, OpenRouter and its model providers may receive up to four 384-character prompt excerpts. Use /working-summary remote off to stop.";

type Settings = typeof DEFAULTS;
type Setting = (typeof SWITCHES)[number];
type Writer = keyof typeof WRITER_NAMES;

function isSetting(key: string): key is Setting {
	return SWITCHES.some((setting) => setting === key);
}

function loadSettings(): Settings | undefined {
	try {
		const parsed: unknown = JSON.parse(readFileSync(join(getAgentDir(), SETTINGS_FILE), "utf8"));
		if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
		const settings = { ...DEFAULTS };
		for (const [key, value] of Object.entries(parsed)) {
			if (key === "ollamaModel" && isLocalOllamaModel(value)) settings.ollamaModel = value;
			else if (isSetting(key) && typeof value === "boolean") settings[key] = value;
			else return;
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
	private fallback: Labels = {};
	private generated: Labels = {};
	private openingExcerpt?: string;
	private displayedLabels: Labels = {};
	private redrawBorder?: () => void;
	private readonly refresh = new SummaryRefresh();

	start(ctx: ExtensionContext) {
		const loaded = loadSettings();
		this.settings = loaded ?? { ...DEFAULTS };
		this.configInvalid = !loaded;
		this.refresh.reset();
		this.redrawBorder = installSummaryBorder(ctx, () => this.displayedLabels);
		this.restore(ctx);
		if (this.configInvalid) ctx.ui.notify(`Invalid ${SETTINGS_FILE}; check the summary switches and ollamaModel. Model summaries are off.`, "warning");
	}

	restore(ctx: ExtensionContext) {
		this.refresh.cancel();
		this.generated = {};
		const prompts = branchPrompts(ctx);
		const latest = prompts.at(-1);
		const preview = latest === undefined ? undefined : previewPrompt(latest);
		this.fallback = { prompt: preview?.label };
		this.openingExcerpt = undefined;
		for (const content of prompts) {
			const { topicSeed, excerpt } = previewPrompt(content);
			this.fallback.session ??= topicSeed;
			this.openingExcerpt ??= excerpt;
			if (this.fallback.session && this.openingExcerpt) break;
		}
		this.render(ctx);
		if (this.writer() === "ollama") this.queueSummary(ctx, preview?.excerpt);
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
		this.fallback.session ??= preview.topicSeed;
		this.openingExcerpt ??= preview.excerpt;
		this.fallback.prompt = preview.label;
		delete this.generated.prompt;
		this.render(ctx);
		this.queueSummary(ctx, preview.excerpt);
	}

	private queueSummary(ctx: ExtensionContext, latest: string | undefined) {
		const writer = this.writer();
		if (!writer || this.refresh.coolingDown || this.writerBlocker(ctx, writer)) return;
		const publish = (labels: Labels) => {
			this.generated = { ...this.generated, ...labels };
			this.render(ctx);
		};
		if (writer === "ollama") {
			const openingRequest = this.settings.session && !this.generated.session ? this.openingExcerpt : undefined;
			const latestRequest = this.settings.prompt ? latest : undefined;
			const fields = SLOTS.filter((slot) => slot === "session" ? openingRequest : latestRequest);
			if (!fields.length) return;
			const { ollamaModel } = this.settings;
			this.refresh.start(ctx.signal, (signal) => summarizeWithOllama(ollamaModel, fields, { openingRequest, latest: latestRequest }, signal), publish);
		} else if (latest) {
			const fields = SLOTS.filter((slot) => this.settings[slot]);
			this.refresh.start(ctx.signal, (signal) => {
				const evidence = fields.includes("session")
					? { latest, earlier: earlierExcerpts(branchPrompts(ctx), latest), previousTopic: this.generated.session }
					: { latest };
				return summarizeWithOpenRouter(ctx.modelRegistry, fields, evidence, signal);
			}, publish);
		}
	}

	private displayed(slot: Slot): string | undefined {
		return this.settings[slot] ? this.generated[slot] ?? this.fallback[slot] : undefined;
	}

	private render(ctx: ExtensionContext) {
		this.displayedLabels = { session: this.displayed("session"), prompt: this.displayed("prompt") };
		const summary = formatSummary(this.displayedLabels);
		ctx.ui.setWorkingMessage(summary ? `Working · ${summary}` : undefined);
		this.redrawBorder?.();
	}

	private writer(): Writer | undefined {
		if (!this.configInvalid) {
			if (this.settings.remote) return "openrouter";
			if (this.settings.ollama) return "ollama";
		}
	}

	private writerBlocker(ctx: ExtensionContext, writer: Writer): string | undefined {
		if (!this.settings.session && !this.settings.prompt) return "both slots disabled";
		if (writer === "openrouter") return openRouterBlocker(ctx);
		if (!ctx.isProjectTrusted()) return "untrusted project";
	}

	private slotStatus(slot: Slot, writer: Writer | undefined): string {
		if (!this.settings[slot]) return "off";
		if (writer && this.generated[slot]) return `on (${WRITER_NAMES[writer]})`;
		return this.fallback[slot] ? "on (fallback)" : "on (no label)";
	}

	private status(ctx: ExtensionContext): string {
		const writer = this.writer();
		const slots = SLOTS.map((slot) => `${slot}: ${this.slotStatus(slot, writer)}`);
		const model = writer === "ollama" ? `/${this.settings.ollamaModel}` : "";
		const route = writer ? `${WRITER_NAMES[writer]}${model} (${this.writerBlocker(ctx, writer) ?? this.refresh.status()})`
			: `off (${this.configInvalid ? "invalid settings" : "disabled"})`;
		return `Working summaries: ${slots.join(" · ")} · writer: ${route}`;
	}

	command(ctx: ExtensionContext, args: string) {
		const command = parseCommand(args);
		if (command === "status") return ctx.ui.notify(this.status(ctx), "info");
		if (!command) return ctx.ui.notify(`Use /${COMMAND} status or /${COMMAND} <session|prompt|ollama|remote> <on|off>.`, "warning");
		const { key, value } = command;
		const enabled = value === "on";
		if ((key === "remote" || key === "ollama") && enabled && this.configInvalid) {
			return ctx.ui.notify(`Fix ${SETTINGS_FILE} and reload Pi before enabling model summaries.`, "warning");
		}
		if (this.settings[key] !== enabled) this.setSwitch(ctx, key, enabled);
		ctx.ui.notify(key === "remote" && enabled ? REMOTE_NOTICE : `Working summary ${key} ${value} for this session.`, "info");
	}

	private setSwitch(ctx: ExtensionContext, key: Setting, enabled: boolean) {
		const previousWriter = this.writer();
		this.settings[key] = enabled;
		if (previousWriter !== this.writer()) {
			this.refresh.reset();
			this.generated = {};
		} else if (key === "session" || key === "prompt") {
			this.refresh.cancel();
		}
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
		description: "Show or toggle Working summaries: status, session on/off, prompt on/off, ollama on/off, remote on/off",
		getArgumentCompletions: (prefix) => COMMAND_ARGS.filter((arg) => arg !== prefix && arg.startsWith(prefix))
			.map((arg) => ({ value: arg, label: arg })),
		async handler(args, ctx) {
			if (ctx.mode === "tui") summary.command(ctx, args);
		},
	});
}
