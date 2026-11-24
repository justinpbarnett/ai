import { homedir } from "node:os";
import { basename, isAbsolute, relative, resolve, sep } from "node:path";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { ToolResultMessage } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { CREDENTIAL_LIKE } from "../shared/prompt-privacy.js";
import { clip, plain, valueExcerpt, safeLabel, sensitive } from "./screening.js";
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
	if (target.split(sep)[0] !== ".." && !isAbsolute(target)) return plain(target || ".");
}

function safeTarget(raw: string, cwd: string): string | undefined {
	if (!safeLabel(raw)) return;
	const path = raw.replace(/^@/, "");
	if (!path) return;
	const target = path === "~" ? homedir() : path.startsWith(`~${sep}`) ? resolve(homedir(), path.slice(2)) : resolve(cwd, path);
	if (safeLabel(target)) return target;
}

const actions = {
	read: { name: "file read", done: "Read a file", failed: "Could not read a file" },
	edit: { name: "file edit", done: "Edited a file", failed: "Could not edit a file" },
	write: { name: "file write", done: "Wrote a file", failed: "Could not write a file" },
	search: { name: "workspace search", done: "Searched the workspace", failed: "Workspace search failed" },
	list: { name: "directory listing", done: "Listed directory contents", failed: "Could not list directory contents" },
	gitStatus: { name: "Git status check", done: "Checked the working tree", failed: "Could not check the working tree" },
	gitDiff: { name: "Git diff", done: "Inspected changes", failed: "Could not inspect changes" },
	gitLog: { name: "Git history lookup", done: "Inspected commit history", failed: "Could not inspect commit history" },
	test: { name: "test command", done: "Ran a test command", failed: "The test command returned an error" },
	print: { name: "print command", done: "Ran a command to print text", failed: "The print command failed" },
	shell: { name: "shell command", done: "Ran shell code with no visible command name", failed: "Shell code failed" },
	webSearch: { name: "web search", done: "Searched the web", failed: "Web search failed" },
	webRead: { name: "web fetch", done: "Fetched web content", failed: "Could not fetch web content" },
	tool: { name: "tool call", done: "Completed a tool call", failed: "The tool returned an error" },
} as const;

export type Action = keyof typeof actions;

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

export type ToolActivity = { name: string; target?: string };
export const genericActivity: ToolActivity = { name: actions.tool.name };

export function toolActivity(call: Invocation, cwd: string): ToolActivity {
	const action = actionFor(call);
	if (action === "tool") {
		const name = safeName(call.toolName);
		return name === "tool" || !safeLabel(name) ? genericActivity : { name: `call to ${name}` };
	}
	const rawPath = isFileAction(action) ? stringArg(call, "path") : undefined;
	const path = rawPath ? safeTarget(rawPath, cwd) : undefined;
	return { name: actions[action].name, target: path ? valueExcerpt(basename(path)) : undefined };
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
		: `${actions[action][isError ? "failed" : "done"]}${label ? ` (${label})` : ""}`;
	return `${description}.${suffix}`;
}

function shellCommand(call: Invocation): string | undefined {
	if (call.toolName !== "bash" && call.toolName !== "powershell") return;
	const command = stringArg(call, "command");
	if (!command || Buffer.byteLength(command, "utf8") > 512) return;
	const screened = plain(command).trim();
	if (screened && !sensitive(screened)) return screened;
}

export type PurposeCall = { operation: Action; tool?: string; command?: string; target?: string; search?: string };

export function purposeCall(call: Invocation, cwd: string): PurposeCall {
	const operation = actionFor(call);
	const tool = operation === "tool" ? safeName(call.toolName) : undefined;
	const command = shellCommand(call);
	const rawPath = stringArg(call, "path");
	const path = rawPath && safeTarget(rawPath, cwd);
	const target = path ? valueExcerpt(workspacePath(path, cwd) ?? basename(path)) : undefined;
	const query = stringArg(call, "query") ?? stringArg(call, "pattern");
	return { operation, tool, command, target, search: query ? valueExcerpt(query) : undefined };
}

function describeShell(label: string | undefined, failed: boolean): string {
	return label ? `${failed ? "Shell error:" : "Ran"} ${label}` : actions.shell[failed ? "failed" : "done"];
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
	if ([path, command, output].some(sensitive)) {
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
