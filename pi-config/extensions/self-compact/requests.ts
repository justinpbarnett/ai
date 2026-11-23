import { raceAbort } from "../shared/abort.js";

export async function bounded<T>(signals: (AbortSignal | undefined)[], ms: number, run: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
	const timeout = new AbortController();
	const signal = AbortSignal.any([timeout.signal, ...signals.filter((input) => input !== undefined)]);
	if (signal.aborted) return;
	const timer = setTimeout(() => timeout.abort(), ms);
	try {
		return await raceAbort(signal, run, () => undefined);
	} finally {
		clearTimeout(timer);
	}
}
