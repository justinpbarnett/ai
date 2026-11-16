import { setTimeout as sleep } from "node:timers/promises";
import robotsParser from "robots-parser";
import {
  braveCredentialsPath,
  credentialsPath,
  loadBraveApiKey,
  loadCredentials,
} from "./config.ts";
import {
  checkScope,
  extractPage,
  NonRetryableError,
  normalizeUrl,
  type PageContent,
  type UrlPolicy,
} from "./content.ts";
import {
  brightDataFetch,
  browserFetch,
  browserInstalled,
  closeBrowsers,
  curlFetch,
  httpFetch,
  type PageTransport,
} from "./transports.ts";

export interface ScrapeOptions {
  startTier?: number;
  maxTier?: number;
  timeoutMs?: number;
  fresh?: boolean;
  waitForSelector?: string;
}

export interface ScrapeRuntime {
  signal?: AbortSignal;
  onProgress?: (message: string) => void;
  allowedUrl?: UrlPolicy;
}

export interface PageAttempt {
  tier: number;
  durationMs: number;
  ok: boolean;
  error?: string;
}

interface PageBase {
  requestedUrl: string;
  url: string;
  attempts: PageAttempt[];
  durationMs: number;
}

export interface PageSuccess extends PageBase, PageContent {
  ok: true;
  tier: number;
  tierName: string;
  status: number;
  cached: boolean;
}

export interface PageFailure extends PageBase {
  ok: false;
  error: string;
}

export type PageResult = PageSuccess | PageFailure;
export interface PageCollection {
  ok: boolean;
  pages: PageResult[];
  skipped?: { url: string; reason: string }[];
  remaining?: number;
}

export interface CrawlOptions extends ScrapeOptions {
  url: string;
  maxPages?: number;
  maxDepth?: number;
  pathPrefix?: string;
  delayMs?: number;
}

const tiers: {
  name: string;
  fetch: PageTransport;
  minimumTimeoutMs?: number;
}[] = [
  { name: "HTTP fetch", fetch: httpFetch },
  { name: "cURL + browser headers", fetch: curlFetch },
  { name: "Playwright", fetch: browserFetch },
  { name: "Bright Data", fetch: brightDataFetch, minimumTimeoutMs: 60000 },
];
const cache = new Map<
  string,
  { result: PageSuccess; bytes: number; expires: number }
>();
let cacheBytes = 0;

function boundedInteger(
  value: number | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
  label: string,
): number {
  const result = value ?? fallback;
  if (!Number.isInteger(result) || result < minimum || result > maximum) {
    throw new Error(
      `${label} must be an integer from ${minimum} to ${maximum}.`,
    );
  }
  return result;
}

function removeCachedPage(key: string): void {
  const entry = cache.get(key);
  if (entry) {
    cacheBytes -= entry.bytes;
    cache.delete(key);
  }
}

function cachedPage(key: string): PageSuccess | undefined {
  const entry = cache.get(key);
  if (!entry) return;
  if (entry.expires <= Date.now()) {
    removeCachedPage(key);
    return;
  }
  return { ...entry.result, cached: true };
}

function cachePage(key: string, result: PageSuccess): void {
  removeCachedPage(key);
  const bytes = Buffer.byteLength(JSON.stringify(result));
  if (bytes >= 2 * 1024 * 1024) return;
  while (cache.size >= 64 || cacheBytes + bytes > 32 * 1024 * 1024) {
    removeCachedPage(cache.keys().next().value!);
  }
  cache.set(key, { result, bytes, expires: Date.now() + 15 * 60 * 1000 });
  cacheBytes += bytes;
}

export async function dispose(): Promise<void> {
  await closeBrowsers();
  cache.clear();
  cacheBytes = 0;
}

export async function status() {
  const { token, zone } = await loadCredentials();
  const braveKey = await loadBraveApiKey();
  const installed = await browserInstalled();
  return {
    search: `Brave Web Search: ${braveKey ? "configured (not yet validated)" : "not configured"}`,
    braveCredentialsPath,
    tiers: [
      "1. HTTP fetch + Readability: ready",
      "2. cURL + browser headers: ready (requires curl on PATH)",
      `3. Playwright Chromium: ${installed ? "ready" : "missing; run npm run browser:install in the extension directory"}`,
      `4. Bright Data Web Unlocker: ${token && zone ? `configured (zone: ${zone}; not yet validated)` : "not configured"}`,
    ],
    credentialsPath,
    cacheEntries: cache.size,
  };
}

