import { basename } from "node:path";

const SEPARATOR = /^(?:&&|\|\||[;|\r\n])$/;
const CONTROL_WORD = /^(?:if|then|elif|else|fi|for|while|until|case|esac|do|done|function|select|in|!|\[\[?|\]\]?)$/;
const ASSIGNMENT = /^[a-z_][\w]*=/i;
const SCRIPT_RUNNER = /^(?:python[\d.]*|node|tsx|deno|ruby|perl|bash|zsh|sh|pwsh|powershell)$/i;

function literal(word: string | undefined): string | undefined {
	if (!word) return;
	const value = word.replace(/^(['"])([^'"]*)\1$/, "$2");
	if (/^[\w./~][\w./~+:-]{0,159}$/.test(value)) return value;
}

type SafeArg = (index: number) => string | undefined;

function scriptLabel(program: string, args: string[], boundary: string, safeArg: SafeArg): string {
	if (boundary === "<<" && !args.length) return `${program} (inline script)`;
	if (/^-(?:c|e|Command|EncodedCommand|eval)$/i.test(args[0] ?? "")) return `${program} (inline script)`;
	const index = program === "deno" && args[0] === "run" ? 1 : 0;
	const script = safeArg(index);
	return script && /\.(?:py|[cm]?[jt]sx?|rb|pl|sh|ps1)$/i.test(script) ? `${program} ${basename(script)}` : program;
}

function gitLabel(args: string[]): string {
	let index = 0;
	while (args[index] === "-C" || args[index] === "-c") index += 2;
	const operation = literal(args[index]);
	return /^(?:add|apply|branch|checkout|clone|commit|diff|fetch|grep|log|ls-files|merge|pull|push|rebase|reset|restore|rev-parse|show|status|switch|tag|worktree)$/.test(operation ?? "") ? `git ${operation}` : "git";
}

function githubLabel(args: string[]): string {
	const noun = literal(args[0]);
	const verb = literal(args[1]);
	if (/^(?:pr|issue|run|repo|release|workflow|auth)$/.test(noun ?? "")) {
		return /^(?:list|view|diff|status|checks|watch|create|edit|checkout|merge)$/.test(verb ?? "") ? `gh ${noun} ${verb}` : `gh ${noun}`;
	}
	return noun === "api" || noun === "search" ? `gh ${noun}` : "gh";
}

function taskLabel(program: string, args: string[], safeArg: SafeArg): string {
	const operation = literal(args[0]);
	if (operation === "run") {
		const task = safeArg(1);
		return task && /^[\w][\w.:-]{0,31}$/.test(task) ? `${program} run ${task}` : `${program} run`;
	}
	return /^(?:build|check|fmt|install|lint|ls|ps|test|typecheck|exec|compose)$/.test(operation ?? "") ? `${program} ${operation}` : program;
}

function countLabel(flag: string | undefined, safeArg: SafeArg): string {
	if (!/^-[cmlw]{1,4}$/.test(flag ?? "")) return "wc";
	const file = safeArg(1);
	const name = file ? basename(file) : "";
	return name ? `wc ${flag} ${name}` : `wc ${flag}`;
}

function signature(words: string[], boundary: string, allow: (text: string) => boolean): string | undefined {
	let i = 0;
	while (ASSIGNMENT.test(words[i] ?? "")) i++;
	const executable = literal(words[i]);
	if (!executable || !allow(executable)) return;
	const program = basename(executable);
	if (!program || CONTROL_WORD.test(program) || /^[.~]+$/.test(program)) return;
	const args = words.slice(i + 1);
	const safeArg = (index: number) => {
		const value = literal(args[index]);
		return value && allow(value) ? value : undefined;
	};
	if (SCRIPT_RUNNER.test(program)) return scriptLabel(program, args, boundary, safeArg);
	if (program === "git") return gitLabel(args);
	if (program === "gh") return githubLabel(args);
	if (/^(?:npm|pnpm|yarn|bun|uv|go|cargo|docker|kubectl|make|just)$/.test(program)) return taskLabel(program, args, safeArg);
	if (program === "wc") return countLabel(args[0], safeArg);
	return program;
}

export function shellLabel(command: string, allow: (text: string) => boolean): string | undefined {
	// Read literal command words for display, not shell syntax for execution. Stop before redirects, substitutions and heredoc bodies.
	const tokens = /\\\r?\n|[ \t]+|&&|\|\||<<|[;|\r\n]|[<>&(){}#`]|(?:'[^']*'|"(?:\\[\s\S]|[^"\\])*"|\\[^\r\n]|[^\s\\'"|;<>&(){}#`])+/gy;
	const prefix = command.slice(0, 2048);
	const labels: string[] = [];
	let words: string[] = [];
	let joiner = "";
	const add = (boundary: string) => {
		const label = signature(words, boundary, allow);
		if (label) labels.push(labels.length ? `${joiner}${label}` : label);
		words = [];
		return label;
	};
	for (const [token] of prefix.matchAll(tokens)) {
		if (/^[ \t]+$|^\\\r?\n$/.test(token)) continue;
		if (SEPARATOR.test(token)) {
			if (!words.length) continue;
			if (!add(token) || labels.length === 3) break;
			joiner = /[;\r\n]/.test(token) ? "; " : ` ${token} `;
		} else if (/^(?:<<|[<>&(){}#`])$/.test(token)) {
			add(token);
			break;
		} else {
			words.push(token);
		}
	}
	if (words.length) add("");
	return labels.join("") || undefined;
}
