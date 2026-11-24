import { NonRetryableError } from "./errors.ts";

export const maxResponseMebibytes = 10;
export const maxResponseBytes = maxResponseMebibytes * 1024 * 1024;
const markupSniffBytes = 1024;

export function oversizeError(): NonRetryableError {
  return new NonRetryableError(
    `Response exceeds the ${maxResponseMebibytes} MiB download limit.`,
  );
}

function declaredCharset(buffer: Buffer, contentType: string | null): string {
  return (
    contentType?.match(/charset=["']?([^;\s"']+)/i)?.[1] ||
    buffer
      .subarray(0, markupSniffBytes)
      .toString("latin1")
      .match(/<meta[^>]+charset\s*=\s*["']?\s*([^\s"';/>]+)/i)?.[1] ||
    "utf-8"
  );
}

export function decodeBody(buffer: Buffer, contentType: string | null): string {
  const charset = declaredCharset(buffer, contentType);
  try {
    return new TextDecoder(charset).decode(buffer);
  } catch {
    return buffer.toString("utf8");
  }
}

export async function responseText(response: Response): Promise<string> {
  if (Number(response.headers.get("content-length")) > maxResponseBytes) {
    await response.body?.cancel();
    throw oversizeError();
  }
  if (!response.body) return "";
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maxResponseBytes) throw oversizeError();
      chunks.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  return decodeBody(
    Buffer.concat(chunks),
    response.headers.get("content-type"),
  );
}
