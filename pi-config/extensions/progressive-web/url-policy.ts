export type UrlPolicy = (url: string) => boolean;
export class NonRetryableError extends Error {}

export function normalizeUrl(value: string, base?: string): string {
  const url = new URL(value, base);
  if (url.href.length > 8192)
    throw new NonRetryableError("URL exceeds the 8192-character limit.");
  if (!["http:", "https:"].includes(url.protocol))
    throw new NonRetryableError("Only HTTP and HTTPS URLs are supported.");
  if (url.username || url.password)
    throw new NonRetryableError(
      "URLs containing credentials are not supported.",
    );
  url.hash = "";
  for (const key of [...url.searchParams.keys()]) {
    if (/^utm_/i.test(key) || ["fbclid", "gclid"].includes(key))
      url.searchParams.delete(key);
  }
  return url.href;
}

export function checkScope(url: string, allowedUrl?: UrlPolicy): void {
  if (allowedUrl && !allowedUrl(url)) {
    throw new NonRetryableError(
      "Redirect left the permitted crawl scope or is disallowed by robots.txt.",
    );
  }
}
