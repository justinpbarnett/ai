import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { callsIn, safeLabel, toolActivity, type ToolActivity } from "./evidence.js";
import type { Batch } from "./inline.js";

const ENTRY_TYPE = "tool-explainer.batch.v1";

type SavedBatch = { callIds: string[]; failed: boolean; purpose?: string; route: string };

export function saveBatch(pi: ExtensionAPI, batch: Batch) {
	const record: SavedBatch = {
		callIds: batch.rows.map(({ callId }) => callId),
		failed: batch.rows[0]?.failed ?? false,
		purpose: batch.purpose,
		route: batch.pending ? "no summary: writer interrupted" : batch.route,
	};
	pi.appendEntry(ENTRY_TYPE, record);
}

function readBatch(data: unknown): SavedBatch | undefined {
	if (!data || typeof data !== "object") return;
	const { callIds, failed, purpose, route } = data as Partial<SavedBatch>;
	if (!Array.isArray(callIds) || callIds.length < 1 || callIds.length > 10 ||
		!callIds.every((id) => typeof id === "string" && id.length > 0) || new Set(callIds).size !== callIds.length ||
		typeof failed !== "boolean" || (failed && callIds.length !== 1) ||
		typeof route !== "string" || route.length > 256 || !safeLabel(route) ||
		(purpose !== undefined && (typeof purpose !== "string" || purpose.length > 120 || !safeLabel(purpose)))) return;
	return { callIds, failed, purpose, route };
}

export function loadBatches(ctx: ExtensionContext): Batch[] {
	const branch = ctx.sessionManager.getBranch();
	const records = new Map<string, SavedBatch>();
	for (const entry of branch) {
		if (entry.type !== "custom" || entry.customType !== ENTRY_TYPE) continue;
		const record = readBatch(entry.data);
		if (record) records.set(record.callIds.at(-1)!, record);
	}
	const missing = new Set([...records.values()].flatMap(({ purpose, callIds }) => purpose ? [] : callIds));
	const activities = new Map<string, ToolActivity>();
	if (missing.size) {
		const messages = branch.flatMap((entry) => entry.type === "message" ? [entry.message] : []);
		for (const call of callsIn(messages)) {
			const id = call.result.toolCallId;
			if (missing.delete(id)) activities.set(id, toolActivity(call, ctx.cwd));
			if (!missing.size) break;
		}
	}
	return [...records.values()].map(({ callIds, failed, purpose, route }) => ({
		rows: callIds.map((callId) => ({ callId, failed, activity: activities.get(callId) })), purpose, route,
	}));
}

export function visibleToolResults(ctx: ExtensionContext): Set<string> {
	return new Set(ctx.sessionManager.buildContextEntries().flatMap((entry) =>
		entry.type === "message" && entry.message.role === "toolResult" ? [entry.message.toolCallId] : []));
}