export async function scrape(
  options: ScrapeOptions & { url: string },
  runtime: ScrapeRuntime = {},
): Promise<PageResult> {
  const url = normalizeUrl(options.url);
  const startTier = boundedInteger(
    options.startTier,
    options.waitForSelector ? 3 : 1,
    1,
    4,
    "startTier",
  );
  const maxTier = boundedInteger(options.maxTier, 4, startTier, 4, "maxTier");
  const timeoutMs = boundedInteger(
    options.timeoutMs,
    30000,
    1000,
    120000,
    "timeoutMs",
  );
  if (options.waitForSelector && maxTier < 3)
    throw new Error("waitForSelector requires browser tier 3.");
  runtime.signal?.throwIfAborted();
  const cacheKey = JSON.stringify([
    url,
    startTier,
    maxTier,
    options.waitForSelector || "",
  ]);
  const cached = options.fresh ? undefined : cachedPage(cacheKey);
  if (cached) {
    checkScope(cached.url, runtime.allowedUrl);
    return cached;
  }
  const attempts: PageAttempt[] = [];
  const started = Date.now();
  for (let tier = startTier; tier <= maxTier; tier++) {
    runtime.signal?.throwIfAborted();
    const transport = tiers[tier - 1];
    runtime.onProgress?.(`${url}: tier ${tier} (${transport.name})`);
    const attemptStarted = Date.now();
    const tierTimeoutMs = Math.max(timeoutMs, transport.minimumTimeoutMs || 0);
    const deadline = AbortSignal.timeout(tierTimeoutMs);
    const signal = runtime.signal
      ? AbortSignal.any([runtime.signal, deadline])
      : deadline;
    try {
      const response = await transport.fetch(url, {
        signal,
        timeoutMs: tierTimeoutMs,
        waitForSelector: options.waitForSelector,
        allowedUrl: runtime.allowedUrl,
      });
      signal.throwIfAborted();
      checkScope(response.url, runtime.allowedUrl);
      const content = extractPage(response);
      signal.throwIfAborted();
      attempts.push({
        tier,
        durationMs: Date.now() - attemptStarted,
        ok: true,
      });
      const result: PageSuccess = {
        ok: true,
        requestedUrl: url,
        url: response.url,
        ...content,
        tier,
        tierName: transport.name,
        status: response.status,
        attempts,
        durationMs: Date.now() - started,
        cached: false,
      };
      cachePage(cacheKey, result);
      return result;
    } catch (error) {
      runtime.signal?.throwIfAborted();
      const message = deadline.aborted
        ? `Tier timed out after ${tierTimeoutMs} ms.`
        : error instanceof Error
          ? error.message
          : String(error);
      attempts.push({
        tier,
        durationMs: Date.now() - attemptStarted,
        ok: false,
        error: message,
      });
      runtime.onProgress?.(`Tier ${tier} failed: ${message}`);
      if (error instanceof NonRetryableError) break;
    }
  }
  return {
    ok: false,
    requestedUrl: url,
    url,
    attempts,
    durationMs: Date.now() - started,
    error: attempts
      .map((attempt) => `Tier ${attempt.tier}: ${attempt.error}`)
      .join("\n"),
  };
}

export async function scrapeBatch(
  options: ScrapeOptions & { urls: string[] },
  runtime: ScrapeRuntime = {},
): Promise<PageCollection> {
  if (!options.urls.length || options.urls.length > 10)
    throw new Error("Scrape requires 1-10 URLs.");
  const urls = options.urls.map((url) => normalizeUrl(url));
  const pages: PageResult[] = new Array(urls.length);
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(2, urls.length) }, async () => {
      while (next < urls.length) {
        const index = next++;
        pages[index] = await scrape({ ...options, url: urls[index] }, runtime);
      }
    }),
  );
  return { ok: pages.some((page) => page.ok), pages };
}

