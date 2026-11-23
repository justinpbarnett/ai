import type { ClassifierResult } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

export const OPENROUTER_PROVIDER = "openrouter";
export const JEV_CLASSIFIER_MODEL = "typesafe/jev-1.14";
export const OPENROUTER_WRITER_MODEL = "google/gemini-2.5-flash-lite";
export const JEV_UPSTREAM = "TypeSafe";
export const WRITER_UPSTREAM = "Google";
export const OPENROUTER_SIGN_IN_MESSAGE = "OpenRouter sign-in needed. Use /login or OPENROUTER_API_KEY.";

export const isPiOffline = () => /^(?:1|true|yes)$/i.test(process.env.PI_OFFLINE ?? "");

export const isOpenRouterConfigured = (registry: ExtensionContext["modelRegistry"]) =>
	registry.getProviderAuthStatus(OPENROUTER_PROVIDER).configured;

export function jevBlocker(ctx: ExtensionContext): string | undefined {
	if (!ctx.isProjectTrusted()) return "untrusted project";
	if (isPiOffline()) return "Pi is offline";
	if (!isOpenRouterConfigured(ctx.modelRegistry)) return "OpenRouter sign-in needed";
	if (!ctx.modelRegistry.findOfType("classifier", OPENROUTER_PROVIDER, JEV_CLASSIFIER_MODEL)) return "OpenRouter JEV model unavailable";
}

export function trustedJevAnswer(result: ClassifierResult | undefined, key: string) {
	const answer = result?.stopReason === "stop" ? result.answers[key] : undefined;
	if (answer?.type === "bool" && Number.isFinite(answer.probability) && answer.probability >= 0 && answer.probability <= 1) return answer;
	if (answer?.type === "choice" && Number.isFinite(answer.confidence) && answer.confidence >= 0 && answer.confidence <= 1) return answer;
}
