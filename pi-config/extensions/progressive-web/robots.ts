import robotsParser from "robots-parser";
import { deadlineSignal } from "./deadline.ts";
import { httpFetch } from "./transports.ts";

const robotsTimeoutMs = 15000;

async function fetchPolicy(origin: string, signal: AbortSignal) {
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

export async function crawlPolicy(origin: string, caller?: AbortSignal) {
  const { deadline, signal } = deadlineSignal(robotsTimeoutMs, caller);
  return fetchPolicy(origin, signal).catch((error: unknown) => {
    caller?.throwIfAborted();
    if (deadline.aborted)
      throw new Error(`robots.txt timed out after ${robotsTimeoutMs} ms.`);
    throw error;
  });
}
