export async function raceAbort<T, A>(signal: AbortSignal, run: (signal: AbortSignal) => Promise<T>, onAbort: () => A): Promise<T | A> {
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
