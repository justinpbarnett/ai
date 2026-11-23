import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { CREDENTIAL_LIKE } from "../shared/prompt-privacy.js";

export const PRIVATE_PATH = /(?:^|[\s/\\'"=@])(?:\.env(?:\.[\w.-]+)?|\.ssh|\.aws|\.gnupg|auth\.json|credentials(?:\.json)?|id_(?:rsa|ed25519))(?:$|[\s/\\'";])/i;
const MAX_SUMMARY_CHARS = 2_000;

export function plain(text: string): string {
	return stripTerminalSequences(text).replace(/[^\S\n]/g, " ").replace(/[\p{Cc}\p{Cf}]/gu, (char) => char === "\n" ? char : "");
}

export function clip(text: string, max: number): string {
	if (text.length <= max) return text;
	const half = Math.floor((max - 3) / 2);
	return `${text.slice(0, half)} … ${text.slice(-half)}`;
}

export function safeLabel(text: string): boolean {
	return !/[\p{Cc}\p{Cf}]/u.test(text) && !CREDENTIAL_LIKE.test(text) && !PRIVATE_PATH.test(text);
}

export function purposeExcerpt(value: string): string | undefined {
	if (value.length > 16_384 || /```|~~~|<(?:file\s|skill\b)|(?:^|\s)@\S|\bfile:\/\//i.test(value)) return;
	const text = plain(value).replace(/\s+/gu, " ").trim();
	if (text && safeLabel(text)) return clip(text, 300);
}

export function usableSummary(text: string): string | undefined {
	const summary = plain(text).replace(/`/g, "").replace(/\s+/gu, " ").trim();
	if (/^\p{L}/u.test(summary) && summary.length <= MAX_SUMMARY_CHARS && safeLabel(summary) &&
		!/[\u2028\u2029]|ctrl\+|ignore (?:the|previous|all) instructions/i.test(summary)) return summary;
}
