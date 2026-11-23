import { NonRetryableError } from "./url-policy.ts";

export const maxResponseBytes = 10 * 1024 * 1024;

export function deadlineSignal(timeoutMs: number, caller?: AbortSignal) {
  const deadline = AbortSignal.timeout(timeoutMs);
  return {
    deadline,
    signal: caller ? AbortSignal.any([caller, deadline]) : deadline,
  };
}

export function oversizeError(): NonRetryableError {
  return new NonRetryableError("Response exceeds the 10 MiB download limit.");
}

export function decodeBody(buffer: Buffer, contentType: string | null): string {
  const charset =
    contentType?.match(/charset=["']?([^;\s"']+)/i)?.[1] || "utf-8";
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
