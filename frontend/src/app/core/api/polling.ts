/** Waits before each refresh of something that is still being worked on in the background: quick
 * at first, then longer, so a slow job costs few requests. One schedule for every screen. */
export const POLL_DELAYS_MS: readonly number[] = [2000, 3000, 5000, 8000, 10000];

/** About ten minutes of refreshing; after that it waits for the next real reload. */
export const MAX_POLLS = 60;

/** The wait before refresh number `polls` (0 is the first), or null once it should stop. */
export function pollDelayMs(polls: number): number | null {
  return polls >= MAX_POLLS ? null : POLL_DELAYS_MS[Math.min(polls, POLL_DELAYS_MS.length - 1)];
}
