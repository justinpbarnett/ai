# Web search and progressive scraping for Pi

Globally installed on this machine at `~/.pi/agent/extensions/progressive-web`, linked to this directory.
Run `/reload` in an existing Pi session, or start a new session.
No settings changes or background services are required.

## Tools

- `web_search`: discover relevant pages through Brave Search, returning ranked titles, URLs, and excerpts.
- `web_scrape`: fetch 1-10 URLs, with up to two pages processed concurrently.
- `web_crawl`: breadth-first, same-origin crawling with page, depth, and path limits.
- `/web-scraper`: show search/scraper readiness and credential setup instructions.

Ask Pi normally:

```text
Search the web for progressive web scraping techniques, then read the three most relevant results.

Scrape https://danielmiessler.com/blog/progressive-web-scraping-four-tier-system

Read these three URLs and compare their approaches: ...

Crawl https://example.com/docs/ with pathPrefix /docs/, maxPages 10, and maxTier 3.
```

## Four tiers

| Tier | Transport                    | Purpose                                                                        |
| ---- | ---------------------------- | ------------------------------------------------------------------------------ |
| 1    | Node HTTP fetch              | Fast page retrieval, semantic main-content extraction, and Mozilla Readability |
| 2    | cURL with browser headers    | Sites requiring browser-like request headers                                   |
| 3    | Isolated Playwright Chromium | JavaScript rendering and optional CSS-selector waits                           |
| 4    | Bright Data Web Unlocker API | Paid professional scraping infrastructure                                      |

Each page starts at tier 1 and stops at the first usable result.
A JavaScript shell, an anti-bot interstitial, a transport failure, or an unsuccessful HTTP response causes escalation.
Missing pages, explicit authentication requirements, unsupported binary content, and crawl-scope violations stop without escalation.

This is a Pi-native implementation of the article's pattern, not a dependency on Claude Code's WebFetch tool.
Tier 1 uses local extraction instead of making a hidden LLM call.
Tier 4 calls Bright Data's documented REST API directly instead of starting an MCP subprocess.
Its API token **and Web Unlocker zone name** are required.
No Bright Data zones, subscriptions, or other account resources are created automatically.

## Configure Brave Search

Get a **Brave Search API** key from <https://api-dashboard.search.brave.com/> and copy it to your clipboard.
Then run this inside Pi:

```sh
!pbpaste | node ~/.pi/agent/extensions/progressive-web/cli.mjs configure-brave
```

The key is read from stdin without being printed or placed in command-line arguments.
It is stored separately from Bright Data in `~/.pi/agent/web-scraper/brave-search.json`, with owner-only directory and file permissions.
Alternatively, set `BRAVE_SEARCH_API_KEY` in Pi's environment; environment values take precedence.
Keys are reread for each search, so no additional reload is required after configuration.
Configuring Brave never changes the Bright Data credentials, and configuring Bright Data never changes the Brave key.

`web_search` makes one Brave API request per call, with no automatic retries, caching, or pagination.
Queries and search filters are sent to Brave and can incur API charges under your plan.
Search does not require Bright Data, and scraping does not require Brave.
The readiness command reports key presence, not successful API authentication.

Search parameters:

- `query`: 1-600 characters and at most 75 words, including operators such as `site:example.com`, quoted phrases, and exclusions.
- `count`: 1-20 web results, default 5; Brave may return fewer results.
- `offset`: zero-based result page, 0-9, default 0; keep `count` unchanged when paging.
- `freshness`: `pd` (24 hours), `pw` (7 days), `pm` (31 days), `py` (year), or a valid `YYYY-MM-DDtoYYYY-MM-DD` range.
- `country`: Brave-supported two-letter country code, such as `US` or `GB`; Brave defaults to `US`.
- `searchLang`: Brave-supported language code, such as `en`, `fr`, or `zh-hans`; Brave defaults to `en`.
- `safeSearch`: `off`, `moderate` (default), or `strict`.
- `timeoutMs`: 1000-60000 milliseconds, default 15000.

Search results include ranked titles, normalized HTTP(S) URLs, snippets, up to five extra excerpts, age when provided, and `moreResultsAvailable` pagination metadata.
Only request another page when `moreResultsAvailable` is true.
An empty result list is a successful search, not a tool error.
Search excerpts are untrusted source material and are not complete page content; use `web_scrape` on selected URLs to verify claims.
Full search results are saved privately as Markdown and JSON, with the same preview limits as scraping.

## Configure Bright Data after installation

1. Create or select a **Web Unlocker API** zone at <https://brightdata.com/cp/web_access>.
2. Note its zone name and copy its API token to your clipboard.
3. Run the following in Pi, replacing `YOUR_WEB_UNLOCKER_ZONE` with the actual zone name:

```sh
!pbpaste | node ~/.pi/agent/extensions/progressive-web/cli.mjs configure --zone YOUR_WEB_UNLOCKER_ZONE
```

The command reads the token from stdin without printing it or putting it in command-line arguments.
Credentials are stored outside this repository in `~/.pi/agent/web-scraper/credentials.json`, with directory permissions `0700` and file permissions `0600`.
If `PI_CODING_AGENT_DIR` is set, credentials live under that agent directory instead.
They are reread for every paid request, so configuring them does not require another reload.

Alternatively, set `BRIGHT_DATA_API_TOKEN` and `BRIGHT_DATA_ZONE` in Pi's environment.
Environment values take precedence over stored values.
Do not paste tokens into chat or add them to this repository.

