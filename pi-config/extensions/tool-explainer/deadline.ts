import { raceAbort } from "../shared/abort.js";
import { ExplanationError } from "./errors.js";

const DEADLINE_MS = 15_000;

export async function withinDeadline<T>(parent: AbortSignal, timeoutMessage: string, run: (signal: AbortSignal) => Promise<T>, timeoutMs = DEADLINE_MS): Promise<T> {
	const timeout = AbortSignal.timeout(timeoutMs);
	const signal = AbortSignal.any([parent, timeout]);
	return raceAbort(signal, run, (): never => {
		if (timeout.aborted && !parent.aborted) throw new ExplanationError(timeoutMessage);
		throw signal.reason;
	});
}
