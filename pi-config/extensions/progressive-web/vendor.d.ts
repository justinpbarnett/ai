// The package's bundled declarations misrepresent its CommonJS function under NodeNext.
declare module "robots-parser" {
  interface Robot {
    isAllowed(url: string, userAgent?: string): boolean | undefined;
    isDisallowed(url: string, userAgent?: string): boolean | undefined;
    getMatchingLineNumber(url: string, userAgent?: string): number;
    getCrawlDelay(userAgent?: string): number | undefined;
    getSitemaps(): string[];
    getPreferredHost(): string | null;
  }
  export default function robotsParser(url: string, text: string): Robot;
}

declare module "turndown-plugin-gfm" {
  import type TurndownService from "turndown";
  export const gfm: TurndownService.Plugin;
}
