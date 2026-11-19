import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { UserMessage } from "@earendil-works/pi-ai";
import { getAgentDir, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DEFAULT_OLLAMA_MODEL, isLocalOllamaModel } from "../shared/ollama.js";
import { installSummaryBorder } from "./editor.js";
import { earlierExcerpts, formatSummary, parseSummaryLabel, previewPrompt, SLOTS, type Labels, type Slot } from "./labels.js";
import { summarizeWithOllama } from "./ollama.js";
import { classifyMissionWithJev, jevBlocker, openRouterBlocker, summarizeWithOpenRouter } from "./openrouter.js";
import { SummaryRefresh } from "./refresh.js";

const SETTINGS_FILE = "working-summary.json";
const DEFAULTS = { session: true, prompt: true, ollama: true, jev: false, remote: false, ollamaModel: DEFAULT_OLLAMA_MODEL };
const SWITCHES = [...SLOTS, "ollama", "jev", "remote"] as const;
const WRITER_NAMES = { ollama: "Ollama", openrouter: "OpenRouter" };
const COMMAND = "working-summary";
const MISSION_ENTRY = `${COMMAND}.mission`;
const COMMAND_ARGS = ["status", ...SWITCHES.flatMap((name) => [`${name} on`, `${name} off`])];
const REMOTE_NOTICE = "Remote summaries on. On the next eligible prompt, OpenRouter and its model providers may receive up to four 384-character prompt excerpts. Use /working-summary remote off to stop.";
const JEV_NOTICE = "JEV mission checks on. OpenRouter and TypeSafe can receive the mission title and up to two 384-character prompt excerpts. This does not change the label writer. Use /working-summary jev off to stop.";

type Settings = typeof DEFAULTS;
type Setting = (typeof SWITCHES)[number];
type Writer = keyof typeof WRITER_NAMES;
type PromptExcerpt = { text: string; timestamp: number };
type MissionCheckpoint = { title: string; requestAt: number };
type Branch = ReturnType<ExtensionContext["sessionManager"]["getBranch"]>;

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

function branchPrompts(branch: Branch): UserMessage[] {
	return branch.flatMap((entry) => entry.type === "message" && entry.message.role === "user" ? [entry.message] : []);
}

function savedMission(branch: Branch): MissionCheckpoint | undefined {
	for (let index = branch.length - 1; index >= 0; index--) {
		const entry = branch[index];
		if (entry?.type !== "custom" || entry.customType !== MISSION_ENTRY || !entry.data || typeof entry.data !== "object") continue;
		const { title, requestAt } = entry.data as Partial<MissionCheckpoint>;
		const label = parseSummaryLabel(title);
		if (label && typeof requestAt === "number" && Number.isFinite(requestAt)) return { title: label, requestAt };
	}
}

function excerptAt(message: UserMessage | undefined, text: string | undefined): PromptExcerpt | undefined {
	if (message && text) return { text, timestamp: message.timestamp };
}

class WorkingSummary {
	private settings: Settings = { ...DEFAULTS };
	private configInvalid = false;
	private fallback: Labels = {};
	private generated: Labels = {};
	private openingExcerpt?: PromptExcerpt;
	private missionExcerpt?: PromptExcerpt;
	private pendingMission?: MissionCheckpoint;
	private displayedLabels: Labels = {};
	private redrawBorder?: () => void;
	private readonly refresh = new SummaryRefresh();

