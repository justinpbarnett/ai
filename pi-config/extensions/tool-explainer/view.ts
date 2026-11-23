import { BorderedLoader, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { matchesKey, ScrollView, Text, truncateToWidth } from "@earendil-works/pi-tui";
import type { Evidence, ManualRow } from "./evidence.js";
import { explain, failureMessage, JEV, withinDeadline, WRITER, type Explanation } from "./explain.js";

export function showView(ctx: ExtensionContext, title: string, body: string, signal: AbortSignal, allowSend = false) {
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
				const hint = allowSend ? "S send · Esc cancel · ↑↓ scroll" : "Enter or Esc close · ↑↓ scroll";
				const range = lines.length > height ? `  ${start + 1}–${Math.min(start + height, lines.length)}/${lines.length}` : "";
				return [
					truncateToWidth(theme.fg("accent", theme.bold(title)), width),
					...lines.slice(start, start + height),
					truncateToWidth(theme.fg("muted", hint + range), width),
				];
			},
			invalidate: () => text.invalidate(),
			dispose: () => signal.removeEventListener("abort", cancel),
			handleInput(data) {
				if (keys.matches(data, "tui.select.cancel")) return cancel();
				if (allowSend && matchesKey(data, "s")) return done(true);
				if (!allowSend && keys.matches(data, "tui.select.confirm")) return cancel();
				const page = Math.max(1, scroll.viewportHeight - 1);
				if (keys.matches(data, "tui.select.up")) scroll.scrollBy(-1);
				else if (keys.matches(data, "tui.select.down")) scroll.scrollBy(1);
				else if (matchesKey(data, "pageUp")) scroll.scrollBy(-page);
				else if (matchesKey(data, "pageDown")) scroll.scrollBy(page);
			},
		};
	}, allowSend ? { blocked: { kind: "permission", message: "Share tool excerpts with OpenRouter?" } } : undefined);
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

export function preview(calls: Evidence[], localCount: number): string {
	return [
		`Send ${calls.length} selected ${calls.length === 1 ? "call" : "calls"} to OpenRouter (${JEV} and ${WRITER}).`,
		"Upstream: TypeSafe and Google. Charges may apply.",
		`${localCount} selected ${localCount === 1 ? "call stays" : "calls stay"} local. Cancel if any excerpt is sensitive.`,
		"",
		JSON.stringify(calls, null, 2),
	].join("\n");
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
			// A prose model can turn a printed success string into an unsupported test claim.
			const text = result && row.evidence?.operation === "print"
				? (!row.failed && row.evidence.output?.trim() ? `Printed: ${row.evidence.output.trim()}` : row.text)
				: generated ?? row.text;
			return `${row.id}. ${kind}: ${text}${notes ? ` ${notes}` : ""}`;
		}),
	].join("\n");
}
