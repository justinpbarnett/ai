import { isProbablyReaderable, Readability } from "@mozilla/readability";
import { JSDOM, VirtualConsole } from "jsdom";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";
import type { PageResponse } from "./transports.ts";
import { NonRetryableError, normalizeUrl } from "./url-policy.ts";

export interface PageContent {
  title: string;
  markdown: string;
  links: string[];
  excerpt: string;
}

const markdown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  bulletListMarker: "-",
});
markdown.use(gfm);
markdown.remove((node) =>
  /^(script|style|noscript|iframe|svg|canvas)$/i.test(node.nodeName),
);

function checkDocument(document: Document): void {
  const title = document.title.trim();
  const sample =
    `${title}\n${document.body?.textContent?.slice(0, 3000) || ""}`.replace(
      /\s+/g,
      " ",
    );
  if (
    /^(just a moment|attention required|access denied|verify you are human|security check|robot or human|captcha)\b/i.test(
      title,
    ) ||
    (sample.length < 3000 &&
      /checking (?:your )?browser|verify (?:that )?you (?:are|['’]re) human|enable javascript and cookies to continue|performing security verification/i.test(
        sample,
      ))
  ) {
    throw new Error("Received an anti-bot challenge instead of page content.");
  }
  if (
    document.querySelector('input[type="password"]') &&
    (sample.length < 1500 ||
      /^(?:log ?in|sign ?in|authentication required)\b/i.test(title))
  ) {
    throw new NonRetryableError(
      "This page requires authentication; only public content is supported.",
    );
  }
}

function pageForbidsFollowing(document: Document): boolean {
  return [
    ...document.querySelectorAll<HTMLMetaElement>('meta[name="robots" i]'),
  ].some((meta) =>
    meta.content
      .toLowerCase()
      .split(/[\s,]+/)
      .some((token) => token === "nofollow" || token === "none"),
  );
}

function collectLinks(document: Document, url: string): string[] {
  if (pageForbidsFollowing(document)) return [];
  const links = new Set<string>();
  for (const anchor of document.querySelectorAll<HTMLAnchorElement>(
    "a[href]",
  )) {
    if (anchor.rel.toLowerCase().split(/\s+/).includes("nofollow")) continue;
    try {
      links.add(normalizeUrl(anchor.href, url));
    } catch {}
    if (links.size >= 500) break;
  }
  return [...links];
}

function resolveContentUrls(root: HTMLElement, url: string): void {
  for (const anchor of root.querySelectorAll("a[href]")) {
    try {
      const target = new URL(anchor.getAttribute("href")!, url);
      anchor.setAttribute("href", normalizeUrl(target.href) + target.hash);
    } catch {
      anchor.removeAttribute("href");
    }
  }
  for (const image of root.querySelectorAll("img[src]")) {
    try {
      image.setAttribute("src", new URL(image.getAttribute("src")!, url).href);
    } catch {
      image.remove();
    }
  }
}

function removeSideForms(document: Document): void {
  const bodyLength = document.body.textContent.length;
  for (const form of document.querySelectorAll("form")) {
    if (form.textContent.length < bodyLength * 0.8) form.remove();
  }
}

function rejectUnusableResponse({ body, status }: PageResponse): string {
  if ([401, 404, 410, 451].includes(status)) {
    throw new NonRetryableError(
      `HTTP ${status}: content is missing, restricted, or requires authentication.`,
    );
  }
  if (status < 200 || status >= 300) throw new Error(`HTTP ${status}`);
  const trimmed = body.trim();
  if (!trimmed)
    throw new Error("Empty response; the page may require JavaScript.");
  return trimmed;
}

function isHtmlResponse({ body, contentType }: PageResponse): boolean {
  return (
    /html/i.test(contentType) ||
    /^\s*(?:<!doctype html|<html|<head|<body)/i.test(body)
  );
}

function extractPlainTextPage(
  { url, contentType }: PageResponse,
  trimmed: string,
): PageContent {
  if (!/text\/|json|xml|javascript|markdown|csv/i.test(contentType)) {
    throw new NonRetryableError(
      `Unsupported content type: ${contentType || "unknown"}. This tool extracts web pages, not binary files.`,
    );
  }
  return {
    title: url,
    markdown: trimmed,
    links: [],
    excerpt: trimmed.slice(0, 300),
  };
}

export function extractPage(response: PageResponse): PageContent {
  const { body, url } = response;
  const trimmed = rejectUnusableResponse(response);
  if (!isHtmlResponse(response)) return extractPlainTextPage(response, trimmed);

  const dom = new JSDOM(body, { url, virtualConsole: new VirtualConsole() });
  try {
    const document = dom.window.document;
    checkDocument(document);
    const title = (
      document.querySelector<HTMLMetaElement>('meta[property="og:title"]')
        ?.content ||
      document.title ||
      url
    )
      .trim()
      .slice(0, 1024);
    const links = collectLinks(document, url);
    for (const node of document.querySelectorAll(
      "nav,footer,header,aside,script,style,noscript,[hidden],[aria-hidden='true']",
    ))
      node.remove();
    removeSideForms(document);
    const main = document.querySelector<HTMLElement>(
      "main,[role='main'],article",
    );
    const article =
      !main && isProbablyReaderable(document)
        ? new Readability(document.cloneNode(true) as Document, {
            charThreshold: 100,
          }).parse()
        : null;
    const root = main || document.body;
    if (article?.content) root.innerHTML = article.content;
    resolveContentUrls(root, url);
    const text = root.textContent.replace(/\s+/g, " ").trim();
    if (text.length < 80)
      throw new Error(
        "Too little readable content; the page may be a JavaScript shell or an interstitial.",
      );
    return {
      title,
      markdown: markdown.turndown(root.innerHTML).trim(),
      links,
      excerpt: article?.excerpt || text.slice(0, 300),
    };
  } finally {
    dom.window.close();
  }
}