	constructor(private readonly pi: ExtensionAPI) {}

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
		const branch = ctx.sessionManager.getBranch();
		const prompts = branchPrompts(branch);
		const latest = prompts.at(-1);
		const preview = latest && previewPrompt(latest.content);
		this.fallback = { prompt: preview?.label };
		this.openingExcerpt = this.missionExcerpt = undefined;
		this.pendingMission = undefined;
		for (const message of prompts) {
			const { topicSeed, excerpt } = previewPrompt(message.content);
			this.fallback.session ??= topicSeed;
			this.openingExcerpt ??= excerptAt(message, excerpt);
			if (this.fallback.session && this.openingExcerpt) break;
		}
		const local = this.writer() === "ollama";
		const saved = local ? savedMission(branch) : undefined;
		if (saved) {
			this.generated.session = saved.title;
			const source = prompts.findLast((message) => message.timestamp === saved.requestAt);
			if (source) this.missionExcerpt = excerptAt(source, previewPrompt(source.content).excerpt);
		}
		this.render(ctx);
		if (local) this.queueSummary(ctx, excerptAt(latest, preview?.excerpt), false);
	}

	shutdown() {
		this.refresh.cancel();
		this.displayedLabels = {};
		this.redrawBorder = undefined;
	}

	settle(aborted: boolean) {
		if (aborted) this.refresh.cancel();
		this.persistMission();
		this.redrawBorder?.();
	}

	private persistMission() {
		if (!this.pendingMission) return;
		this.pi.appendEntry(MISSION_ENTRY, this.pendingMission);
		this.pendingMission = undefined;
	}

	deliver(ctx: ExtensionContext, message: UserMessage) {
		this.refresh.cancel();
		const preview = previewPrompt(message.content);
		const latest = excerptAt(message, preview.excerpt);
		this.fallback.session ??= preview.topicSeed;
		this.openingExcerpt ??= latest;
		this.fallback.prompt = preview.label;
		delete this.generated.prompt;
		this.render(ctx);
		this.queueSummary(ctx, latest, true);
	}

	private queueSummary(ctx: ExtensionContext, latest: PromptExcerpt | undefined, checkMission: boolean) {
		const writer = this.writer();
		if (!writer || this.refresh.coolingDown || this.writerBlocker(ctx, writer)) return;
		const publish = (labels: Labels) => {
			this.generated = { ...this.generated, ...labels };
			this.render(ctx);
		};
		if (writer === "ollama") {
			this.queueLocal(ctx, latest, checkMission, publish);
		} else if (latest) {
			const fields = SLOTS.filter((slot) => this.settings[slot]);
			this.refresh.start(ctx.signal, (signal) => {
				const evidence = fields.includes("session")
					? { latest: latest.text, earlier: earlierExcerpts(branchPrompts(ctx.sessionManager.getBranch()).map((message) => message.content), latest.text), previousTopic: this.generated.session }
					: { latest: latest.text };
				return summarizeWithOpenRouter(ctx.modelRegistry, fields, evidence, signal);
			}, publish);
		}
	}

	private queueLocal(ctx: ExtensionContext, latest: PromptExcerpt | undefined, checkMission: boolean, publish: (labels: Labels) => void) {
		const title = this.settings.session ? this.generated.session : undefined;
		const mission = checkMission && title && latest && latest.timestamp !== this.missionExcerpt?.timestamp
			? { title, request: this.missionExcerpt?.text } : undefined;
		const opening = this.settings.session && !title ? this.openingExcerpt : undefined;
		const source = mission ? latest : opening;
		const includePrompt = this.settings.prompt && !!latest;
		const fields = SLOTS.filter((slot) => slot === "session" ? !!source : includePrompt);
		if (!fields.length) return;
		const { ollamaModel, jev } = this.settings;
		const useJev = jev && !!mission && !jevBlocker(ctx);
		this.refresh.start(ctx.signal, async (signal) => {
			if (useJev && mission && latest) {
				const decision = await classifyMissionWithJev(ctx.modelRegistry, { mission, latest: latest.text }, signal);
				if (decision === "switch") {
					return summarizeWithOllama(ollamaModel, fields, { openingRequest: latest.text, latest: includePrompt ? latest.text : undefined }, signal);
				}
				if (decision === "keep") {
					return includePrompt ? summarizeWithOllama(ollamaModel, ["prompt"], { latest: latest.text }, signal) : { labels: {} };
				}
			}
			return summarizeWithOllama(ollamaModel, fields, { openingRequest: opening?.text, latest: includePrompt || mission ? latest?.text : undefined, mission }, signal);
		}, (labels) => {
			if (labels.session && source) {
				this.missionExcerpt = source;
				this.pendingMission = { title: labels.session, requestAt: source.timestamp };
				if (ctx.isIdle()) this.persistMission();
			}
			publish(labels);
		});
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
		const jev = writer === "ollama" && this.settings.jev && this.settings.session;
		const blocker = jev ? jevBlocker(ctx) : undefined;
		const mission = writer === "ollama" && this.settings.session ? ` · mission: ${jev && !blocker ? "JEV via OpenRouter" : "Ollama"}${blocker ? ` (${blocker})` : ""}` : "";
		return `Working summaries: ${slots.join(" · ")} · writer: ${route}${mission}`;
	}

	command(ctx: ExtensionContext, args: string) {
		const command = parseCommand(args);
		if (command === "status") return ctx.ui.notify(this.status(ctx), "info");
		if (!command) return ctx.ui.notify(`Use /${COMMAND} status or /${COMMAND} <${SWITCHES.join("|")}> <on|off>.`, "warning");
		const { key, value } = command;
		const enabled = value === "on";
		if ((key === "remote" || key === "ollama" || key === "jev") && enabled && this.configInvalid) {
			return ctx.ui.notify(`Fix ${SETTINGS_FILE} and reload Pi before enabling model summaries.`, "warning");
		}
		if (this.settings[key] !== enabled) this.setSwitch(ctx, key, enabled);
		ctx.ui.notify(key === "remote" && enabled ? REMOTE_NOTICE : key === "jev" && enabled ? JEV_NOTICE : `Working summary ${key} ${value} for this session.`, "info");
	}

	private setSwitch(ctx: ExtensionContext, key: Setting, enabled: boolean) {
		const previousWriter = this.writer();
		this.settings[key] = enabled;
		const writer = this.writer();
		if (previousWriter !== writer) {
			this.refresh.reset();
			if (writer === "ollama") return this.restore(ctx);
			this.generated = {};
			this.missionExcerpt = undefined;
			this.pendingMission = undefined;
		} else if (key === "session" || key === "prompt" || key === "jev") {
			this.refresh.cancel();
		}
		this.render(ctx);
	}
}

export default function (pi: ExtensionAPI) {
	const summary = new WorkingSummary(pi);
	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode === "tui") summary.start(ctx);
	});
	pi.on("session_tree", (_event, ctx) => {
		if (ctx.mode === "tui") summary.restore(ctx);
	});
	pi.on("session_shutdown", () => summary.shutdown());
	pi.on("agent_settled", (event) => summary.settle(event.aborted));
	pi.on("message_start", (event, ctx) => {
		if (ctx.mode === "tui" && event.message.role === "user") summary.deliver(ctx, event.message);
	});

	pi.registerCommand(COMMAND, {
		description: "Show or toggle Working summaries: status, session/prompt/ollama/jev/remote on or off",
		getArgumentCompletions: (prefix) => COMMAND_ARGS.filter((arg) => arg !== prefix && arg.startsWith(prefix))
			.map((arg) => ({ value: arg, label: arg })),
		async handler(args, ctx) {
			if (ctx.mode === "tui") summary.command(ctx, args);
		},
	});
}
