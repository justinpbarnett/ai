import { readFileSync } from "node:fs";
import { join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { DEFAULT_OLLAMA_MODEL, isLocalOllamaModel } from "../shared/ollama.js";
import { OPENROUTER_WRITER_MODEL, isOpenRouterModelId } from "../shared/openrouter.js";
import type { Writer } from "./writer.js";

export const DEFAULT_COUNT = 3;
export const MAX_COUNT = 10;

export function parseCount(value: unknown): number | undefined {
	if (typeof value === "number") return Number.isInteger(value) && value >= 1 && value <= MAX_COUNT ? value : undefined;
	if (typeof value === "string" && /^[1-9]\d?$/.test(value)) return parseCount(Number(value));
}

export type Settings = { count: number; auto: boolean; writer: Writer; warning?: string };
export const defaults: Settings = { count: DEFAULT_COUNT, auto: true, writer: { kind: "ollama", model: DEFAULT_OLLAMA_MODEL } };

function configuredWriter(kind: unknown, ollamaModel?: string, openrouterModel?: string): Writer {
	if (kind === undefined || kind === "ollama") return { kind: "ollama", model: ollamaModel ?? DEFAULT_OLLAMA_MODEL };
	if (kind === "openrouter") return { kind, model: openrouterModel ?? OPENROUTER_WRITER_MODEL };
	if (kind === "off") return { kind };
	throw new Error("Invalid writer");
}

function parseSettings(value: unknown): Settings {
	if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("Invalid settings");
	const { count, auto, writer, ollamaModel, openrouterModel } = value as Record<string, unknown>;
	if (count !== undefined && (typeof count !== "number" || !parseCount(count))) throw new Error("Invalid count");
	if (auto !== undefined && typeof auto !== "boolean") throw new Error("Invalid auto");
	if (ollamaModel !== undefined && !isLocalOllamaModel(ollamaModel)) throw new Error("Invalid Ollama model");
	if (openrouterModel !== undefined && !isOpenRouterModelId(openrouterModel)) throw new Error("Invalid OpenRouter model");
	return { count: count ?? DEFAULT_COUNT, auto: auto ?? true, writer: configuredWriter(writer, ollamaModel, openrouterModel) };
}

export function config(): Settings {
	try {
		return parseSettings(JSON.parse(readFileSync(join(getAgentDir(), "tool-explainer.json"), "utf8")));
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return defaults;
		return { ...defaults, auto: false, writer: { kind: "off" }, warning: `Invalid tool-explainer.json. Check auto (boolean), count (1–${MAX_COUNT}), writer (ollama, openrouter, or off), and model IDs. Automatic explanations are disabled.` };
	}
}
