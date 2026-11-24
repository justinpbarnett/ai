import { createHash } from "node:crypto";

export const CREDENTIAL_LIKE = /-----BEGIN [\w ]*(?:PRIVATE KEY(?: BLOCK)?|SECRET)-----|\b(?:sk[-_][\w-]{8,}|(?:gh[pousr]_|github_pat_|xox[baprs]-|AKIA|ASIA|AIza|npm_|hf_|glpat-)[\w-]{8,}|eyJ[\w-]+\.[\w-]+\.[\w-]+)|\bBearer\s+\S|\bAuthorization["']?\s*:\s*(?:Basic|Digest)\s+\S|(?:^|\s)(?:-u|--user)\s+[^\s:]+:\S|\blogin\s+\S+\s+password\s+\S|(?:api[-_ ]?key|access[-_ ]?token|token|secret|password|credential)["']?\s*[:=]\s*\S|:\/\/[^\s/@:]+:[^\s/@]+@/i;

const PRIVATE_PATH = /(?:^|[\s/\\'"=@])(?:\.env(?:\.[\w.-]+)?|\.ssh|\.aws|\.gnupg|auth\.json|credentials(?:\.json)?|id_(?:rsa|ed25519))(?:$|[\s/\\'";])/i;

const MENTION = /(?:^|\s)@\S/;

const LOCAL_ONLY_CONTENT = /<(?:file|skill|attachment)\b|\[.*?\]\(file:|file:\/\/|```|~~~/i;

export const isSensitiveText = (text: string) => CREDENTIAL_LIKE.test(text) || PRIVATE_PATH.test(text);

export const hasMention = (text: string) => MENTION.test(text);

export const isShareableValue = (text: string) => !LOCAL_ONLY_CONTENT.test(text) && !isSensitiveText(text);

export const isCommandInput = (text: string) => /^[!/]/.test(text.trimStart());

export const isShareablePrompt = (text: string) => !isCommandInput(text) && !hasMention(text) && isShareableValue(text);

export const promptDigest = (text: string) => createHash("sha256").update(text).digest("hex");
