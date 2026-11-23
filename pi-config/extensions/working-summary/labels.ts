import type { UserMessage } from "@earendil-works/pi-ai";
import { parseSkillBlock } from "@earendil-works/pi-coding-agent";
import { CREDENTIAL_LIKE } from "../shared/prompt-privacy.js";
import { replaceControlCharacters, stripTerminalSequences, visibleWidth } from "@earendil-works/pi-tui";

export const SLOTS = ["session", "prompt"] as const;
export type Slot = (typeof SLOTS)[number];
export type Labels = Partial<Record<Slot, string>>;

export const SUMMARY_WORD_LIMIT = 6;

const EXCERPT_LENGTH = 384;
const FILE_BLOCK = /<file name="/;
const FILE_END = /<\/file>(?:\r?\n|$)/g;
const IMAGE_NOTE = /^\[Image(?: converted from| omitted:|: original )[^\]\r\n]*\][\t ]*\r?$/gm;
const FILE_REFERENCE = /(?:^|\s)@[^\s]|\bfile:\/\//i;
const CODE_FENCE = /```|~~~/;
const TOPIC_REQUESTS = [
	{ prefix: /^(?:walk (?:me |us )?through|give (?:me|us) a walkthrough of) /i, kind: "walkthrough" },
	{ prefix: /^give (?:me|us) (?:a quick overview|an overview) of /i, kind: "overview" },
];
const REQUEST_LEAD_IN = /^(?:(?:(?:can|could|would) you|please) )+/i;
const RECENT_WORK_ASIDE = / (?:that )?(?:we|you|I) (?:(?:just|recently) )?(?:added|built|created|made|wrote)(?: (?:recently|earlier|yesterday|last week))?$/i;

export interface PromptPreview {
	label?: string;
	topicSeed?: string;
	excerpt?: string;
}

function plainLine(text: string): string {
	return replaceControlCharacters(stripTerminalSequences(text))
		.replace(/[\u202a-\u202e\u2066-\u2069]/gu, "")
		.replace(/\s+/gu, " ")
		.trim();
}

function cleanLabel(value: string): string | undefined {
	const text = plainLine(value);
	if (text && !CREDENTIAL_LIKE.test(text) && visibleWidth(text) > 0) return text;
}

function labelWords(text: string): string[] {
	return text.split(" ", SUMMARY_WORD_LIMIT + 1);
}

export function parseSummaryLabel(value: unknown): string | undefined {
	if (typeof value !== "string") return;
	const text = cleanLabel(value);
	if (text && labelWords(text).length <= SUMMARY_WORD_LIMIT) return text;
}

function localLabel(value: string): string | undefined {
	const text = cleanLabel(value);
	if (!text) return;
	const words = labelWords(text);
	return words.length <= SUMMARY_WORD_LIMIT ? text : `${words.slice(0, SUMMARY_WORD_LIMIT).join(" ")}…`;
}

function localSessionTitle(firstLine: string): string | undefined {
	const request = plainLine(firstLine).replace(REQUEST_LEAD_IN, "");
	for (const { prefix, kind } of TOPIC_REQUESTS) {
		if (!prefix.test(request)) continue;
		const subject = request.replace(prefix, "").split(/[.!?](?= |$)/, 1)[0]!
			.replace(RECENT_WORK_ASIDE, "")
			.replace(/^(?:the|a|an|our|my)(?: |$)/i, "")
			.replace(/`([^`]+)`/g, "$1");
		if (subject && !/^(?:how|why|what|when|where|whether)\b/i.test(subject)) {
			return parseSummaryLabel(`${subject} ${kind}`);
		}
	}
}

function excerpt(text: string): string {
	let end = 0;
	let characters = 0;
	for (const character of text) {
		if (characters++ === EXCERPT_LENGTH) break;
		end += character.length;
	}
	return text.slice(0, end);
}

function afterFileBlocks(text: string): string {
	let end = 0;
	for (const match of text.matchAll(FILE_END)) end = match.index! + match[0].length;
	return end ? text.slice(end).trim() : "";
}

function inspectPrompt(content: UserMessage["content"]) {
	let text = stripTerminalSequences(typeof content === "string" ? content : content.flatMap((block) =>
		block.type === "text" ? [block.text] : []).join("\n")).trim();
	let hasImage = typeof content !== "string" && content.some((block) => block.type === "image");
	const hasFile = FILE_BLOCK.test(text);
	if (hasFile) text = afterFileBlocks(text);
	text = text.replace(IMAGE_NOTE, () => {
		hasImage = true;
		return "";
	}).trim();
	const skill = parseSkillBlock(text);
	const request = skill ? skill.userMessage ?? "" : text;
	const line = plainLine(request);
	const safeLine = CREDENTIAL_LIKE.test(line) ? undefined : line;
	return { request, skillName: skill?.name, safeLine, hasImage, hasFile };
}

function modelExcerpt({ request, safeLine, hasImage, hasFile }: ReturnType<typeof inspectPrompt>): string | undefined {
	if (!safeLine || hasImage || hasFile || CODE_FENCE.test(request) || FILE_REFERENCE.test(request)) return;
	return excerpt(safeLine);
}

export function previewPrompt(content: UserMessage["content"]): PromptPreview {
	const prompt = inspectPrompt(content);
	const { request, skillName, safeLine, hasImage, hasFile } = prompt;
	if (safeLine === undefined) return { label: "Sensitive prompt" };

	const source = skillName !== undefined && !request ? skillName : request.split(CODE_FENCE, 1)[0]!.trim();
	const firstLine = source.split(/[\r\n\u2028\u2029]/u, 1)[0]!;
	const topicSeed = localSessionTitle(firstLine) ?? localLabel(firstLine);
	const label = localLabel(source) ?? (hasImage ? "Image prompt" : hasFile ? "File prompt" : undefined);
	return { label, topicSeed, excerpt: modelExcerpt(prompt) };
}

export function earlierExcerpts(branch: readonly UserMessage["content"][], latest: string): string[] {
	const earlier = new Set<string>();
	const add = (content: UserMessage["content"]) => {
		const text = modelExcerpt(inspectPrompt(content));
		if (!text || text === latest || earlier.has(text)) return false;
		earlier.add(text);
		return true;
	};
	for (const content of branch) {
		add(content);
		if (earlier.size === 2) break;
	}
	for (let index = branch.length - 1; index >= 0; index--) {
		if (add(branch[index]!)) break;
	}
	return [...earlier];
}
