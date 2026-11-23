import { createHash } from "node:crypto";

export const CREDENTIAL_LIKE = /-----BEGIN [\w ]*(?:PRIVATE KEY|SECRET)-----|\b(?:sk[-_][\w-]{8,}|(?:gh[pousr]_|github_pat_|xox[baprs]-|AKIA|ASIA)[\w-]{8,}|eyJ[\w-]+\.[\w-]+\.[\w-]+)|\bBearer\s+\S|(?:api[-_ ]?key|access[-_ ]?token|token|secret|password|credential)["']?\s*[:=]\s*\S|:\/\/[^\s/@:]+:[^\s/@]+@/i;

export const promptDigest = (text: string) => createHash("sha256").update(text).digest("hex");
