export async function bounded<T>(signals: (AbortSignal | undefined)[], ms: number, run: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
	const timeout = new AbortController();
	const signal = AbortSignal.any([timeout.signal, ...signals.filter((input) => input !== undefined)]);
	if (signal.aborted) return;
	const timer = setTimeout(() => timeout.abort(), ms);
	let onAbort: () => void = () => {};
	try {
		const cancelled = new Promise<undefined>((resolve) => {
			onAbort = () => resolve(undefined);
			signal.addEventListener("abort", onAbort, { once: true });
		});
		return await Promise.race([cancelled, run(signal)]);
	} finally {
		clearTimeout(timer);
		signal.removeEventListener("abort", onAbort);
	}
}
