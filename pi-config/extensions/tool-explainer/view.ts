import { BorderedLoader, type ExtensionContext, type KeybindingsManager } from "@earendil-works/pi-coding-agent";
import { matchesKey, ScrollView, Text, truncateToWidth } from "@earendil-works/pi-tui";
import { withinDeadline } from "./deadline.js";
import type { Evidence, ManualRow } from "./evidence.js";
import { JEV_CLASSIFIER_MODEL, JEV_UPSTREAM, OPENROUTER_WRITER_MODEL, WRITER_UPSTREAM } from "../shared/openrouter.js";
import { explain, failureMessage, type Explanation } from "./explain.js";

type DialogMode = {
	hint: string;
	decide: (data: string, keys: KeybindingsManager) => boolean | undefined;
	blocked?: { kind: "permission"; message: string };
};

const READ_ONLY_VIEW: DialogMode = {
	hint: "Enter or Esc close · ↑↓ scroll",
	decide: (data, keys) => keys.matches(data, "tui.select.cancel") || keys.matches(data, "tui.select.confirm") ? false : undefined,
};

const SEND_PREVIEW: DialogMode = {
	hint: "S send · Esc cancel · ↑↓ scroll",
	decide: (data, keys) => keys.matches(data, "tui.select.cancel") ? false : matchesKey(data, "s") || matchesKey(data, "shift+s") ? true : undefined,
	blocked: { kind: "permission", message: "Share tool excerpts with OpenRouter?" },
};

function scrollDialog(ctx: ExtensionContext, title: string, body: string, signal: AbortSignal, mode: DialogMode) {
	if (signal.aborted) return Promise.resolve(false);
	return ctx.ui.custom<boolean>((tui, theme, keys, done) => {
		const text = new Text(body, 0, 0);
		const scroll = new ScrollView(text, { scrollbar: "hidden" });
		const cancel = () => done(false);
		signal.addEventListener("abort", cancel, { once: true });
		return {
			render(width) {
				const lines = scroll.render(width);
				const height = Math.max(1, Math.min(22, Math.floor(tui.terminal.rows / 2) - 3));
				scroll.updateLayout(lines.length, height, () => tui.requestRender());
				const start = scroll.scrollTop;
				const range = lines.length > height ? `  ${start + 1}–${Math.min(start + height, lines.length)}/${lines.length}` : "";
				return [
					truncateToWidth(theme.fg("accent", theme.bold(title)), width),
					...lines.slice(start, start + height),
					truncateToWidth(theme.fg("muted", mode.hint + range), width),
				];
			},
			invalidate: () => text.invalidate(),
			dispose: () => signal.removeEventListener("abort", cancel),
			handleInput(data) {
				const decision = mode.decide(data, keys);
				if (decision !== undefined) return done(decision);
				const page = Math.max(1, scroll.viewportHeight - 1);
				if (keys.matches(data, "tui.select.up")) scroll.scrollBy(-1);
				else if (keys.matches(data, "tui.select.down")) scroll.scrollBy(1);
				else if (matchesKey(data, "pageUp")) scroll.scrollBy(-page);
				else if (matchesKey(data, "pageDown")) scroll.scrollBy(page);
			},
		};
	}, mode.blocked && { blocked: mode.blocked });
}

export async function showView(ctx: ExtensionContext, title: string, body: string, signal: AbortSignal) {
	await scrollDialog(ctx, title, body, signal, READ_ONLY_VIEW);
}

export function confirmPreview(ctx: ExtensionContext, title: string, body: string, signal: AbortSignal): Promise<boolean> {
	return scrollDialog(ctx, title, body, signal, SEND_PREVIEW);
}

export function preview(calls: Evidence[], localCount: number): string {
	return [
		`Send ${calls.length} selected ${calls.length === 1 ? "call" : "calls"} to OpenRouter (${JEV_CLASSIFIER_MODEL} and ${OPENROUTER_WRITER_MODEL}).`,
		`Upstream: ${JEV_UPSTREAM} and ${WRITER_UPSTREAM}. Charges may apply.`,
		`${localCount} selected ${localCount === 1 ? "call stays" : "calls stay"} local. Cancel if any excerpt is sensitive.`,
		"",
		JSON.stringify(calls, null, 2),
	].join("\n");
}

function deterministicPrintText(row: ManualRow, evidence: Evidence): string {
	const output = evidence.output?.trim();
	return !row.failed && output ? `Printed: ${output}` : row.text;
}

export function explanationText(rows: ManualRow[], result?: Explanation, error?: string): string {
	const printed = rows.some((row) => row.evidence?.operation === "print");
	return [
		result ? (printed ? "Printed output is reported as text, not as proof that a check ran." : result.overview)
			: error ?? "No excerpts sent. Local tool facts are shown below.",
		"",
		...rows.map((row) => {
			const generated = result?.items.get(row.id);
			const kind = row.failed ? "Error" : "Completed";
			const notes = [row.note, row.evidence?.clipped && "Excerpt clipped."].filter(Boolean).join(" ");
			const text = result && row.evidence?.operation === "print" ? deterministicPrintText(row, row.evidence) : generated ?? row.text;
			return `${row.id}. ${kind}: ${text}${notes ? ` ${notes}` : ""}`;
		}),
	].join("\n");
}

export async function collectExplanation(ctx: ExtensionContext, calls: Evidence[], signal: AbortSignal) {
	const registry = ctx.modelRegistry;
	return ctx.ui.custom<{ result?: Explanation; error?: string } | undefined>((tui, theme, _keys, done) => {
		const loader = new BorderedLoader(tui, theme, "Explaining tool output via OpenRouter…");
		const combined = AbortSignal.any([signal, loader.signal]);
		loader.onAbort = () => done(undefined);
		void withinDeadline(combined, (deadline) => explain(registry, calls, deadline)).then(
			(result) => { if (!combined.aborted) done({ result }); },
			(error: unknown) => { if (!loader.signal.aborted) done(signal.aborted ? undefined : { error: failureMessage(error) }); },
		);
		return loader;
	});
}
