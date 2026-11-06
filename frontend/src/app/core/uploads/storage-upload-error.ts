/** Anything that went wrong talking to storage; the message shown is always the same safe text. */
export class StorageUploadError extends Error {}

/**
 * The server only ever hands out addresses on another origin. A same-origin address would
 * receive our bearer token from the interceptor, so it is refused.
 */
export function isExternalHttpUrl(url: string, ownOrigin: string): boolean {
  try {
    const parsed = new URL(url, ownOrigin);
    return /^https?:$/.test(parsed.protocol) && parsed.origin !== ownOrigin;
  } catch {
    return false;
  }
}
