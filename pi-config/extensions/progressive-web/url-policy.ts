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
  const segments = url.search.slice(1).split("&");
  const kept = segments.filter((segment) => !isTrackingParameter(segment));
  if (kept.length < segments.length) url.search = kept.join("&");
  return url.href;
}

const TRACKING_PARAMETERS = new Set(["fbclid", "gclid"]);

function isTrackingParameter(segment: string): boolean {
  const rawKey = segment.split("=", 1)[0].replace(/\+/g, " ");
  let key = rawKey;
  try {
    key = decodeURIComponent(rawKey);
  } catch {}
  const name = key.toLowerCase();
  return name.startsWith("utm_") || TRACKING_PARAMETERS.has(name);
}

export function checkScope(url: string, allowedUrl?: UrlPolicy): void {
  if (allowedUrl && !allowedUrl(url)) {
    throw new NonRetryableError(
      "Redirect left the permitted crawl scope or is disallowed by robots.txt.",
    );
  }
}