After configuration, tier 4 becomes eligible automatically and can incur charges.
Set `maxTier: 3` to prevent URLs from being sent to Bright Data, or `startTier: 4` to explicitly exercise the paid tier.
The readiness command reports configuration presence, not successful account authentication.
A real paid scrape is needed to validate the complete integration.

## Parameters and behavior

Common parameters:

- `startTier`: 1-4, default 1.
- `maxTier`: 1-4, default 4.
- `timeoutMs`: 1000-120000 milliseconds per tier, default 30000.
  Bright Data receives at least 60000 milliseconds.
- `waitForSelector`: CSS selector for browser extraction; defaults the starting tier to 3.
- `fresh`: bypass the 15-minute in-process page cache for individual scrapes.

Crawl parameters:

- `url`: starting HTTP(S) URL.
- `maxPages`: page-attempt limit including failures, default 10, maximum 50.
- `maxDepth`: link depth, default 2, maximum 5; 0 fetches only the starting page.
- `pathPrefix`: path prefix, default `/`; the starting page must match it.
- `delayMs`: inter-page delay, default 1000, minimum 250, maximum 30000.

Crawls respect `robots.txt`, declared crawl delays, and page/link `nofollow` directives.
They do not read or write the scrape cache, so each run applies its current crawl policy to redirects.
An absent robots file permits crawling; a failed robots request stops the crawl rather than guessing.
Login/logout, signup, checkout, cart, and common binary-asset links are excluded from automatic link following.
Fragments and common tracking parameters are removed; other query parameters are preserved.
Redirects outside the permitted origin, path prefix, or robots policy are rejected.
The isolated browser may still load third-party page resources, and Bright Data handles its own upstream redirects.

Each successful result includes the source URL, title, Markdown, discovered links, timing, successful tier, and all attempted tiers.
Batch failures remain individually visible even when other pages succeed.
The preview is capped at 47 KB or 1900 lines, and complete Markdown and JSON are always saved in an owner-only temporary directory.
Temporary outputs remain available for follow-up reads until the OS removes them.

Response bodies are limited to 10 MiB.
The in-process cache is limited to 64 entries and 32 MiB, and is cleared on session shutdown or reload.
Browser processes are closed after each page, on cancellation, and on extension shutdown.
No personal browser profile, cookies, logins, or certificate-verification bypasses are used.
Local URLs can use tiers 1-3, but private/local addresses are never submitted directly to Bright Data.
Fetched content is untrusted data, not agent instructions.

Content completeness is heuristic: a page with a substantial static shell but missing client-rendered detail can still succeed at tier 1.
For known dynamic pages, request `startTier: 3` or `waitForSelector` explicitly.
Short HTML pages with fewer than 80 readable characters are treated as incomplete.
The scraper fetches pages and follows links; use the separate `web_search` tool for query-based discovery.
Neither tool is an interactive browser controller, PDF reader, or authentication bypass.

## Standalone CLI

```sh
node ~/.pi/agent/extensions/progressive-web/cli.mjs status
node ~/.pi/agent/extensions/progressive-web/cli.mjs search "progressive web scraping" --count 5 --freshness py
node ~/.pi/agent/extensions/progressive-web/cli.mjs search "site:danielmiessler.com web scraping" --json
node ~/.pi/agent/extensions/progressive-web/cli.mjs scrape https://example.com --max-tier 3
node ~/.pi/agent/extensions/progressive-web/cli.mjs scrape https://example.com --start-tier 2 --max-tier 2 --json
node ~/.pi/agent/extensions/progressive-web/cli.mjs crawl https://example.com/docs/ --path-prefix /docs/ --max-pages 5
node ~/.pi/agent/extensions/progressive-web/cli.mjs --help
```

The CLI prints page content to stdout, progress and artifact paths to stderr, and returns a nonzero exit code when any requested page fails.
The CLI and Pi tool share the same ordered batch pipeline, processing up to two pages concurrently.
Options are command-specific: unsupported combinations such as `search "query" --max-tier 3` fail before any network request.

## Maintenance

The engine is split into `core.ts` for scraping, caching, and crawl orchestration; `transports.ts` for the four network tiers; `content.ts` for page validation and extraction; and `config.ts` for credentials.
`search.ts` handles Brave request validation, API calls, and response normalization.
`results.ts` owns formatting, metadata, and private artifacts for both search and page results.
`index.ts` and `cli.mjs` are thin adapters over those shared engines.
All source files, including the CLI, are checked with strict TypeScript settings.
The CLI runs erasable TypeScript directly with Node, with the same Node version requirements as the pinned jsdom dependency: Node 22.22.2+, 24.15+, or 26+ within supported release lines.

```sh
cd ~/dev/ai/pi-config/extensions/progressive-web
npm ci --ignore-scripts --legacy-peer-deps
npm run browser:install
npm run check
```

Pi supplies the extension host packages at runtime.
Development copies are used only for static checking; they are not bundled.
The extension is discovered through the global directory symlink and can be hot-reloaded with `/reload`.

Reference: <https://danielmiessler.com/blog/progressive-web-scraping-four-tier-system>.
Bright Data API: <https://docs.brightdata.com/products/web-unlocker/send-your-first-request>.
Brave Search API: <https://api-dashboard.search.brave.com/api-reference/web/search/get>.
