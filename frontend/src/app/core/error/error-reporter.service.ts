import { Injectable, isDevMode } from '@angular/core';

/**
 * Sink for unexpected errors. Never pass file names, document text or tokens.
 *
 * shortcut: errors are only visible in development builds; production drops them silently.
 * Upgrade when the telemetry backend (Phase 8, feat/observability) exists - it plugs in here.
 */
@Injectable({ providedIn: 'root' })
export class ErrorReporter {
  report(error: unknown): void {
    if (isDevMode()) {
      // eslint-disable-next-line no-console -- the single sanctioned console call, dev builds only
      console.error(error);
    }
  }
}
