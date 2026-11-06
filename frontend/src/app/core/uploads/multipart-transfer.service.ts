import { DOCUMENT } from '@angular/common';
import { HttpClient, HttpErrorResponse, HttpEventType } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import {
  catchError,
  defer,
  filter,
  from,
  ignoreElements,
  map,
  mergeMap,
  retry,
  switchMap,
  tap,
  throwError,
  timer,
  type Observable,
} from 'rxjs';

import { type MultipartInstructions } from '@core/api/models';
import { isExternalHttpUrl, StorageUploadError } from './storage-upload-error';
import { UploadsApi } from './uploads-api.service';

export const PART_CONCURRENCY = 3;
export const PART_ATTEMPTS = 3;
const RETRY_BASE_DELAY_MS = 500;

/** A failed PUT to storage, kept apart from failures of our own API so each maps correctly. */
class PartPutError extends Error {
  constructor(readonly source: unknown) {
    super('part upload failed');
  }
}

/** Network errors, server errors and throttling can pass on a second try; other 4xx cannot. */
function isRetryable(error: unknown): boolean {
  const source = error instanceof PartPutError ? error.source : error;
  if (!(source instanceof HttpErrorResponse)) {
    return false;
  }
  return source.status === 0 || source.status >= 500 || source.status === 429;
}

/**
 * Sends a file to storage in server-planned parts: each part is a slice of the file PUT to its own
 * signed address (no token, no extra headers). A failed part is retried on its own and gets a
 * fresh signed address each time. The server lists the parts itself when completing, so no ETag
 * needs to be read back here.
 */
@Injectable({ providedIn: 'root' })
export class MultipartTransfer {
  private readonly api = inject(UploadsApi);
  private readonly http = inject(HttpClient);
  private readonly document = inject(DOCUMENT);

  send(
    fileId: string,
    file: File,
    plan: MultipartInstructions,
    onProgress: (percent: number) => void,
  ): Observable<void> {
    // A plan that does not cover the file would upload it truncated; refuse before sending bytes.
    if (
      plan.part_size_bytes <= 0 ||
      plan.part_count !== Math.ceil(file.size / plan.part_size_bytes)
    ) {
      return throwError(() => new StorageUploadError());
    }
    const loaded = new Array<number>(plan.part_count).fill(0);
    const report = (): void =>
      onProgress(Math.min(99, Math.floor((100 * loaded.reduce((a, b) => a + b, 0)) / file.size)));
    const numbers = Array.from({ length: plan.part_count }, (_, index) => index + 1);
    return from(numbers).pipe(
      mergeMap(
        (number) => this.sendPart(fileId, file, plan, number, loaded, report),
        PART_CONCURRENCY,
      ),
      ignoreElements(),
    );
  }

  private sendPart(
    fileId: string,
    file: File,
    plan: MultipartInstructions,
    number: number,
    loaded: number[],
    report: () => void,
  ): Observable<void> {
    const start = (number - 1) * plan.part_size_bytes;
    // slice() drops the content type, so the browser adds no header the signature does not cover.
    const body = file.slice(start, Math.min(start + plan.part_size_bytes, file.size));
    // Presign and PUT retry together: a retry always uses a freshly signed address.
    return defer(() => this.api.partUrls(fileId, [number])).pipe(
      switchMap((response) => {
        const url = response.parts.find((part) => part.part_number === number)?.url;
        if (!url || !isExternalHttpUrl(url, this.document.location.origin)) {
          return throwError(() => new StorageUploadError());
        }
        return this.http
          .put(url, body, { reportProgress: true, observe: 'events', responseType: 'text' })
          .pipe(
            tap((event) => {
              if (event.type === HttpEventType.UploadProgress) {
                loaded[number - 1] = Math.min(event.loaded, body.size);
                report();
              }
            }),
            filter((event) => event.type === HttpEventType.Response),
            catchError((error: unknown) => throwError(() => new PartPutError(error))),
          );
      }),
      retry({
        count: PART_ATTEMPTS - 1,
        delay: (error, attempt) => {
          if (!isRetryable(error)) {
            return throwError(() => error);
          }
          loaded[number - 1] = 0;
          report();
          return timer(RETRY_BASE_DELAY_MS * 2 ** (attempt - 1));
        },
      }),
      catchError((error: unknown) =>
        throwError(() => (error instanceof PartPutError ? new StorageUploadError() : error)),
      ),
      tap({
        complete: () => {
          loaded[number - 1] = body.size;
          report();
        },
      }),
      map(() => undefined),
    );
  }
}
