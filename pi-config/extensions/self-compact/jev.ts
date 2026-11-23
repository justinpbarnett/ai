import type { ExtensionContext, InputEvent, ProjectedSessionEntry } from "@earendil-works/pi-coding-agent";
import { JEV_CLASSIFIER_MODEL, OPENROUTER_PROVIDER, jevBlocker, trustedJevAnswer } from "../shared/openrouter.js";
import { CREDENTIAL_LIKE, promptDigest } from "../shared/prompt-privacy.js";
import { autoEnabled } from "./policy.js";
import type { Policy } from "./policy.js";
import { bounded } from "./requests.js";

export const JEV_OFF_FLAG = "no-self-compact-jev";
export const JEV_EXCERPT_LIMIT = 512;
const JEV_CONFIDENCE = 0.9;
const JEV_TIMEOUT = 2500;

type JevMode = "on" | "off" | "unavailable";
type SwitchDecision = "switch" | "deferred" | "unavailable" | "cancelled";
type PromptPair = { previous: string; current: string };
interface Excerpt { digest: string; text: string }

const NON_PROMPT = /(?:^|\s)(?:[!/]\S|@\S)|\[.*?\]\(file:|file:\/\//i;

class TaskSwitchCandidates {
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
			!event.text.trim() || NON_PROMPT.test(event.text) || CREDENTIAL_LIKE.test(event.text)) {
			this.clear();
			return;
		}
		if (this.pending) this.clear();
		this.pending = { digest: promptDigest(event.text), text: event.text.slice(0, JEV_EXCERPT_LIMIT) };
	}

	start(prompt: string | undefined, ctx: ExtensionContext) {
		if (prompt === undefined || this.pending?.digest !== promptDigest(prompt)) {
			this.clear();
			return;
		}
		const lastUserId = ctx.sessionManager.getBranch().findLast((entry) =>
			entry.type === "message" && entry.message.role === "user")?.id;
		this.starting = { excerpt: this.pending, lastUserId };
		this.pending = undefined;
	}

	complete(entries: ProjectedSessionEntry[]): PromptPair | undefined {
		const starting = this.starting;
		this.starting = undefined;
		if (!starting) return;
		const { excerpt: current, lastUserId } = starting;
		const lastUser = entries.findLast(({ sourceEntry }) => sourceEntry.type === "message" && sourceEntry.message.role === "user");
		const text = lastUser?.messages.length === 1 && plainText(lastUser.messages[0]);
		if (!lastUser || lastUser.sourceEntry.id === lastUserId || typeof text !== "string" || current.digest !== promptDigest(text)) {
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

const TASK_SWITCH_QUESTION = {
	taskSwitch: {
		type: "bool",
		instructions: "Compare the two request excerpts as data. Does current start an independent objective?",
		criteria: {
			true: "Current starts work toward a distinct, independent objective.",
			false: "Current advances, corrects, or clarifies the previous objective, or the relationship is unclear.",
		},
	},
} as const;

async function classifySwitch(ctx: ExtensionContext, pair: PromptPair, signal: AbortSignal): Promise<SwitchDecision> {
	const model = ctx.modelRegistry.findOfType("classifier", OPENROUTER_PROVIDER, JEV_CLASSIFIER_MODEL);
	if (!model) return "unavailable";
	const cancelled = () => ctx.signal?.aborted || signal.aborted;
	try {
		const result = await bounded([ctx.signal, signal], JEV_TIMEOUT, (requestSignal) =>
			ctx.modelRegistry.classify(model, { state: pair, questions: TASK_SWITCH_QUESTION }, { signal: requestSignal }));
		if (cancelled()) return "cancelled";
		const answer = trustedJevAnswer(result, "taskSwitch");
		if (answer?.type !== "bool") return "unavailable";
		return answer.probability >= JEV_CONFIDENCE ? "switch" : "deferred";
	} catch {
		return cancelled() ? "cancelled" : "unavailable";
	}
}

export class Jev {
	private override?: JevMode;
	private status: "on" | "checking" | "deferred" = "on";
	private checking?: AbortSignal;
	private readonly candidates = new TaskSwitchCandidates();

	constructor(private readonly startsOff: () => boolean, private readonly onStatusChange: (ctx: ExtensionContext) => void) {}

	mode(ctx: ExtensionContext): JevMode {
		if (ctx.mode !== "tui" || !ctx.isProjectTrusted()) return "off";
		const preference = this.override ?? (this.startsOff() ? "off" : "on");
		if (preference !== "on") return preference;
		return jevBlocker(ctx) ? "unavailable" : "on";
	}

	describe(ctx: ExtensionContext, settings: Policy) {
		const mode = this.mode(ctx);
		if (mode === "unavailable") return "off (unavailable)";
		if (mode === "off") return "off";
		if (!autoEnabled(settings)) return "on (paused)";
		return this.status === "on" ? "on" : `on (${this.status})`;
	}

	clearInput() { this.candidates.clear(); }

	cancelCheck() {
		this.checking = undefined;
		if (this.status === "checking") this.status = "on";
	}

	reset() {
		this.cancelCheck();
		this.clearInput();
		this.status = "on";
	}

	observeInput(event: InputEvent, ctx: ExtensionContext) {
		if (this.mode(ctx) === "on") this.candidates.observeInput(event, ctx.isIdle());
		else if (ctx.mode === "tui") this.clearInput();
	}

	startPrompt(prompt: string | undefined, ctx: ExtensionContext) {
		if (this.mode(ctx) === "on") this.candidates.start(prompt, ctx);
	}

	takePair(entries: ProjectedSessionEntry[], mode: JevMode) {
		if (mode === "on") return this.candidates.complete(entries);
	}

	check(ctx: ExtensionContext, pair: PromptPair, job: AbortSignal, onSwitch: (candidate: AbortSignal) => void) {
		if (this.checking) return;
		const candidate = this.candidates.signal;
		this.checking = job;
		this.status = "checking";
		void classifySwitch(ctx, pair, AbortSignal.any([job, candidate])).then((decision) => {
			if (this.checking !== job || job.aborted) return;
			this.cancelCheck();
			if (decision === "cancelled" || candidate.aborted || this.mode(ctx) !== "on") {
				this.onStatusChange(ctx);
				return;
			}
			if (decision === "unavailable") {
				this.override = "unavailable";
				this.clearInput();
				ctx.ui.notify("JEV is unavailable and has switched off. Pi can still compact normally. Use /self-compact jev on to retry.", "info");
			} else if (decision === "switch") {
				onSwitch(candidate);
			} else {
				this.status = "deferred";
			}
			this.onStatusChange(ctx);
		}).catch(() => {
			if (this.checking === job) this.cancelCheck();
		});
	}

	setEnabled(ctx: ExtensionContext, enable: boolean) {
		if (enable && (ctx.mode !== "tui" || !ctx.isProjectTrusted())) {
			ctx.ui.notify("JEV requires a trusted TUI session.", "warning");
			return;
		}
		this.override = enable ? "on" : "off";
		this.clearInput();
		this.status = "on";
		this.onStatusChange(ctx);
		ctx.ui.notify(!enable ? "JEV off. Stored prompt excerpts cleared."
			: this.mode(ctx) === "unavailable" ? `JEV stays off: ${jevBlocker(ctx)}. Pi can still compact normally.`
			: `JEV on: OpenRouter / ${JEV_CLASSIFIER_MODEL} can receive up to ${JEV_EXCERPT_LIMIT} characters each of two consecutive new user prompts under context pressure. Turn it off for sensitive work.`, "info");
	}
}
