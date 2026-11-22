import { createHash } from "node:crypto";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { plain, safeLabel } from "./evidence.js";
import { usableSummary } from "./writer.js";

const ENTRY_TYPE = "tool-explainer.thinking.v1";
const MAX_QUEUE = 12;
const SHORT_THOUGHT_CHARS = 240;
const MARK = "∴";

export type ThinkingRun = { text: string; complete: boolean };
type SavedThought = { key: string; summary: string };
type Branch = ReturnType<ExtensionContext["sessionManager"]["getBranch"]>;

export type ThinkingHost = {
	enabled(): boolean;
	expanded(): boolean;
	refresh(): void;
	write(text: string, signal: AbortSignal): Promise<string> | undefined;
	save(record: SavedThought): void;
};

export function thinkingRuns(message: AssistantMessage): ThinkingRun[] {
	const runs: ThinkingRun[] = [];
	const { content } = message;
	for (let i = 0; i < content.length; i++) {
		if (content[i]!.type !== "thinking") continue;
		const parts: string[] = [];
		for (; i < content.length; i++) {
			const block = content[i]!;
			if (block.type !== "thinking") break;
			const text = block.thinking.trim();
			if (text) parts.push(text);
		}
		if (parts.length) runs.push({ text: parts.join("\n\n"), complete: i < content.length });
	}
	return runs;
}

function keyOf(text: string): string {
	return createHash("sha1").update(text).digest("hex");
}

function shortThought(text: string): string | undefined {
	const line = plain(text).replace(/\s+/gu, " ").trim();
	if (line.length <= SHORT_THOUGHT_CHARS && !text.includes("\n\n")) return line;
}

function lastHeader(text: string): string | undefined {
	const headers = [...text.matchAll(/^\*\*([^*\n]{3,120})\*\*\s*$/gmu)].map(([, header]) => header!.trim());
	const header = headers.at(-1);
	return header && safeLabel(header) ? header : undefined;
}

function escapeMarkdown(text: string): string {
	return text.replace(/[\\`*_{}[\]<>#|~]/g, (char) => `\\${char}`);
}

function readThought(data: unknown): SavedThought | undefined {
	if (!data || typeof data !== "object") return;
	const { key, summary } = data as Partial<SavedThought>;
	if (typeof key !== "string" || !/^[0-9a-f]{40}$/.test(key) || typeof summary !== "string") return;
	const usable = usableSummary(summary);
	if (usable === summary) return { key, summary };
}

export class ThinkingSummaries {
	private readonly summaries = new Map<string, string>();
	private readonly unavailable = new Set<string>();
	private readonly pending = new Set<string>();
	private queue: { key: string; text: string }[] = [];
	private controller = new AbortController();
	private running = false;

	constructor(private readonly host: ThinkingHost) {}

	reset() {
		this.controller.abort();
		this.controller = new AbortController();
		this.queue = [];
		this.pending.clear();
		this.unavailable.clear();
		this.running = false;
	}

	restore(branch: Branch) {
		for (const entry of branch) {
			if (entry.type !== "custom" || entry.customType !== ENTRY_TYPE) continue;
			const record = readThought(entry.data);
			if (record) this.summaries.set(record.key, record.summary);
		}
	}

	observe(message: AssistantMessage, ended: boolean) {
		for (const run of thinkingRuns(message)) {
			if (!run.complete && !ended) continue;
			if (shortThought(run.text)) continue;
			const key = keyOf(run.text);
			if (this.summaries.has(key) || this.pending.has(key) || this.unavailable.has(key)) continue;
			if (this.queue.length >= MAX_QUEUE) {
				this.unavailable.add(key);
				continue;
			}
			this.pending.add(key);
			this.queue.push({ key, text: run.text });
		}
		void this.drain();
	}

	readonly transform = (markdown: string, { isStreaming }: { isStreaming: boolean }): string => {
		if (!this.host.enabled() || this.host.expanded()) return markdown;
		const short = shortThought(markdown);
		if (short) return `${MARK} ${escapeMarkdown(short)}`;
		const key = keyOf(markdown);
		const summary = this.summaries.get(key);
		if (summary) return `${MARK} ${escapeMarkdown(summary)}`;
		if (!this.unavailable.has(key) && (isStreaming || this.pending.has(key))) return `${MARK} Thinking…`;
		const header = lastHeader(markdown);
		return `${MARK} ${header ? escapeMarkdown(header) : "Thought"}`;
	};

	private async drain() {
		if (this.running) return;
		this.running = true;
		const { signal } = this.controller;
		try {
			while (!signal.aborted && this.queue.length) {
				const { key, text } = this.queue.shift()!;
				const writing = this.host.write(text, signal);
				let summary: string | undefined;
				try {
					summary = writing ? await writing : undefined;
				} catch {
					summary = undefined;
				}
				if (signal.aborted) break;
				this.pending.delete(key);
				if (summary) {
					this.summaries.set(key, summary);
					this.host.save({ key, summary });
				} else {
					this.unavailable.add(key);
				}
				this.host.refresh();
			}
		} finally {
			if (!signal.aborted) this.running = false;
		}
	}
}
