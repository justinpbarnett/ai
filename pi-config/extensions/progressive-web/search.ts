import { JSDOM } from "jsdom";
import { loadBraveApiKey } from "./config.ts";
import { normalizeUrl } from "./content.ts";
import { responseText } from "./transports.ts";

export interface SearchOptions {
  query: string;
  count?: number;
  offset?: number;
  freshness?: string;
  country?: string;
  searchLang?: string;
  safeSearch?: string;
  timeoutMs?: number;
}

export interface SearchHit {
  rank: number;
  title: string;
  url: string;
  snippet: string;
  extraSnippets: string[];
  age?: string;
}

export interface SearchResult {
  provider: "brave";
  query: string;
  alteredQuery?: string;
  requestedCount: number;
  offset: number;
  moreResultsAvailable: boolean;
  results: SearchHit[];
  durationMs: number;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function plainText(value: unknown): string {
  return typeof value === "string"
    ? JSDOM.fragment(value).textContent?.replace(/\s+/g, " ").trim() || ""
    : "";
}

function validDate(value: string): boolean {
  const date = new Date(value);
  return (
    Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === value
  );
}

function searchParameters(options: SearchOptions) {
  const query = options.query.trim();
  if (!query || query.length > 600 || query.split(/\s+/).length > 75) {
    throw new Error(
      "Search query must contain 1-600 characters and no more than 75 words.",
    );
  }
  const count = options.count ?? 5;
  const offset = options.offset ?? 0;
  const timeoutMs = options.timeoutMs ?? 15000;
  for (const [name, value, minimum, maximum] of [
    ["count", count, 1, 20],
    ["offset", offset, 0, 9],
    ["timeoutMs", timeoutMs, 1000, 60000],
  ] as const) {
    if (!Number.isInteger(value) || value < minimum || value > maximum)
      throw new Error(
        `${name} must be an integer from ${minimum} to ${maximum}.`,
      );
  }
  const safeSearch = options.safeSearch ?? "moderate";
  if (!["off", "moderate", "strict"].includes(safeSearch))
    throw new Error("safeSearch must be off, moderate, or strict.");
  if (options.country && !/^[a-z]{2}$/i.test(options.country))
    throw new Error(
      "country must be a two-letter country code supported by Brave.",
    );
  if (
    options.searchLang &&
    !/^[a-z]{2,3}(?:-[a-z]{2,4})?$/i.test(options.searchLang)
  )
    throw new Error(
      "searchLang must be a language code supported by Brave, such as en or zh-hans.",
    );
  if (
    options.freshness &&
    !["pd", "pw", "pm", "py"].includes(options.freshness)
  ) {
    const range = options.freshness.match(
      /^(\d{4}-\d{2}-\d{2})to(\d{4}-\d{2}-\d{2})$/,
    );
    if (
      !range ||
      !validDate(range[1]) ||
      !validDate(range[2]) ||
      range[1] > range[2]
    ) {
      throw new Error(
        "freshness must be pd, pw, pm, py, or a valid YYYY-MM-DDtoYYYY-MM-DD date range.",
      );
    }
  }
  const parameters = new URLSearchParams({
    q: query,
    count: String(count),
    offset: String(offset),
    safesearch: safeSearch,
    text_decorations: "false",
    extra_snippets: "true",
    result_filter: "web",
  });
  if (options.country) parameters.set("country", options.country.toUpperCase());
  if (options.searchLang)
    parameters.set("search_lang", options.searchLang.toLowerCase());
  if (options.freshness) parameters.set("freshness", options.freshness);
  return { query, count, offset, timeoutMs, parameters };
}

function parseSearchResponse(payload: unknown, count: number) {
  const root = record(payload);
  if (root?.type !== "search")
    throw new Error("Brave Search returned an unexpected response format.");
  const web = record(root.web);
  if (web?.results !== undefined && !Array.isArray(web.results))
    throw new Error("Brave Search returned invalid web results.");
  const results: SearchHit[] = [];
  const seen = new Set<string>();
  for (const value of Array.isArray(web?.results) ? web.results : []) {
    const item = record(value);
    if (!item || typeof item.url !== "string") continue;
    let url: string;
    try {
      url = normalizeUrl(item.url);
    } catch {
      continue;
    }
    if (seen.has(url)) continue;
    seen.add(url);
    results.push({
      rank: results.length + 1,
      title: plainText(item.title) || url,
      url,
      snippet: plainText(item.description),
      extraSnippets: Array.isArray(item.extra_snippets)
        ? item.extra_snippets.slice(0, 5).map(plainText).filter(Boolean)
        : [],
      age: typeof item.age === "string" ? plainText(item.age) : undefined,
    });
    if (results.length >= count) break;
  }
  const query = record(root.query);
  return {
    results,
    alteredQuery:
      typeof query?.altered === "string" ? query.altered : undefined,
    moreResultsAvailable: query?.more_results_available === true,
  };
}

function braveError(response: Response): Error {
  switch (response.status) {
    case 401:
    case 403:
      return new Error(
        `Brave Search returned HTTP ${response.status}. Check your API key and Search API subscription.`,
      );
    case 422:
      return new Error(
        "Brave Search returned HTTP 422. Check your API key format and supported search parameters, including country, language, freshness, and SafeSearch.",
      );
    case 429: {
      const retryAfter = Number(response.headers.get("retry-after"));
      const advice =
        retryAfter > 0 && Number.isFinite(retryAfter)
          ? `Wait ${retryAfter} seconds before retrying.`
          : "Wait before retrying and check your plan quota.";
      return new Error(
        `Brave Search rate limit exceeded (HTTP 429). ${advice}`,
      );
    }
    default:
      return new Error(
        `Brave Search returned HTTP ${response.status}. Check search parameters and account availability.`,
      );
  }
}

export async function search(
  options: SearchOptions,
  runtime: { signal?: AbortSignal } = {},
): Promise<SearchResult> {
  runtime.signal?.throwIfAborted();
  const { query, count, offset, timeoutMs, parameters } =
    searchParameters(options);
  const apiKey = await loadBraveApiKey();
  if (!apiKey)
    throw new Error(
      "Brave Search is not configured. Set BRAVE_SEARCH_API_KEY, or copy your key and run: !pbpaste | node ~/.pi/agent/extensions/progressive-web/cli.mjs configure-brave",
    );
  const deadline = AbortSignal.timeout(timeoutMs);
  const signal = runtime.signal
    ? AbortSignal.any([runtime.signal, deadline])
    : deadline;
  const started = Date.now();
  try {
    const response = await fetch(
      `https://api.search.brave.com/res/v1/web/search?${parameters}`,
      {
        signal,
        redirect: "error",
        headers: { Accept: "application/json", "X-Subscription-Token": apiKey },
      },
    );
    if (!response.ok) {
      await response.body?.cancel();
      throw braveError(response);
    }
    const text = await responseText(response);
    let payload: unknown;
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error("Brave Search returned invalid JSON.");
    }
    const parsed = parseSearchResponse(payload, count);
    signal.throwIfAborted();
    return {
      provider: "brave",
      query,
      requestedCount: count,
      offset,
      ...parsed,
      durationMs: Date.now() - started,
    };
  } catch (error) {
    runtime.signal?.throwIfAborted();
    if (deadline.aborted)
      throw new Error(`Brave Search timed out after ${timeoutMs} ms.`);
    throw error;
  }
}
