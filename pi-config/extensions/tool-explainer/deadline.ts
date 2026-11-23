import { raceAbort } from "../shared/abort.js";
import { ExplanationError } from "./errors.js";

const DEADLINE_MS = 15_000;

export async function withinDeadline<T>(parent: AbortSignal, run: (signal: AbortSignal) => Promise<T>, timeoutMs = DEADLINE_MS): Promise<T> {
	const timeout = AbortSignal.timeout(timeoutMs);
	const signal = AbortSignal.any([parent, timeout]);
	signal.throwIfAborted();
	return raceAbort(signal, run, (): never => {
		if (timeout.aborted && !parent.aborted) throw new ExplanationError("Explanation timed out.");
		throw signal.reason;
	});
}
