import { FooterComponent } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Container, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import type { Component, TUI } from "@earendil-works/pi-tui";
import type { BackgroundCompaction } from "./background.js";
import type { Jev } from "./jev.js";
import { pressure, readPolicy } from "./policy.js";

const CAPTURE_WIDGET = "pi-self-compact-footer-capture";
const AUTO_INDICATOR = /((?:\d+(?:\.\d+)?%|\?)\/\d+(?:\.\d+)?[kM]? )\(auto\)/;

function findNativeFooter(component: Component): FooterComponent | undefined {
	if (component instanceof FooterComponent) return component;
	if (!(component instanceof Container)) return;
	for (const child of component.children) {
		const footer = findNativeFooter(child);
		if (footer) return footer;
	}
}

function replaceIndicator(line: string, width: number, label: string) {
	if (!AUTO_INDICATOR.test(line)) return line;
	const fit = (indicator: string) => {
		const status = line.replace(AUTO_INDICATOR, (_, usage) => `${usage}(${indicator})`);
		const extra = visibleWidth(status) - width;
		return extra > 0 ? status.replace(/ {2,}/, (padding) => " ".repeat(Math.max(2, padding.length - extra))) : status;
	};
	const detailed = fit(label);
	return visibleWidth(detailed) <= width ? detailed : truncateToWidth(fit("proactive"), width, "");
}

function captureMountedFooter(ctx: ExtensionContext) {
	let host: { tui: TUI; footer: FooterComponent } | undefined;
	ctx.ui.setWidget(CAPTURE_WIDGET, (tui) => {
		const footer = findNativeFooter(tui);
		if (footer) host = { tui, footer };
		return { render: () => [], invalidate() {} };
	});
	ctx.ui.setWidget(CAPTURE_WIDGET, undefined);
	return host;
}

function installProactiveFooter(ctx: ExtensionContext) {
	const host = captureMountedFooter(ctx);
	if (!host) return;

	const { tui, footer } = host;
	const originalRender = footer.render;
	let label = "proactive";
	const render: FooterComponent["render"] = function (this: FooterComponent, width) {
		const lines = originalRender.call(this, width);
		if (lines[1]) lines[1] = replaceIndicator(lines[1], width, label);
		return lines;
	};
	footer.render = render;
	return {
		update(next: string) {
			if (next === label) return;
			label = next;
			tui.requestRender();
		},
		dispose() {
			if (footer.render === render) footer.render = originalRender;
		},
	};
}

export function registerProactiveFooter(pi: ExtensionAPI, background: BackgroundCompaction, jev: Jev) {
	let footer: ReturnType<typeof installProactiveFooter>;
	function refresh(ctx: ExtensionContext) {
		if (!footer) return;
		const settings = readPolicy(pi, ctx);
		const band = settings.problem ? "policy unavailable" : pressure(settings);
		const job = background.status();
		const progress = job === "idle" ? "" : ` (${job})`;
		footer.update(`proactive: ${band}${progress} | JEV ${jev.describe(ctx, settings)}`);
	}

	pi.on("session_start", (_, ctx) => {
		footer?.dispose();
		footer = ctx.mode === "tui" ? installProactiveFooter(ctx) : undefined;
		refresh(ctx);
	});
	pi.on("session_shutdown", () => { footer?.dispose(); footer = undefined; });
	const refreshOn = (_: unknown, ctx: ExtensionContext) => refresh(ctx);
	pi.on("session_compact", refreshOn);
	pi.on("session_compact_failed", refreshOn);
	pi.on("turn_start", refreshOn);
	pi.on("agent_settled", refreshOn);
	return refresh;
}
