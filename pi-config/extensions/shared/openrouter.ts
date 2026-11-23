import type { AssistantMessage, ClassifierResult } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

export const OPENROUTER_PROVIDER = "openrouter";
export const JEV_CLASSIFIER_MODEL = "typesafe/jev-1.14";
export const OPENROUTER_WRITER_MODEL = "google/gemini-2.5-flash-lite";
export const JEV_UPSTREAM = "TypeSafe";
export const WRITER_UPSTREAM = "Google";
export const OPENROUTER_SIGN_IN_MESSAGE = "OpenRouter sign-in needed. Use /login or OPENROUTER_API_KEY.";

export const isOpenRouterModelId = (value: unknown): value is string =>
	typeof value === "string" && value.length <= 150 && /^(?:[\w.-]+\/)?[\w.-]+(?::[\w.-]+)?$/.test(value);

export const isPiOffline = () => /^(?:1|true|yes)$/i.test(process.env.PI_OFFLINE ?? "");

export const isOpenRouterConfigured = (registry: ExtensionContext["modelRegistry"]) =>
	registry.getProviderAuthStatus(OPENROUTER_PROVIDER).configured;

export const findJev = (registry: ExtensionContext["modelRegistry"]) =>
	registry.findOfType("classifier", OPENROUTER_PROVIDER, JEV_CLASSIFIER_MODEL);

export function jevBlocker(ctx: ExtensionContext): string | undefined {
	if (!ctx.isProjectTrusted()) return "untrusted project";
	if (isPiOffline()) return "Pi is offline";
	if (!isOpenRouterConfigured(ctx.modelRegistry)) return "OpenRouter sign-in needed";
	if (!findJev(ctx.modelRegistry)) return "OpenRouter JEV model unavailable";
}

export function usableWriter(registry: ExtensionContext["modelRegistry"]) {
	const writer = registry.find(OPENROUTER_PROVIDER, OPENROUTER_WRITER_MODEL);
	return writer?.api === "openai-completions" ? writer : undefined;
}

export function trustedJevAnswer(result: ClassifierResult | undefined, key: string) {
	const answer = result?.stopReason === "stop" ? result.answers[key] : undefined;
	if (answer?.type === "bool" && Number.isFinite(answer.probability) && answer.probability >= 0 && answer.probability <= 1) return answer;
	if (answer?.type === "choice" && Number.isFinite(answer.confidence) && answer.confidence >= 0 && answer.confidence <= 1) return answer;
}

export function trustedJevChoice<Key extends string = string>(result: ClassifierResult | undefined, key: string, criteria: object, minConfidence = 0) {
	const answer = trustedJevAnswer(result, key);
	if (answer?.type === "choice" && answer.confidence >= minConfidence && Object.hasOwn(criteria, answer.choice)) return { choice: answer.choice as Key, confidence: answer.confidence };
}

export const completionText = (message: Pick<AssistantMessage, "content">) =>
	message.content.flatMap((block) => block.type === "text" ? [block.text] : []).join("");

export const jsonSchemaPayload = (name: string, schema: object) => (payload: unknown) => ({
	...(payload as Record<string, unknown>),
	response_format: { type: "json_schema", json_schema: { name, strict: true, schema } },
});
