import { execFile } from "node:child_process";
import type { LookupAddress } from "node:dns";
import { lookup } from "node:dns/promises";
import { access } from "node:fs/promises";
import { isIP } from "node:net";
import { promisify } from "node:util";
import ipaddr from "ipaddr.js";
import { chromium, type Browser } from "playwright";
import {
  maxResponseBytes,
  decodeBody,
  oversizeError,
  responseText,
} from "./body.ts";
import { loadCredentials } from "./config.ts";
import type { PageResponse } from "./content.ts";
import {
  checkScope,
  NonRetryableError,
  normalizeUrl,
  type UrlPolicy,
} from "./url-policy.ts";

interface RequestContext {
  signal: AbortSignal;
  allowedUrl?: UrlPolicy;
}

export interface TransportOptions extends RequestContext {
  timeoutMs: number;
  waitForSelector?: string;
}

export type PageTransport = (
  url: string,
  options: TransportOptions,
) => Promise<PageResponse>;
export const crawlerAgentName = "PiWebScraper";
const userAgent =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/159.0.0.0 Safari/537.36";
const redirectStatuses = new Set([301, 302, 303, 307, 308]);
const activeBrowsers = new Set<Browser>();
const executeFile = promisify(execFile);
const browserHeaders = {
  Accept:
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.9",
  DNT: "1",
  "Upgrade-Insecure-Requests": "1",
  "Sec-Fetch-Dest": "document",
  "Sec-Fetch-Mode": "navigate",
  "Sec-Fetch-Site": "none",
  "Sec-Fetch-User": "?1",
  "Cache-Control": "max-age=0",
};

export async function browserInstalled(): Promise<boolean> {
  return access(chromium.executablePath()).then(
    () => true,
    () => false,
  );
}

export async function curlInstalled(): Promise<boolean> {
  return executeFile("curl", ["--version"]).then(
    () => true,
    () => false,
  );
}

export async function closeBrowsers(): Promise<void> {
  await Promise.allSettled(
    [...activeBrowsers].map((browser) => browser.close()),
  );
  activeBrowsers.clear();
}

async function readResponse(
  response: Response,
  url: string,
  defaultContentType = "",
): Promise<PageResponse> {
  const location = response.headers.get("location");
  const redirectUrl =
    redirectStatuses.has(response.status) && location ? location : undefined;
  if (redirectUrl) await response.body?.cancel();
  return {
    status: response.status,
    url,
    contentType: response.headers.get("content-type") || defaultContentType,
    body: redirectUrl ? "" : await responseText(response),
    redirectUrl,
  };
}

async function followRedirects(
  url: string,
  context: RequestContext,
  request: (url: string) => Promise<PageResponse>,
): Promise<PageResponse> {
  for (let redirects = 0; redirects <= 10; redirects++) {
    context.signal.throwIfAborted();
    checkScope(url, context.allowedUrl);
    const response = await request(url);
    if (!response.redirectUrl) return response;
    url = normalizeUrl(response.redirectUrl, url);
  }
  throw new NonRetryableError("Too many redirects.");
}

export async function httpFetch(
  url: string,
  context: RequestContext,
): Promise<PageResponse> {
  return followRedirects(url, context, async (target) => {
    const response = await fetch(target, {
      signal: context.signal,
      redirect: "manual",
      headers: {
        "User-Agent": `${crawlerAgentName}/1.0`,
        Accept: "text/html,text/plain,application/json;q=0.9,*/*;q=0.5",
      },
    });
    return readResponse(response, normalizeUrl(response.url));
  });
}

interface CurlMetadata {
  http_code: number;
  redirect_url?: string;
  url_effective: string;
  content_type: string;
}

const curlFileSizeExceededExitCode = 63;

export async function curlFetch(
  url: string,
  options: TransportOptions,
): Promise<PageResponse> {
  const { signal, timeoutMs } = options;
  const marker = Buffer.from("\n__PI_WEB_RESPONSE__");
  return followRedirects(url, options, async (target) => {
    let output: Buffer;
    try {
      const { stdout } = await executeFile(
        "curl",
        [
          "--disable",
          "--silent",
          "--show-error",
          "--compressed",
          "--proto",
          "=http,https",
          "--connect-timeout",
          "10",
          "--max-time",
          String(timeoutMs / 1000),
          "--max-filesize",
          String(maxResponseBytes),
          "--user-agent",
          userAgent,
          ...Object.entries(browserHeaders).flatMap(([name, value]) => [
            "--header",
            `${name}: ${value}`,
          ]),
          "--write-out",
          `${marker.toString()}%{json}`,
          "--url",
          target,
        ],
        {
          signal,
          killSignal: "SIGKILL",
          maxBuffer: maxResponseBytes + 8192,
          encoding: "buffer",
        },
      );
      output = stdout;
    } catch (error) {
      signal.throwIfAborted();
      if (!(error instanceof Error)) throw error;
      if (
        "code" in error &&
        (error.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER" ||
          error.code === curlFileSizeExceededExitCode)
      ) {
        throw oversizeError();
      }
      const message = "stderr" in error ? String(error.stderr) : error.message;
      throw new Error(`cURL failed: ${message.trim().slice(-2000)}`);
    }
    const split = output.lastIndexOf(marker);
    if (split < 0) throw new Error("cURL did not return response metadata.");
    const meta: CurlMetadata = JSON.parse(
      output.subarray(split + marker.length).toString("utf8"),
    );
    return {
      status: meta.http_code,
      url: normalizeUrl(meta.url_effective),
      contentType: meta.content_type || "",
      body: decodeBody(output.subarray(0, split), meta.content_type || ""),
      redirectUrl: redirectStatuses.has(meta.http_code)
        ? meta.redirect_url
        : undefined,
    };
  });
}

