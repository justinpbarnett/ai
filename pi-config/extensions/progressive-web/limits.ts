export const MAX_SCRAPE_URLS = 10;

export type TierKey = "http" | "curl" | "browser" | "brightData";
export const brightDataMinimumTimeoutMs = 60000;
export const tierSpecs: {
  key: TierKey;
  name: string;
  minimumTimeoutMs?: number;
}[] = [
  { key: "http", name: "HTTP fetch" },
  { key: "curl", name: "cURL + browser headers" },
  { key: "browser", name: "Playwright" },
  {
    key: "brightData",
    name: "Bright Data",
    minimumTimeoutMs: brightDataMinimumTimeoutMs,
  },
];
export const maxTierNumber = tierSpecs.length;

export const scrapeTimeoutLimits = {
  minimum: 1000,
  maximum: 120000,
  fallback: 30000,
};
export const crawlLimits = {
  maxPages: { minimum: 1, maximum: 50, fallback: 10 },
  maxDepth: { minimum: 0, maximum: 5, fallback: 2 },
  delayMs: { minimum: 250, maximum: 30000, fallback: 1000 },
};
export const searchLimits = {
  queryCharacters: { maximum: 600 },
  queryWords: { maximum: 75 },
  count: { minimum: 1, maximum: 20, fallback: 5 },
  offset: { minimum: 0, maximum: 9, fallback: 0 },
  timeoutMs: { minimum: 1000, maximum: 60000, fallback: 15000 },
};
export const previewLimits = {
  bytes: 47000,
  lines: 1900,
  overviewBytes: 10000,
  overviewLines: 300,
};
export const previewDescription = `${previewLimits.bytes / 1000} KB/${previewLimits.lines} lines`;
