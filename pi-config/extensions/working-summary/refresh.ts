import type { Labels } from "./labels.js";
import type { SummaryResult } from "./writer.js";

const DEADLINE_MS = 5_000;
const COOLDOWN_MS = 60_000;

interface Job {
	controller: AbortController;
	timeout: ReturnType<typeof setTimeout>;
}

export class SummaryRefresh {
	private pending?: Job;
	private failure?: string;
	private retryAfter = 0;

	get coolingDown(): boolean {
		return this.retryAfter > Date.now();
	}

	status(): string {
		if (this.pending) return "working";
		if (!this.failure) return "ready";
		return `${this.failure}${this.coolingDown ? ", cooldown" : ""}`;
	}

	cancel(): void {
		if (!this.pending) return;
		const { controller, timeout } = this.pending;
		this.pending = undefined;
		clearTimeout(timeout);
		controller.abort();
	}

	reset(): void {
		this.cancel();
		this.failure = undefined;
		this.retryAfter = 0;
	}

	private recordFailure(reason: string): void {
		this.failure = reason;
		this.retryAfter = Date.now() + COOLDOWN_MS;
	}

	start(
		parentSignal: AbortSignal | undefined,
		request: (signal: AbortSignal) => Promise<SummaryResult>,
		publish: (labels: Labels) => void,
	): void {
		this.cancel();
		const controller = new AbortController();
		const signal = parentSignal ? AbortSignal.any([controller.signal, parentSignal]) : controller.signal;
		const job: Job = {
			controller,
			timeout: setTimeout(() => {
				if (this.pending !== job) return;
				if (!signal.aborted) this.recordFailure("summary timed out");
				this.cancel();
			}, DEADLINE_MS).unref(),
		};
		const isCurrent = () => this.pending === job && !signal.aborted;
		this.pending = job;
		setImmediate(async () => {
			try {
				if (!isCurrent()) return;
				const result = await request(signal);
				if (!isCurrent()) return;
				if (result.failure) this.recordFailure(result.failure);
				else this.failure = result.warning;
				publish(result.labels);
			} catch {
				if (isCurrent()) this.recordFailure("summary request failed");
			} finally {
				clearTimeout(job.timeout);
				if (this.pending === job) this.pending = undefined;
			}
		});
	}
}
