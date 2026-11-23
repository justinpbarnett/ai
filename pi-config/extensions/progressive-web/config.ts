import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

interface Credentials {
  token?: string;
  zone?: string;
}

function expandTilde(path: string): string {
  if (path === "~") return homedir();
  if (path.startsWith("~/")) return join(homedir(), path.slice(2));
  return path;
}

const stateDirectory = join(
  expandTilde(
    process.env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent"),
  ),
  "web-scraper",
);
export const credentialsPath = join(stateDirectory, "credentials.json");
export const braveCredentialsPath = join(stateDirectory, "brave-search.json");

async function readCredentials(path: string): Promise<Record<string, unknown>> {
  try {
    const value: unknown = JSON.parse(await readFile(path, "utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value))
      throw new Error("Invalid credentials.");
    return value as Record<string, unknown>;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT")
      return {};
    throw new Error(
      `Cannot read ${path}. Check file permissions and JSON syntax.`,
    );
  }
}

export async function loadBraveApiKey(): Promise<string | undefined> {
  if (process.env.BRAVE_SEARCH_API_KEY) return process.env.BRAVE_SEARCH_API_KEY;
  const stored = await readCredentials(braveCredentialsPath);
  return typeof stored.apiKey === "string" ? stored.apiKey : undefined;
}

export async function loadCredentials(): Promise<Credentials> {
  const { BRIGHT_DATA_API_TOKEN: token, BRIGHT_DATA_ZONE: zone } = process.env;
  if (token && zone) return { token, zone };

  const stored = await readCredentials(credentialsPath);
  return {
    token:
      token || (typeof stored.token === "string" ? stored.token : undefined),
    zone: zone || (typeof stored.zone === "string" ? stored.zone : undefined),
  };
}

function validateSecret(secret: string, provider: string): void {
  if (
    !secret ||
    /\s/.test(secret) ||
    secret.length < 10 ||
    secret.length > 4096
  ) {
    throw new Error(
      `Expected a ${provider} API key on stdin, not an empty value or text containing whitespace.`,
    );
  }
}

async function writeCredentials(
  path: string,
  value: Record<string, string>,
): Promise<void> {
  await mkdir(stateDirectory, { recursive: true, mode: 0o700 });
  await chmod(stateDirectory, 0o700);
  const directory = await mkdtemp(join(stateDirectory, ".credentials-"));
  try {
    const temporary = join(directory, "credentials.json");
    await writeFile(temporary, JSON.stringify(value, null, 2) + "\n", {
      mode: 0o600,
    });
    await rename(temporary, path);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

export async function configure(
  token: string,
  zone: string | undefined,
): Promise<string> {
  validateSecret(token, "Bright Data");
  if (!zone || !/^[a-zA-Z0-9_-]{1,128}$/.test(zone)) {
    throw new Error("Provide your Web Unlocker zone name with --zone NAME.");
  }
  await writeCredentials(credentialsPath, { token, zone });
  return `Bright Data credentials saved privately to ${credentialsPath}.`;
}

export async function configureBrave(apiKey: string): Promise<string> {
  validateSecret(apiKey, "Brave Search");
  await writeCredentials(braveCredentialsPath, { apiKey });
  return `Brave Search credentials saved privately to ${braveCredentialsPath}.`;
}
