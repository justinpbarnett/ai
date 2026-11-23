const OLLAMA_URL = "http://127.0.0.1:11434";
const OLLAMA_TAG = /^(?:[\w.-]+(?::\d+)?\/){0,2}[\w.-]+(?::[\w.-]+)?$/;
export const DEFAULT_OLLAMA_MODEL = "qwen3.5:2b";

export class OllamaWriterError extends Error {}

export function isLocalOllamaModel(value: unknown): value is string {
	return typeof value === "string" && value.length <= 150 && OLLAMA_TAG.test(value) && !/(?:[:-])cloud$/i.test(value);
}

interface ShowReply {
	remote_host?: unknown;
	remote_model?: unknown;
	model_info?: Record<string, unknown>;
}

interface ChatReply {
	done_reason?: unknown;
	message?: { content?: unknown };
}

async function post(path: string, body: object, signal: AbortSignal): Promise<any> {
	const unreachable = new OllamaWriterError("Ollama request failed; check that the model is installed and Ollama is running.");
	const response = await fetch(`${OLLAMA_URL}${path}`, {
		method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal, redirect: "error",
	}).catch((error) => {
		if (signal.aborted) throw error;
		throw unreachable;
	});
	if (!response.ok) throw unreachable;
	try {
		return await response.json();
	} catch (error) {
		if (signal.aborted) throw error;
		throw unreachable;
	}
}

interface WritingRequest {
	model: string;
	systemPrompt: string;
	evidence: object;
	maxTokens: number;
}

export async function writeWithOllama({ model, systemPrompt, evidence, maxTokens }: WritingRequest, signal: AbortSignal): Promise<string> {
	const modelError = "Ollama writer requires a locally installed, non-cloud model.";
	if (!isLocalOllamaModel(model)) throw new OllamaWriterError(modelError);
	const info: ShowReply | null = await post("/api/show", { model }, signal);
	if (info?.remote_host || info?.remote_model || !info?.model_info?.["general.architecture"]) {
		throw new OllamaWriterError(modelError);
	}
	const response: ChatReply | null = await post("/api/chat", {
		model, stream: false, think: false,
		messages: [{ role: "system", content: systemPrompt }, { role: "user", content: JSON.stringify(evidence) }],
		options: { temperature: 0, num_predict: maxTokens, num_ctx: 4096 },
	}, signal);
	if (response?.done_reason !== "stop" || typeof response.message?.content !== "string") {
		throw new OllamaWriterError("Ollama did not finish the summary.");
	}
	return response.message.content;
}
