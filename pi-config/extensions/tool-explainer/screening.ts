import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { hasMention, isSensitiveText, isShareableValue } from "../shared/prompt-privacy.js";

const MAX_SUMMARY_CHARS = 2_000;

export function plain(text: string): string {
	return stripTerminalSequences(text).replace(/[^\S\n]/g, " ").replace(/[\p{Cc}\p{Cf}]/gu, (char) => char === "\n" ? char : "");
}

export function clip(text: string, max: number): string {
	if (text.length <= max) return text;
	const half = Math.floor((max - 3) / 2);
	return `${text.slice(0, half)} … ${text.slice(-half)}`;
}

export function sensitive(text: string): boolean {
	return isSensitiveText(text);
}

export function safeLabel(text: string): boolean {
	return !/[\p{Cc}\p{Cf}]/u.test(text) && !sensitive(text);
}

export function valueExcerpt(value: string): string | undefined {
	if (value.length > 16_384 || !isShareableValue(value)) return;
	const text = plain(value).replace(/\s+/gu, " ").trim();
	if (text && safeLabel(text)) return clip(text, 300);
}

function promptExcerpt(value: string): string | undefined {
	if (!hasMention(value)) return valueExcerpt(value);
}

type MessageContent = string | ReadonlyArray<{ type: string; text?: string }>;

export function textExcerpt(content: MessageContent): string | undefined {
	if (typeof content === "string") return promptExcerpt(content);
	if (content.some((block) => block.type === "image")) return;
	return promptExcerpt(content.flatMap((block) => block.type === "text" && block.text ? [block.text] : []).join("\n"));
}

export function usableSummary(text: string): string | undefined {
	const summary = plain(text).replace(/`/g, "").replace(/\s+/gu, " ").trim();
	if (/^\p{L}/u.test(summary) && summary.length <= MAX_SUMMARY_CHARS && safeLabel(summary) &&
		!/ctrl\+|ignore (?:the|previous|all) instructions/i.test(summary)) return summary;
}
