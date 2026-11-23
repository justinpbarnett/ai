import type { ExtensionAPI, TurnEndEvent } from "@earendil-works/pi-coding-agent";
import { BackgroundCompaction, SELF_COMPACT_TOOL } from "./background.js";
import { CHECKPOINT_TYPE, currentCheckpoint } from "./checkpoint.js";
import { registerControls } from "./controls.js";
import { registerProactiveFooter } from "./footer.js";
import { Jev, JEV_OFF_FLAG } from "./jev.js";
import { NOTICE_FLAG, PressureCycle, WARN_FLAG, pressure, readPolicy } from "./policy.js";
import { StatusRelay } from "./status-relay.js";

const NOTICE = "Context notice: Pi can prepare a background checkpoint. Call self_compact to request an early swap with a handoff.";
const WARNING = "Context warning: Pi can apply a ready background checkpoint at a safe boundary. Native compaction remains the backstop.";

function note(event: TurnEndEvent, content: string) {
	return { entries: [...event.entries, { type: "custom_message" as const, customType: CHECKPOINT_TYPE, content, display: false }] };
}

function continuesNaturally(event: TurnEndEvent) {
	return event.continue || event.toolResults.length > 0 || event.context.pendingMessages.length > 0;
}

export default function (pi: ExtensionAPI) {
	const status = new StatusRelay();
	const cycle = new PressureCycle();
	const jev = new Jev(() => pi.getFlag(JEV_OFF_FLAG) === true, status.notify);
	const background = new BackgroundCompaction(jev, cycle, status.notify);

	function reset() {
		background.reset();
		jev.reset();
		cycle.reset();
	}

	pi.registerFlag(NOTICE_FLAG, { type: "string", description: "Self-compaction notice threshold in tokens (6000, 6k) or percent (60%)" });
	pi.registerFlag(WARN_FLAG, { type: "string", description: "Self-compaction warning threshold in tokens (10000, 10k) or percent (80%)" });
	pi.registerFlag(JEV_OFF_FLAG, { type: "boolean", description: "Start Pi with JEV task-switch detection off" });

	pi.on("session_start", reset);
	pi.on("session_shutdown", reset);
	pi.on("session_tree", (_, ctx) => { reset(); status.notify(ctx); });
	pi.on("model_select", (_, ctx) => { reset(); status.notify(ctx); });
	pi.on("session_before_compact", (_, ctx) => { background.discard(); status.notify(ctx); });
	pi.on("agent_settled", (event) => background.settle(event.aborted));
	pi.on("input", (event, ctx) => jev.observeInput(event, ctx));
	pi.on("before_agent_start", (event, ctx) => jev.startPrompt(event.messageType === "user" && !event.images?.length ? event.prompt : undefined, ctx));
	pi.on("user_bash", () => jev.clearInput());

	pi.on("turn_end", (event, ctx) => {
		const settings = readPolicy(pi, ctx);
		const band = pressure(settings);
		const checkpointId = currentCheckpoint(ctx)?.id;
		cycle.observe(checkpointId, band);
		const result = background.advance(event, ctx, settings, band);
		if (result?.draft) return { entries: [...event.entries, result.draft] };
		if (!result || !continuesNaturally(event)) return;
		if (result.failure) return note(event, `Self-compaction skipped: ${result.failure}.`);
		if (!settings.enabled || !pi.getActiveTools().includes(SELF_COMPACT_TOOL) || event.entries.some((entry) => entry.type === "compaction")) return;
		const notice = cycle.takeNotice(band);
		if (notice) return note(event, notice === "warning" ? WARNING : NOTICE);
	});

	status.listen(registerProactiveFooter(pi, background, jev));
	registerControls(pi, background, jev);
}
