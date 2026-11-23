import { homedir } from "node:os";
import { basename, isAbsolute, relative, resolve, sep } from "node:path";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { ToolResultMessage } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { CREDENTIAL_LIKE } from "../shared/prompt-privacy.js";
import { PRIVATE_PATH, clip, plain, purposeExcerpt, safeLabel } from "./screening.js";
import { shellLabel } from "./shell-label.js";

const MAX_BATCH_BYTES = 12 * 1024;
const MAX_INSPECT_CHARS = 128 * 1024;

export type Call = { args?: Record<string, unknown>; result: ToolResultMessage };
export type Invocation = { toolName: string; args?: Record<string, unknown> };

function invocationOf(call: Call): Invocation {
	return { toolName: call.result.toolName, args: call.args };
}

export function* callsIn(messages: Iterable<AgentMessage>): Generator<Call> {
	let args = new Map<string, Record<string, unknown>>();
	for (const message of messages) {
		if (message.role === "assistant") {
			args = new Map(message.content.filter((block) => block.type === "toolCall").map((call) => [call.id, call.arguments]));
		} else if (message.role === "toolResult") {
			yield { result: message, args: args.get(message.toolCallId) };
		}
	}
}

export function recentCalls(ctx: ExtensionContext, count: number): Call[] {
	const calls: Call[] = [];
	for (const call of callsIn(ctx.sessionManager.buildSessionProjection().messages)) {
		calls.push(call);
		if (calls.length > count) calls.shift();
	}
	return calls;
}

function stringArg(call: Invocation, key: string): string | undefined {
	const value = call.args?.[key];
	return typeof value === "string" ? value : undefined;
}

function safeName(name: string): string {
	return /^[\w.-]{1,80}$/.test(name) && !CREDENTIAL_LIKE.test(name) ? name : "tool";
}

function workspacePath(path: string, cwd: string): string | undefined {
	if (path.startsWith("~") || /^[a-z]:[/\\]|^\\/i.test(path)) return;
	const target = relative(cwd, resolve(cwd, path.replace(/^@/, "")));
	if (target !== ".." && !target.startsWith("../") && !isAbsolute(target)) return plain(target || ".");
}

