#!/usr/bin/env node
import { parseArgs } from "node:util";
import { configure, configureBrave } from "./config.ts";
import {
  crawl,
  crawlLimits,
  dispose,
  MAX_SCRAPE_URLS,
  scrapeBatch,
  scrapeTimeoutLimits,
  status,
} from "./core.ts";
import { formatResults, hasFailures, saveDocument } from "./results.ts";
import { search, searchLimits, searchStatus } from "./search.ts";

const help = `Pi web search and progressive scraper

Usage:
  node cli.mjs search "YOUR QUERY" [--count 5] [--freshness pw] [--json]
  node cli.mjs scrape URL [URL...] [--start-tier 1] [--max-tier 4] [--json]
  node cli.mjs crawl URL [--max-pages 10] [--max-depth 2] [--path-prefix /docs/]
  node cli.mjs status
  pbpaste | node cli.mjs configure --zone YOUR_WEB_UNLOCKER_ZONE
  pbpaste | node cli.mjs configure-brave

Search options:
  --count N         Maximum results, ${searchLimits.count.minimum}-${searchLimits.count.maximum} (default ${searchLimits.count.fallback})
  --offset N        Zero-based result page, ${searchLimits.offset.minimum}-${searchLimits.offset.maximum} (default ${searchLimits.offset.fallback})
  --freshness F     pd, pw, pm, py, or YYYY-MM-DDtoYYYY-MM-DD
  --country CC      Brave-supported country code, e.g. US or GB
  --language CODE   Brave-supported search language, e.g. en or zh-hans
  --safe-search S   off, moderate (default), or strict
  --timeout N       Search timeout in milliseconds (default ${searchLimits.timeoutMs.fallback})
  --                Put it before a query that starts with a dash: search -- "-spam site:example.com"

Scrape/crawl options:
  --start-tier N    Start at tier 1, 2, 3, or 4
  --max-tier N      Highest permitted tier (3 prevents paid requests)
  --timeout N       Per-tier timeout in milliseconds (default ${scrapeTimeoutLimits.fallback}; tier 4 at least 60000)
  --wait-for CSS    Wait for a CSS selector; starts at browser tier 3 by default
  --fresh           Bypass the 15-minute scrape cache (crawls never use it)
  --max-pages N     Crawl page attempt limit, ${crawlLimits.maxPages.minimum}-${crawlLimits.maxPages.maximum} (default ${crawlLimits.maxPages.fallback})
  --max-depth N     Crawl depth, ${crawlLimits.maxDepth.minimum}-${crawlLimits.maxDepth.maximum} (default ${crawlLimits.maxDepth.fallback})
  --path-prefix P   Only crawl paths beginning with P (default /)
  --delay N         Crawl delay in milliseconds, at least ${crawlLimits.delayMs.minimum} (default ${crawlLimits.delayMs.fallback})
  --json            Print complete structured results instead of Markdown

Tiers: HTTP + Readability -> cURL + browser headers -> Playwright -> Bright Data.
Crawls stay on the starting origin and respect robots.txt and nofollow.
Bright Data requires a token and Web Unlocker zone; the first three tiers do not.
Search requires a separate Brave Search API key and can incur API charges.
Search discovers URLs; use scrape to read their full content.
Credentials stay outside source control, with owner-only permissions.
`;

const stringOption = Object.freeze({ type: "string" });
const booleanOption = Object.freeze({ type: "boolean" });
const scrapeOptions = {
  json: booleanOption,
  fresh: booleanOption,
  "start-tier": stringOption,
  "max-tier": stringOption,
  timeout: stringOption,
  "wait-for": stringOption,
};
const commandOptions = {
  search: {
    json: booleanOption,
    count: stringOption,
    offset: stringOption,
    timeout: stringOption,
    freshness: stringOption,
    country: stringOption,
    language: stringOption,
    "safe-search": stringOption,
  },
  scrape: scrapeOptions,
  crawl: {
    ...scrapeOptions,
    "max-pages": stringOption,
    "max-depth": stringOption,
    "path-prefix": stringOption,
    delay: stringOption,
  },
  status: { json: booleanOption },
  configure: { zone: stringOption },
  "configure-brave": {},
};

/**
 * @param {string} kind
 * @param {import("./results.ts").WebResult} result
 * @param {boolean | undefined} json
 */