export async function browserFetch(
  url: string,
  options: TransportOptions,
): Promise<PageResponse> {
  const { signal, timeoutMs, waitForSelector, allowedUrl } = options;
  signal.throwIfAborted();
  const started = Date.now();
  const browser = await chromium.launch({
    headless: true,
    timeout: Math.min(timeoutMs, 15000),
  });
  activeBrowsers.add(browser);
  const abort = () => {
    void browser.close().catch(() => {});
  };
  signal.addEventListener("abort", abort, { once: true });
  try {
    signal.throwIfAborted();
    const context = await browser.newContext({
      userAgent,
      locale: "en-US",
      acceptDownloads: false,
      serviceWorkers: "block",
    });
    let scopeError: unknown;
    await context.route("**/*", (route) => {
      const request = route.request();
      if (request.isNavigationRequest() && !request.frame().parentFrame()) {
        try {
          checkScope(normalizeUrl(request.url()), allowedUrl);
        } catch (error) {
          scopeError = error;
          return route.abort();
        }
      }
      return ["image", "font", "media"].includes(request.resourceType())
        ? route.abort()
        : route.continue();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(Math.min(timeoutMs, 10000));
    const response = await page
      .goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs })
      .catch((error: unknown) => {
        throw scopeError || error;
      });
    checkScope(normalizeUrl(page.url()), allowedUrl);
    if (!response)
      throw new Error("Browser navigation returned no HTTP response.");
    if (waitForSelector)
      await page.waitForSelector(waitForSelector, {
        state: "attached",
        timeout: Math.max(1, timeoutMs - (Date.now() - started)),
      });
    else {
      await page
        .waitForLoadState("networkidle", { timeout: Math.min(timeoutMs, 5000) })
        .catch(() => {});
      await page.waitForTimeout(1000);
    }
    signal.throwIfAborted();
    const body = await page.content();
    if (Buffer.byteLength(body) > maxResponseBytes)
      throw new NonRetryableError("Rendered page exceeds the 10 MiB limit.");
    return {
      status: response.status(),
      url: normalizeUrl(page.url()),
      contentType: "text/html",
      body,
    };
  } finally {
    signal.removeEventListener("abort", abort);
    await browser.close().catch(() => {});
    activeBrowsers.delete(browser);
  }
}

async function assertPublicUrl(
  url: string,
  signal: AbortSignal,
): Promise<void> {
  const host = new URL(url).hostname.replace(/^\[|\]$/g, "");
  signal.throwIfAborted();
  let records: LookupAddress[];
  let abort: (() => void) | undefined;
  try {
    records = isIP(host)
      ? [{ address: host, family: isIP(host) }]
      : await Promise.race([
          lookup(host, { all: true }),
          new Promise<LookupAddress[]>((_, reject) => {
            abort = () => reject(signal.reason);
            signal.addEventListener("abort", abort, { once: true });
          }),
        ]);
  } finally {
    if (abort) signal.removeEventListener("abort", abort);
  }
  if (
    !records.length ||
    records.some(({ address }) => ipaddr.process(address).range() !== "unicast")
  ) {
    throw new NonRetryableError(
      "Private or local URLs are never sent to Bright Data. Use maxTier: 3 for local sites.",
    );
  }
}

export async function brightDataFetch(
  url: string,
  { signal }: TransportOptions,
): Promise<PageResponse> {
  const { token, zone } = await loadCredentials();
  if (!token || !zone)
    throw new Error(
      "Bright Data is not configured. Set BRIGHT_DATA_API_TOKEN and BRIGHT_DATA_ZONE, or run the scraper CLI configure command.",
    );
  await assertPublicUrl(url, signal);
  const response = await fetch("https://api.brightdata.com/request", {
    method: "POST",
    signal,
    redirect: "error",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ zone, url, format: "raw" }),
  });
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error(
      `Bright Data returned HTTP ${response.status}. Check your API token, Web Unlocker zone, balance, and account permissions.`,
    );
  }
  const unlockError = response.headers.get("x-brd-error");
  if (unlockError) {
    await response.body?.cancel();
    throw new Error(
      `Bright Data could not unlock the page: ${unlockError.slice(0, 200)}`,
    );
  }
  const page = await readResponse(response, url, "text/html");
  const targetStatus = Number.parseInt(
    response.headers.get("x-brd-status-code") ?? "",
    10,
  );
  return Number.isNaN(targetStatus) ? page : { ...page, status: targetStatus };
}
