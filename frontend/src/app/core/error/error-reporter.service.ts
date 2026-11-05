import { Injectable, isDevMode } from '@angular/core';

/**
 * Sink for unexpected errors. A telemetry backend plugs in here later; until then errors are only
 * visible in development builds. Never pass file names, document text or tokens.
 */
@Injectable({ providedIn: 'root' })
export class ErrorReporter {
  report(error: unknown): void {
    if (isDevMode()) {
      // eslint-disable-next-line no-console
      console.error(error);
    }
  }
}
