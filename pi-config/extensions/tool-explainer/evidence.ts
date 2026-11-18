import { homedir } from "node:os";
import { basename, isAbsolute, relative, resolve, sep } from "node:path";
import type { ToolCall, ToolResultMessage } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { shellLabel } from "./shell-label.js";

const SECRET = /-----BEGIN [\w ]*(?:PRIVATE KEY|SECRET)-----|\b(?:sk[-_][\w-]{8,}|(?:gh[pousr]_|github_pat_|xox[baprs]-|AKIA|ASIA)[\w-]{8,}|eyJ[\w-]+\.[\w-]+\.[\w-]+)|\bBearer\s+\S|(?:api[-_ ]?key|access[-_ ]?token|token|secret|password|credential)["']?\s*[:=]\s*\S|:\/\/[^\s/@:]+:[^\s/@]+@/i;
const PRIVATE_PATH = /(?:^|[\s/\\'"=@])(?:\.env(?:\.[\w.-]+)?|\.ssh|\.aws|\.gnupg|auth\.json|credentials(?:\.json)?|id_(?:rsa|ed25519))(?:$|[\s/\\'";])/i;
const MAX_BATCH_BYTES = 12 * 1024;
const MAX_INSPECT_CHARS = 128 * 1024;

export type Call = { args?: Record<string, unknown>; result: ToolResultMessage };

export function plain(text: string): string {
	return stripTerminalSequences(text).replace(/[^\S\n]/g, " ").replace(/[\p{Cc}\p{Cf}]/gu, (char) => char === "\n" ? char : "");
}

function clip(text: string, max: number): string {
	if (text.length <= max) return text;
	const half = Math.floor((max - 3) / 2);
	return `${text.slice(0, half)} … ${text.slice(-half)}`;
}

export function recentCalls(ctx: ExtensionContext, count: number): Call[] {
	const calls: Call[] = [];
	let args = new Map<string, Record<string, unknown>>();
	for (const { messages } of ctx.sessionManager.buildSessionProjection().entries) {
		for (const message of messages) {
			if (message.role === "assistant") {
				args = new Map(message.content.filter((block) => block.type === "toolCall").map((call) => [call.id, call.arguments]));
			} else if (message.role === "toolResult") {
				calls.push({ result: message, args: args.get(message.toolCallId) });
				if (calls.length > count) calls.shift();
			}
		}
	}
	return calls;
}

export function pairCalls(results: ToolResultMessage[], calls: ToolCall[]): Call[] {
	const args = new Map(calls.map((call) => [call.id, call.arguments]));
	return results.map((result) => ({ result, args: args.get(result.toolCallId) }));
}

function stringArg(call: Call, key: string): string | undefined {
	const value = call.args?.[key];
	return typeof value === "string" ? value : undefined;
}

function safeName(name: string): string {
	return /^[\w.-]{1,80}$/.test(name) && !SECRET.test(name) ? name : "tool";
}

function workspacePath(path: string, cwd: string): string | undefined {
	if (path.startsWith("~") || /^[a-z]:[/\\]|^\\/i.test(path)) return;
	const target = relative(cwd, resolve(cwd, path.replace(/^@/, "")));
	if (target !== ".." && !target.startsWith("../") && !isAbsolute(target)) return plain(target || ".");
}

function safeLabel(text: string): boolean {
	return !/[\p{Cc}\p{Cf}]/u.test(text) && !SECRET.test(text) && !PRIVATE_PATH.test(text);
}

function pathLabel(raw: string, cwd: string): string | undefined {
	if (!safeLabel(raw)) return;
	const path = raw.replace(/^@/, "");
	if (!path) return;
	const home = homedir();
	const target = path === "~" ? home : path.startsWith(`~${sep}`) ? resolve(home, path.slice(2)) : resolve(cwd, path);
	if (!safeLabel(target)) return;
	const inWorkspace = workspacePath(target, cwd);
	const inHome = inWorkspace ? undefined : workspacePath(target, home);
	const preferred = inWorkspace ?? (inHome === "." ? "~" : inHome ? `~${sep}${inHome}` : target);
	const max = 42;
	if (preferred.length <= max) return preferred;
	const suffix = preferred.slice(-(max - 1));
	const nextSeparator = suffix.indexOf(sep);
	return nextSeparator >= 0 ? `…${suffix.slice(nextSeparator)}` : `…${sep}${suffix.slice(1)}`;
}

const verbs = {
	read: ["Read a file", "Could not read a file"],
	edit: ["Edited a file", "Could not edit a file"],
	write: ["Wrote a file", "Could not write a file"],
	search: ["Searched the workspace", "Workspace search failed"],
	list: ["Listed directory contents", "Could not list directory contents"],
	gitStatus: ["Checked the working tree", "Could not check the working tree"],
	gitDiff: ["Inspected changes", "Could not inspect changes"],
	gitLog: ["Inspected commit history", "Could not inspect commit history"],
	test: ["Ran a test command", "The test command returned an error"],
	print: ["Ran a command to print text", "The print command failed"],
	shell: ["Ran shell code with no visible command name", "Shell code failed"],
	webSearch: ["Searched the web", "Web search failed"],
	webRead: ["Fetched web content", "Could not fetch web content"],
	tool: ["Completed a tool call", "The tool returned an error"],
} as const;

export type Action = keyof typeof verbs;
export type AutoRow = { facts: { action: Action; failed: boolean }; label?: string; text: string };

function actionFor(call: Call): Action {
	switch (call.result.toolName) {
		case "read": case "edit": case "write": return call.result.toolName;
		case "grep": case "find": return "search";
		case "ls": return "list";
		case "web_search": return "webSearch";
		case "web_scrape": case "web_crawl": return "webRead";
		case "bash": {
			const command = stringArg(call, "command")?.trim() ?? "";
			if (!/[\n\r;&|<>`]/.test(command)) {
				const git = /^git(?:\s+-C\s+(?:"[^"]*"|'[^']*'|\S+))?\s+(status|diff|log)(?:\s|$)/.exec(command)?.[1];
				if (git === "status") return "gitStatus";
				if (git === "diff") return "gitDiff";
				if (git === "log") return "gitLog";
				if (/^(?:rg|grep|find)(?:\s|$)/.test(command)) return "search";
				if (/^ls(?:\s|$)/.test(command)) return "list";
				if (/^(?:(?:uv\s+run\s+)?pytest|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test|go\s+test|cargo\s+test)(?:\s|$)/.test(command)) return "test";
				if (/^(?:printf|echo)(?:\s|$)/.test(command)) return "print";
			}
			return "shell";
		}
		case "powershell": return "shell";
		default: return "tool";
	}
}

export function autoRow(call: Call, cwd: string): AutoRow {
	const { content, isError, toolName } = call.result;
	const action = actionFor(call);
	const image = content.some((block) => block.type === "image");
	const text = content.some((block) => block.type === "text" && Boolean(block.text.trim()));
	const path = isFileAction(action) || action === "search" || action === "list"
		? stringArg(call, "path") : undefined;
	const command = action === "shell" ? stringArg(call, "command") : undefined;
	const label = action === "tool" ? safeName(toolName) : command ? shellLabel(command, safeLabel) : path ? pathLabel(path, cwd) : undefined;
	const suffix = image ? " Returned an image." : !text && !isError ? " No text output." : "";
	const description = action === "shell" ? describeShell(label ? [label] : [], Number(!label), isError)
		: `${verbs[action][isError ? 1 : 0]}${label ? ` (${label})` : ""}`;
	return { facts: { action, failed: isError }, label, text: `${description}.${suffix}` };
}

export function shellCommand(call: Call): string | undefined {
	const command = stringArg(call, "command");
	if (!command || Buffer.byteLength(command, "utf8") > 512) return;
	const screened = plain(command).trim();
	if (screened && !SECRET.test(screened) && !PRIVATE_PATH.test(screened)) return screened;
}

function listLabels(labels: string[]) {
	return new Intl.ListFormat("en", { type: "conjunction" }).format(labels);
}

function describeShell(labels: string[], unnamed: number, failed: boolean): string {
	if (!labels.length) {
		if (unnamed > 1) return failed ? `${unnamed} shell calls failed` : `Ran shell code in ${unnamed} calls`;
		return verbs.shell[failed ? 1 : 0];
	}
	const details = listLabels(unnamed ? [...labels, unnamed === 1 ? "one other call" : `${unnamed} other calls`] : labels);
	return failed ? `Shell error: ${details}` : `Ran ${details}`;
}

function isFileAction(action: Action): boolean {
	return action === "read" || action === "edit" || action === "write";
}

type Interpretation = { rows: Set<AutoRow>; text: string };
export type BatchSummary = { full: string; compact: string };

export function summarizeBatch(rows: AutoRow[], interpretation?: Interpretation): BatchSummary {
	return { full: summarizeRows(rows, interpretation, false), compact: summarizeRows(rows, interpretation, true) };
}

function summarizeRows(rows: AutoRow[], interpretation: Interpretation | undefined, shortPaths: boolean): string {
	const pathsByName = new Map<string, Set<string>>();
	if (shortPaths) {
		for (const { facts, label } of rows) {
			if (!label || !isFileAction(facts.action)) continue;
			const name = basename(label);
			const paths = pathsByName.get(name) ?? new Set<string>();
			paths.add(label);
			pathsByName.set(name, paths);
		}
	}
	const parts: string[] = [];
	let group: AutoRow[] = [];
	let interpreted = false;
	function flush() {
		const first = group[0];
		if (!first) return;
		const { action, failed } = first.facts;
		const labels = [...new Set(group.flatMap(({ label }) => label ? [label] : []))];
		const unnamed = group.filter(({ label }) => !label).length;
		const verb = verbs[action][failed ? 1 : 0];
		if (isFileAction(action)) {
			const files = labels.map((path) => pathsByName.get(basename(path))?.size === 1 ? basename(path) : path);
			if (unnamed) files.push(unnamed === 1 && !files.length ? "a file" : `${unnamed}${files.length ? " other" : ""} ${unnamed === 1 ? "file" : "files"}`);
			parts.push(`${verb.replace(/ a file$/, "")} ${listLabels(files)}`);
		} else if (action === "tool" && labels.length) {
			parts.push(`${failed ? "Error from" : "Ran"} ${listLabels(labels)}`);
		} else if (action === "shell") {
			parts.push(describeShell(labels, unnamed, failed));
		} else if (labels.length) {
			parts.push(`${verb} (${listLabels(labels)})`);
		} else {
			parts.push(verb);
		}
		group = [];
	}
	for (const row of rows) {
		if (interpretation?.rows.has(row)) {
			if (!interpreted) {
				flush();
				parts.push(interpretation.text);
				interpreted = true;
			}
			continue;
		}
		if (group.length && (group[0].facts.action !== row.facts.action || group[0].facts.failed !== row.facts.failed)) flush();
		group.push(row);
	}
	flush();
	return parts.join("; ");
}

export type Evidence = { id: number; tool: string; operation: Action; failed: boolean; target?: string; output?: string; clipped?: true };
export type ManualRow = AutoRow & { id: number; evidence?: Evidence; note?: string };

function excerpt(call: Call, cwd: string, id: number): Pick<ManualRow, "evidence" | "note"> {
	if (!call.args) return { note: "No matching call arguments in this branch; kept local." };
	if (call.result.content.some((block) => block.type !== "text")) return { note: "Non-text result; kept local." };
	const rawTarget = stringArg(call, "path");
	const rawCommand = call.result.toolName === "bash" || call.result.toolName === "powershell" ? stringArg(call, "command") : undefined;
	const blocks = call.result.content.flatMap((block) => block.type === "text" ? [block.text] : []);
	const rawFields = [rawTarget ?? "", rawCommand ?? "", ...blocks];
	if (rawFields.reduce((size, field) => size + field.length, 0) > MAX_INSPECT_CHARS) return { note: "Result too large to screen; kept local." };
	const [path, command, ...body] = rawFields.map(plain);
	const output = body.join("\n");
	if ([path, command, output].some((field) => SECRET.test(field) || PRIVATE_PATH.test(field))) {
		return { note: "Possible credential or protected path; kept local." };
	}
	const target = command || (path && workspacePath(path, cwd)) || undefined;
	const evidence: Evidence = {
		id, tool: safeName(call.result.toolName), operation: actionFor(call), failed: call.result.isError,
		target: target ? clip(target, 320) : undefined,
		output: output ? clip(output, 640) : undefined,
		clipped: (target?.length ?? 0) > 320 || output.length > 640 ? true : undefined,
	};
	return { evidence };
}

export function manualRows(calls: Call[], cwd: string): ManualRow[] {
	const evidence: Evidence[] = [];
	return calls.map((call, index) => {
		const id = index + 1;
		const row = excerpt(call, cwd, id);
		if (row.evidence) {
			if (Buffer.byteLength(JSON.stringify([...evidence, row.evidence]), "utf8") > MAX_BATCH_BYTES) {
				return { ...autoRow(call, cwd), id, note: "Batch evidence limit; kept local." };
			}
			evidence.push(row.evidence);
		}
		return { ...autoRow(call, cwd), id, ...row };
	});
}
