export function isModelId(value: unknown): value is string {
	return typeof value === "string" && value.length <= 150 && /^(?:[\w.-]+\/)?[\w.-]+(?::[\w.-]+)?$/.test(value);
}
