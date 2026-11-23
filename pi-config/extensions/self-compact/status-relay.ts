import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

export class StatusRelay {
	private listener: (ctx: ExtensionContext) => void = () => {};

	readonly notify = (ctx: ExtensionContext) => this.listener(ctx);

	listen(listener: (ctx: ExtensionContext) => void) { this.listener = listener; }
}
