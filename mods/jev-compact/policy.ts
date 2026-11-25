export const SWITCH_FLOOR_TOKENS = 90_000
export const PAUSE_FLOOR_TOKENS = 120_000
export const SURE = 0.8
export const CREDENTIAL_LIKE = /-----BEGIN [\w ]*(?:PRIVATE KEY(?: BLOCK)?|SECRET)-----|\b(?:sk[-_][\w-]{8,}|(?:gh[pousr]_|github_pat_|xox[baprs]-|AKIA|ASIA|AIza|npm_|hf_|glpat-)[\w-]{8,}|eyJ[\w-]+\.[\w-]+\.[\w-]+)|\bBearer\s+\S|\bAuthorization["']?\s*:\s*(?:Basic|Digest)\s+\S|(?:^|\s)(?:-u|--user)\s+[^\s:]+:\S|\blogin\s+\S+\s+password\s+\S|(?:(?:api|secret|private|access|auth|signing|encryption)[-_ ]?key|access[-_ ]?token|token|secret|password|credential)["']?\s*[:=]\s*\S|:\/\/[^\s/@:]+:[^\s/@]+@/i
export const SWITCHES = 'Does the new message start a different task from the recent work, so that the details of the recent work no longer matter for it?'
export const PAUSES = "Did the assistant's last reply finish the work the user asked for, with nothing left running and no question waiting on the user, so this is a good point to pause?"

export function recommendation(tokens: number): string | undefined {
  if (tokens > 150_000) {
    return `Current context is ${tokens.toLocaleString('en-US')} tokens. Strongly recommend running /compact before continuing.`
  }
}
