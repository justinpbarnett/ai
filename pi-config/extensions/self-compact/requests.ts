import { withTimeout } from "../shared/abort.js";

export function bounded<T>(signals: (AbortSignal | undefined)[], ms: number, run: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
	return withTimeout(signals, ms, run, () => undefined);
}
