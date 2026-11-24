import { readFileSync } from "node:fs";
import { join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";

export function readSettingsFile(file: string): unknown {
	try {
		return JSON.parse(readFileSync(join(getAgentDir(), file), "utf8"));
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
	}
}

export function onlyKnownKeys(value: object, known: readonly string[]): void {
	const unknown = Object.keys(value).find((key) => !known.includes(key));
	if (unknown !== undefined) throw new Error(`Unknown setting ${unknown}`);
}
