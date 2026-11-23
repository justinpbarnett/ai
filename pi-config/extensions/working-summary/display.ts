import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import type { Labels } from "./labels.js";

const SEPARATOR = "  |  ";

export function formatSummary({ session, prompt }: Labels, width?: number): string {
	if (!session || !prompt) {
		const label = session ?? prompt ?? "";
		return width === undefined ? label : truncateToWidth(label, width, "…");
	}
	if (width === undefined) return `${session}${SEPARATOR}${prompt}`;
	const promptWidth = width - visibleWidth(session) - SEPARATOR.length;
	if (promptWidth < 2) return truncateToWidth(session, width, "…");
	return `${session}${SEPARATOR}${truncateToWidth(prompt, promptWidth, "…")}`;
}