function safeTarget(raw: string, cwd: string): string | undefined {
	if (!safeLabel(raw)) return;
	const path = raw.replace(/^@/, "");
	if (!path) return;
	const target = path === "~" ? homedir() : path.startsWith(`~${sep}`) ? resolve(homedir(), path.slice(2)) : resolve(cwd, path);
	if (safeLabel(target)) return target;
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

function bashAction(command: string): Action {
	if (/[\n\r;&|<>`]|\$\(/.test(command)) return "shell";
	if (/^find(?:\s|$)/.test(command) && /\s-(?:delete|exec|execdir|ok|okdir|fprint0?|fprintf|fls)(?:\s|$)/.test(command)) return "shell";
	if (/^rg(?:\s|$)/.test(command) && /\s--pre(?:[=\s]|$)/.test(command)) return "shell";
	const git = /^git(?:\s+-C\s+(?:"[^"]*"|'[^']*'|\S+))?\s+(status|diff|log)(?:\s|$)/.exec(command)?.[1];
	if (git && /\s--(?:ou|out|outp|outpu|output|ext-diff)(?=[=\s]|$)/.test(command)) return "shell";
	if (git === "status") return "gitStatus";
	if (git === "diff") return "gitDiff";
	if (git === "log") return "gitLog";
	if (/^(?:rg|grep|find)(?:\s|$)/.test(command)) return "search";
	if (/^ls(?:\s|$)/.test(command)) return "list";
	if (/^(?:(?:uv\s+run\s+)?pytest|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test|go\s+test|cargo\s+test)(?:\s|$)/.test(command)) return "test";
	if (/^(?:printf|echo)(?:\s|$)/.test(command)) return "print";
	return "shell";
}

function actionFor(call: Invocation): Action {
	switch (call.toolName) {
		case "read": case "edit": case "write": return call.toolName;
		case "grep": case "find": return "search";
		case "ls": return "list";
		case "web_search": return "webSearch";
		case "web_scrape": case "web_crawl": return "webRead";
		case "bash": return bashAction(stringArg(call, "command")?.trim() ?? "");
		case "powershell": return "shell";
		default: return "tool";
	}
}

const activityNames = {
	read: ["file read", "file reads"],
	edit: ["file edit", "file edits"],
	write: ["file write", "file writes"],
	search: ["workspace search", "workspace searches"],
	list: ["directory listing", "directory listings"],
	gitStatus: ["Git status check", "Git status checks"],
	gitDiff: ["Git diff", "Git diffs"],
	gitLog: ["Git history lookup", "Git history lookups"],
	test: ["test command", "test commands"],
	print: ["print command", "print commands"],
	shell: ["shell command", "shell commands"],
	webSearch: ["web search", "web searches"],
	webRead: ["web fetch", "web fetches"],
} satisfies Record<Exclude<Action, "tool">, [string, string]>;

export type ToolActivity = { singular: string; plural: string; target?: string };
export const genericActivity: ToolActivity = { singular: "tool call", plural: "tool calls" };

export function toolActivity(call: Invocation, cwd: string): ToolActivity {
	const action = actionFor(call);
	if (action === "tool") {
		const name = safeName(call.toolName);
		return name === "tool" || !safeLabel(name) ? genericActivity : { singular: `call to ${name}`, plural: `calls to ${name}` };
	}
	const [singular, plural] = activityNames[action];
	const rawPath = isFileAction(action) ? stringArg(call, "path") : undefined;
	const path = rawPath ? safeTarget(rawPath, cwd) : undefined;
	return { singular, plural, target: path ? purposeExcerpt(basename(path)) : undefined };
}

function manualLabel(call: Invocation, action: Action, cwd: string): string | undefined {
	if (action === "tool") return safeName(call.toolName);
	if (action === "shell") {
		const command = stringArg(call, "command");
		return command ? shellLabel(command, safeLabel) : undefined;
	}
	if (!isFileAction(action) && action !== "search" && action !== "list") return;
	const path = stringArg(call, "path");
	const target = path ? safeTarget(path, cwd) : undefined;
	return target && (basename(target) || ".");
}

function manualDescription(call: Call, cwd: string): string {
	const { content, isError } = call.result;
	const invocation = invocationOf(call);
	const action = actionFor(invocation);
	const label = manualLabel(invocation, action, cwd);
	const image = content.some((block) => block.type === "image");
	const text = content.some((block) => block.type === "text" && Boolean(block.text.trim()));
	const suffix = image ? " Returned an image." : !text && !isError ? " No text output." : "";
	const description = action === "shell" ? describeShell(label, isError)
		: `${verbs[action][isError ? 1 : 0]}${label ? ` (${label})` : ""}`;
	return `${description}.${suffix}`;
}

function shellCommand(call: Invocation): string | undefined {
	if (call.toolName !== "bash" && call.toolName !== "powershell") return;
	const command = stringArg(call, "command");
	if (!command || Buffer.byteLength(command, "utf8") > 512) return;
	const screened = plain(command).trim();
	if (screened && !CREDENTIAL_LIKE.test(screened) && !PRIVATE_PATH.test(screened)) return screened;
}

export type PurposeCall = { operation: Action; tool?: string; command?: string; target?: string; search?: string };

export function purposeCall(call: Invocation, cwd: string): PurposeCall {
	const operation = actionFor(call);
	const tool = operation === "tool" ? safeName(call.toolName) : undefined;
	const command = shellCommand(call);
	const rawPath = stringArg(call, "path");
	const path = rawPath && safeTarget(rawPath, cwd);
	const target = path ? purposeExcerpt(workspacePath(path, cwd) ?? basename(path)) : undefined;
	const query = stringArg(call, "query") ?? stringArg(call, "pattern");
	return { operation, tool, command, target, search: query ? purposeExcerpt(query) : undefined };
}

function describeShell(label: string | undefined, failed: boolean): string {
	return label ? `${failed ? "Shell error:" : "Ran"} ${label}` : verbs.shell[failed ? 1 : 0];
}

function isFileAction(action: Action): boolean {
	return action === "read" || action === "edit" || action === "write";
}

export type Evidence = { id: number; tool: string; operation: Action; failed: boolean; target?: string; output?: string; clipped?: true };
export type ManualRow = { id: number; failed: boolean; text: string; evidence?: Evidence; note?: string };

type ScreenedFields = { path: string; command: string; output: string } | { note: string };

function screenEvidence(call: Call): ScreenedFields {
	if (!call.args) return { note: "No matching call arguments in this branch; kept local." };
	if (call.result.content.some((block) => block.type !== "text")) return { note: "Non-text result; kept local." };
	const invocation = invocationOf(call);
	const rawTarget = stringArg(invocation, "path");
	const rawCommand = call.result.toolName === "bash" || call.result.toolName === "powershell" ? stringArg(invocation, "command") : undefined;
	const blocks = call.result.content.flatMap((block) => block.type === "text" ? [block.text] : []);
	const rawFields = [rawTarget ?? "", rawCommand ?? "", ...blocks];
	if (rawFields.reduce((size, field) => size + field.length, 0) > MAX_INSPECT_CHARS) return { note: "Result too large to screen; kept local." };
	const [path, command, ...body] = rawFields.map(plain);
	const output = body.join("\n");
	if ([path, command, output].some((field) => CREDENTIAL_LIKE.test(field) || PRIVATE_PATH.test(field))) {
		return { note: "Possible credential or protected path; kept local." };
	}
	return { path, command, output };
}

function excerpt(call: Call, cwd: string, id: number): Pick<ManualRow, "evidence" | "note"> {
	const fields = screenEvidence(call);
	if ("note" in fields) return fields;
	const { path, command, output } = fields;
	const target = command || (path && workspacePath(path, cwd)) || undefined;
	const evidence: Evidence = {
		id, tool: safeName(call.result.toolName), operation: actionFor(invocationOf(call)), failed: call.result.isError,
		target: target ? clip(target, 320) : undefined,
		output: output ? clip(output, 640) : undefined,
		clipped: (target?.length ?? 0) > 320 || output.length > 640 ? true : undefined,
	};
	return { evidence };
}

export function manualRows(calls: Call[], cwd: string): ManualRow[] {
	const evidence: Evidence[] = [];
	return calls.map((call, index) => {
		const row = { id: index + 1, failed: call.result.isError, text: manualDescription(call, cwd) };
		const details = excerpt(call, cwd, row.id);
		if (details.evidence) {
			if (Buffer.byteLength(JSON.stringify([...evidence, details.evidence]), "utf8") > MAX_BATCH_BYTES) {
				return { ...row, note: "Batch evidence limit; kept local." };
			}
			evidence.push(details.evidence);
		}
		return { ...row, ...details };
	});
}
