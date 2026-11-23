import {
	AssistantMessageComponent, BashExecutionComponent, BranchSummaryMessageComponent,
	CompactionSummaryMessageComponent, SkillInvocationMessageComponent, keyHint, keyText,
} from "@earendil-works/pi-coding-agent";
import {
	Box, Container, Markdown, MouseRegion, Text, sliceByColumn, stripTerminalSequences, visibleWidth,
	type Component,
} from "@earendil-works/pi-tui";

export function clickToToggle(child: Component, toggle: () => void): MouseRegion {
	return new MouseRegion(child, (event) => {
		// Pi dispatches click on release, only if the gesture wasn't a selection drag.
		if (event.type !== "click" || event.button !== "left") return;
		toggle();
		return { handled: true };
	});
}

const EXPAND_ACTION = "app.tools.expand";
type HintSource = "tool" | "summary" | "shell";

function cleanHintLine(line: string, source: HintSource, key: string): string {
	if (!line.includes("to expand") && !line.includes("to collapse")) return line;
	const label = stripTerminalSequences(line);
	const expand = ` (${key} to expand)`;
	if (source === "shell" && label === `(${key} to collapse)`) return "";
	if (label.endsWith(expand) && (source !== "tool" || /^(?:\[skill\] |read (?:docs|example|resource) )/.test(label))) {
		return sliceByColumn(line, 0, visibleWidth(label.slice(0, -expand.length)));
	}
	const countHint = `, ${key} to expand)`;
	if (source === "tool" && label.endsWith(countHint) && line.includes(keyHint(EXPAND_ACTION, "to expand"))) {
		const count = label.slice(0, -countHint.length);
		if (/^\.\.\. \(\d+ (?:more|earlier) \w+(?:, \d+ total)?$/.test(count)) {
			return sliceByColumn(line, 0, visibleWidth(count)) + ")";
		}
	}
	return line;
}

function field(component: object, name: string): unknown {
	return Reflect.get(component, name);
}

const checkedText = new WeakMap<Text, string>();
const wrappedPreview = new WeakSet<object>();

export function removeExpansionHints<T extends Component>(component: T, source: HintSource = "tool"): T {
	const key = keyText(EXPAND_ACTION);
	const clean = (line: string) => cleanHintLine(line, source, key);
	function visit(child: Component) {
		// These native Pi components don't expose their labels through the extension API.
		if (child instanceof Text) {
			const text = field(child, "text");
			if (typeof text !== "string" || checkedText.get(child) === text) return;
			if (!text.includes("to expand") && !text.includes("to collapse")) {
				checkedText.set(child, text);
				return;
			}
			const lines = text.split("\n");
			const cleaned = lines.map(clean).filter((line, i) => line || !lines[i]).join("\n");
			if (cleaned !== text) child.setText(cleaned);
			checkedText.set(child, cleaned);
		} else if (child instanceof Container || child instanceof Box) {
			for (const item of child.children) visit(item);
		} else if (child instanceof MouseRegion) {
			const content = field(child, "child") as Component | undefined;
			if (content?.render) visit(content);
		} else if (source === "tool") {
			const preview = field(child, "options") as { formatHint?: (hidden: number) => string } | undefined;
			if (typeof preview?.formatHint !== "function" || wrappedPreview.has(preview)) return;
			const formatHint = preview.formatHint;
			preview.formatHint = (hidden) => clean(formatHint(hidden));
			wrappedPreview.add(preview);
			child.invalidate();
		}
	}
	visit(component);
	return component;
}

export class TranscriptPresentation {
	thinkingExpanded?: boolean;
	private thinkingOverrides = new WeakMap<Markdown, boolean>();

	resetThinking() {
		this.thinkingOverrides = new WeakMap();
	}

	attach(thinkingSummarized: () => boolean, toolsExpanded: () => boolean): () => void {
		let defaultExpanded = toolsExpanded();
		const currentDefault = () => {
			const expanded = toolsExpanded();
			if (expanded !== defaultExpanded) {
				defaultExpanded = expanded;
				this.resetThinking();
			}
			return expanded;
		};
		const detach = [this.patchThinkingRegions(thinkingSummarized, currentDefault), patchSummaryComponents(), patchShellComponent()];
		return () => { for (const restore of detach) restore(); };
	}

	private patchThinkingRegions(thinkingSummarized: () => boolean, currentDefault: () => boolean): () => void {
		const assistant = AssistantMessageComponent.prototype;
		const update = assistant.updateContent;
		const presentation = this;
		assistant.updateContent = function (...args) {
			update.apply(this, args);
			if (!thinkingSummarized()) return;
			const content = field(this, "contentContainer");
			if (!(content instanceof Container)) return;
			const nativelyHidden = field(this, "hideThinkingBlock") === true;
			content.children.forEach((region, i) => {
				if (!(region instanceof MouseRegion)) return;
				const markdown = field(region, "child");
				if (!(markdown instanceof Markdown)) return;
				const expanded = () => {
					const fallback = currentDefault();
					return nativelyHidden || (presentation.thinkingOverrides.get(markdown) ?? fallback);
				};
				let renderedExpanded: boolean | undefined;
				const renderedThought: Component = {
					render(width) {
						const next = expanded();
						if (renderedExpanded !== undefined && renderedExpanded !== next) markdown.invalidate();
						renderedExpanded = next;
						const previous = presentation.thinkingExpanded;
						presentation.thinkingExpanded = next;
						try { return markdown.render(width); }
						finally { presentation.thinkingExpanded = previous; }
					},
					invalidate: () => markdown.invalidate(),
				};
				content.children[i] = nativelyHidden
					? { ...renderedThought, handleMouse: (event) => region.handleMouse(event) }
					: clickToToggle(renderedThought, () => presentation.thinkingOverrides.set(markdown, !expanded()));
			});
		};
		return () => { assistant.updateContent = update; };
	}
}

function patchSummaryComponents(): () => void {
	const detach: (() => void)[] = [];
	for (const { prototype } of [SkillInvocationMessageComponent, BranchSummaryMessageComponent, CompactionSummaryMessageComponent]) {
		const render = prototype.render;
		prototype.render = function (width) {
			if (field(this, "expanded") === false) removeExpansionHints(this, "summary");
			return render.call(this, width);
		};
		detach.push(() => { prototype.render = render; });
	}
	return () => { for (const restore of detach) restore(); };
}

function patchShellComponent(): () => void {
	const shell = BashExecutionComponent.prototype;
	const renderShell = shell.render;
	const shellMouse = shell.handleMouse;
	shell.render = function (width) {
		const body = field(this, "contentContainer");
		if (body instanceof Container && field(this, "status") !== "running") {
			const status = body.children.at(-1);
			if (status instanceof Text) {
				removeExpansionHints(status, "shell");
				if (field(status, "text") === "") body.removeChild(status);
			}
		}
		return renderShell.call(this, width);
	};
	shell.handleMouse = function (event) {
		const result = shellMouse.call(this, event);
		if (result || event.type !== "click" || event.button !== "left" || field(this, "status") === "running") return result;
		const expanded = field(this, "expanded");
		if (typeof expanded !== "boolean" || event.y < 2 || event.y >= event.height - 1) return;
		this.setExpanded(!expanded);
		return {
			handled: true,
			target: { component: this, originX: event.screenX - event.x, originY: event.screenY - event.y, width: event.width, height: event.height },
		};
	};
	return () => {
		shell.render = renderShell;
		shell.handleMouse = shellMouse;
	};
}
