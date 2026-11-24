export async function raceAbort<T, A>(signal: AbortSignal, run: (signal: AbortSignal) => Promise<T>, onAbort: () => A): Promise<T | A> {
	if (signal.aborted) return onAbort();
	let listener: () => void = () => {};
	try {
		const aborted = new Promise<A>((resolve, reject) => {
			listener = () => {
				try {
					resolve(onAbort());
				} catch (error) {
					reject(error);
				}
			};
			signal.addEventListener("abort", listener, { once: true });
		});
		return await Promise.race([aborted, run(signal)]);
	} finally {
		signal.removeEventListener("abort", listener);
	}
}

export async function withTimeout<T, A>(
	signals: (AbortSignal | undefined)[],
	ms: number,
	run: (signal: AbortSignal) => Promise<T>,
	onAbort: (timedOut: boolean, signal: AbortSignal) => A,
): Promise<T | A> {
	const parents = signals.filter((input) => input !== undefined);
	const timeout = new AbortController();
	const signal = AbortSignal.any([timeout.signal, ...parents]);
	const timer = setTimeout(() => timeout.abort(), ms);
	try {
		return await raceAbort(signal, run, () => onAbort(timeout.signal.aborted && !parents.some((parent) => parent.aborted), signal));
	} finally {
		clearTimeout(timer);
	}
}