async function crawlPolicy(origin: string, signal: AbortSignal) {
  const url = `${origin}/robots.txt`;
  const response = await httpFetch(url, {
    signal,
    allowedUrl: (target) => new URL(target).origin === origin,
  });
  if ([404, 410].includes(response.status)) return robotsParser(url, "");
  if (response.status < 200 || response.status >= 300) {
    throw new Error(
      `robots.txt returned HTTP ${response.status}; crawl stopped rather than guessing permission.`,
    );
  }
  if (
    /html/i.test(response.contentType) &&
    /^\s*(?:<!doctype|<html)/i.test(response.body)
  ) {
    throw new Error(
      "robots.txt returned HTML instead of crawl rules; crawl stopped.",
    );
  }
  return robotsParser(url, response.body);
}

function crawlablePath(path: string): boolean {
  return (
    !/\.(?:pdf|zip|gz|tar|exe|dmg|png|jpe?g|gif|svg|webp|ico|mp[34]|wav|woff2?|ttf|css|js)$/i.test(
      path,
    ) &&
    !/(?:^|\/)(?:log(?:in|out)|sign[-_]?(?:in|out|up)|register|checkout|cart)(?:\/|$)/i.test(
      path,
    )
  );
}

export async function crawl(
  options: CrawlOptions,
  runtime: ScrapeRuntime = {},
) {
  const url = normalizeUrl(options.url);
  const origin = new URL(url).origin;
  const maxPages = boundedInteger(options.maxPages, 10, 1, 50, "maxPages");
  const maxDepth = boundedInteger(options.maxDepth, 2, 0, 5, "maxDepth");
  let delayMs = boundedInteger(options.delayMs, 1000, 250, 30000, "delayMs");
  const pathPrefix = options.pathPrefix || "/";
  if (!pathPrefix.startsWith("/"))
    throw new Error("pathPrefix must start with /.");
  const inScope = (value: string) => {
    const candidate = new URL(value);
    return (
      candidate.origin === origin && candidate.pathname.startsWith(pathPrefix)
    );
  };
  if (!inScope(url))
    throw new Error("The starting URL must be inside pathPrefix.");
  const deadline = AbortSignal.timeout(15000);
  const policy = await crawlPolicy(
    origin,
    runtime.signal ? AbortSignal.any([runtime.signal, deadline]) : deadline,
  );
  const crawlDelay =
    policy.getCrawlDelay("PiWebScraper") ?? policy.getCrawlDelay("*");
  if (crawlDelay !== undefined && Number.isFinite(crawlDelay))
    delayMs = Math.max(delayMs, crawlDelay * 1000);
  if (delayMs > 30000)
    throw new Error(
      "robots.txt requests a crawl delay over 30 seconds. Use individual page fetches instead.",
    );
  const allowedUrl = (value: string) =>
    inScope(value) && policy.isAllowed(value, "PiWebScraper") !== false;
  const queue = [{ url, depth: 0 }];
  const scheduled = new Set([url]);
  const visited = new Set<string>();
  const pages: (PageResult & { depth: number })[] = [];
  const skipped: { url: string; reason: string }[] = [];
  const started = Date.now();
  while (queue.length && pages.length < maxPages) {
    runtime.signal?.throwIfAborted();
    const current = queue.shift()!;
    if (visited.has(current.url)) continue;
    visited.add(current.url);
    if (policy.isAllowed(current.url, "PiWebScraper") === false) {
      skipped.push({ url: current.url, reason: "Disallowed by robots.txt" });
      continue;
    }
    if (pages.length)
      await sleep(delayMs, undefined, { signal: runtime.signal });
    runtime.onProgress?.(
      `Crawling ${pages.length + 1}/${maxPages}: ${current.url}`,
    );
    const page = await scrape(
      { ...options, url: current.url },
      { ...runtime, allowedUrl },
    );
    pages.push({ ...page, depth: current.depth });
    if (!page.ok) continue;
    visited.add(page.url);
    if (current.depth >= maxDepth) continue;
    for (const link of page.links) {
      if (
        !inScope(link) ||
        scheduled.has(link) ||
        !crawlablePath(new URL(link).pathname)
      )
        continue;
      if (scheduled.size >= maxPages * 20) break;
      scheduled.add(link);
      queue.push({ url: link, depth: current.depth + 1 });
    }
  }
  return {
    ok: pages.some((page) => page.ok),
    url,
    pages,
    skipped,
    remaining: queue.length,
    maxPages,
    maxDepth,
    pathPrefix,
    durationMs: Date.now() - started,
  };
}
