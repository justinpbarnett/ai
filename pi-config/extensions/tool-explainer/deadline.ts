import { withTimeout } from "../shared/abort.js";
import { ExplanationError } from "./errors.js";

const DEADLINE_MS = 15_000;

export async function withinDeadline<T>(parent: AbortSignal, timeoutMessage: string, run: (signal: AbortSignal) => Promise<T>, timeoutMs = DEADLINE_MS): Promise<T> {
	return withTimeout([parent], timeoutMs, run, (timedOut, signal): never => {
		if (timedOut) throw new ExplanationError(timeoutMessage);
		throw signal.reason;
	});
}
