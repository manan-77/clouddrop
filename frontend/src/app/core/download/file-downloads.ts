import { DestroyRef, inject, type Signal, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize } from 'rxjs';

import { FilesApi } from '@core/api/files-api.service';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { DownloadService } from './download.service';

export const DOWNLOAD_START_FAILED = 'The download could not be started. Please try again.';

export interface FileDownloads {
  /** Ids of the files whose link is being fetched, so each button can show it is working. */
  readonly busy: Signal<readonly string[]>;
  /** The reason the last download failed, in words a person can read. */
  readonly error: Signal<string | null>;
  start(fileId: string): void;
  clearError(): void;
}

/**
 * Downloading a file the caller can read, as every screen that lists files does it: ask for a
 * short-lived link, hand it to the browser, never keep it. Call from a component's field
 * initialiser (it needs the injection context); requests end with the component.
 */
export function fileDownloads(): FileDownloads {
  const files = inject(FilesApi);
  const downloads = inject(DownloadService);
  const resolver = inject(ErrorResolver);
  const destroyRef = inject(DestroyRef);
  const busy = signal<readonly string[]>([]);
  const error = signal<string | null>(null);

  return {
    busy: busy.asReadonly(),
    error: error.asReadonly(),
    clearError: () => error.set(null),
    start(fileId: string): void {
      // A disabled button does not stop Enter or a fast double click, so the handler guards too.
      if (busy().includes(fileId)) {
        return;
      }
      error.set(null);
      busy.update((ids) => [...ids, fileId]);
      files
        .download(fileId)
        .pipe(
          finalize(() => busy.update((ids) => ids.filter((id) => id !== fileId))),
          takeUntilDestroyed(destroyRef),
        )
        .subscribe({
          next: (link) => {
            try {
              downloads.start(link.url);
            } catch {
              // The browser refused the link (not http or https): say so instead of doing nothing.
              error.set(DOWNLOAD_START_FAILED);
            }
          },
          error: (failure: unknown) => error.set(resolver.resolve(failure).message),
        });
    },
  };
}