async function printResults(kind, result, json) {
  const { markdown } = formatResults(result);
  const paths = await saveDocument(kind, result, markdown);
  console.error(
    `Full Markdown: ${paths.markdownPath}\nStructured results: ${paths.jsonPath}`,
  );
  console.log(
    json ? JSON.stringify({ ...result, ...paths }, null, 2) : markdown,
  );
  if (hasFailures(result)) process.exitCode = 1;
}

const controller = new AbortController();
process.once("SIGINT", () => controller.abort(new Error("Cancelled.")));
process.once("SIGTERM", () => controller.abort(new Error("Cancelled.")));

try {
  const { values, positionals } = parseArgs({
    args: process.argv.slice(2),
    allowPositionals: true,
    options: {
      help: { type: "boolean", short: "h" },
      ...commandOptions.search,
      ...commandOptions.crawl,
      ...commandOptions.configure,
    },
  });
  const [command, ...args] = positionals;
  const allowedOptions = new Map(Object.entries(commandOptions)).get(command);
  if (!values.help && allowedOptions) {
    const unsupported = Object.keys(values).find(
      (name) => !Object.hasOwn(allowedOptions, name),
    );
    if (unsupported)
      throw new Error(
        `--${unsupported} is not supported by ${command}. Run with --help.`,
      );
  }
  /** @param {keyof typeof values} key */
  const numeric = (key) =>
    values[key] === undefined ? undefined : Number(values[key]);
  if (values.help || !command) {
    console.log(help);
  } else if (command === "configure" || command === "configure-brave") {
    if (args.length)
      throw new Error("Supply the token on stdin, never as an argument.");
    if (process.stdin.isTTY)
      throw new Error(
        command === "configure-brave"
          ? "Copy your key, then run: pbpaste | node cli.mjs configure-brave"
          : "Copy your token, then run: pbpaste | node cli.mjs configure --zone YOUR_WEB_UNLOCKER_ZONE",
      );
    let token = "";
    for await (const chunk of process.stdin) {
      token += chunk.toString();
      if (token.length > 8192)
        throw new Error("Input is too large to be an API token.");
    }
    console.log(
      command === "configure-brave"
        ? await configureBrave(token.trim())
        : await configure(token.trim(), values.zone),
    );
  } else if (command === "status") {
    if (args.length)
      throw new Error("status does not take positional arguments.");
    const result = { ...(await searchStatus()), ...(await status()) };
    console.log(
      values.json
        ? JSON.stringify(result, null, 2)
        : [
            result.search,
            ...result.tiers,
            `Brave credentials: ${result.braveCredentialsPath}`,
            `Bright Data credentials: ${result.credentialsPath}`,
          ].join("\n"),
    );
  } else if (command === "search") {
    console.error("Searching Brave...");
    const result = await search(
      {
        query: args.join(" "),
        count: numeric("count"),
        offset: numeric("offset"),
        timeoutMs: numeric("timeout"),
        freshness: values.freshness,
        country: values.country,
        searchLang: values.language,
        safeSearch: values["safe-search"],
      },
      { signal: controller.signal },
    );
    await printResults("search", result, values.json);
  } else if (["scrape", "crawl"].includes(command)) {
    if (
      !args.length ||
      args.length > MAX_SCRAPE_URLS ||
      (command === "crawl" && args.length !== 1)
    ) {
      throw new Error(
        command === "crawl"
          ? "Crawl requires exactly one starting URL."
          : `Scrape requires 1-${MAX_SCRAPE_URLS} URLs.`,
      );
    }
    const options = {
      startTier: numeric("start-tier"),
      maxTier: numeric("max-tier"),
      timeoutMs: numeric("timeout"),
      fresh: values.fresh,
      waitForSelector: values["wait-for"],
    };
    /** @type {import("./core.ts").ScrapeRuntime} */
    const runtime = {
      signal: controller.signal,
      onProgress: (message) => console.error(message),
    };
    /** @type {import("./results.ts").WebResult} */
    let result;
    if (command === "crawl") {
      result = await crawl(
        {
          ...options,
          url: args[0],
          maxPages: numeric("max-pages"),
          maxDepth: numeric("max-depth"),
          pathPrefix: values["path-prefix"],
          delayMs: numeric("delay"),
        },
        runtime,
      );
    } else {
      result = await scrapeBatch({ ...options, urls: args }, runtime);
    }
    await printResults(command, result, values.json);
  } else {
    throw new Error(`Unknown command: ${command}. Run with --help.`);
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = controller.signal.aborted ? 130 : 1;
} finally {
  await dispose();
}
