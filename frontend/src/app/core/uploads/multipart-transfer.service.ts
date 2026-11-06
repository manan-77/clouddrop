import { DOCUMENT } from '@angular/common';
import { HttpClient, HttpEventType } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import {
  catchError,
  filter,
  from,
  map,
  mergeMap,
  retry,
  switchMap,
  tap,
  throwError,
  timer,
  toArray,
  type Observable,
} from 'rxjs';

import { type MultipartInstructions } from '@core/api/models';
import { UploadsApi } from './uploads-api.service';
import { isExternalHttpUrl, StorageUploadError } from './storage-upload-error';

export const PART_CONCURRENCY = 3;
export const PART_ATTEMPTS = 3;
const RETRY_BASE_DELAY_MS = 500;

/**
 * Sends a file to storage in server-planned parts: each part is a slice of the file PUT to its own
 * signed address (no token, no extra headers). A failed part is retried on its own. The server
 * lists the parts itself when completing, so no ETag needs to be read back here.
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
    const loaded = new Array<number>(plan.part_count).fill(0);
    const report = (): void =>
      onProgress(Math.min(99, Math.floor((100 * loaded.reduce((a, b) => a + b, 0)) / file.size)));
    const numbers = Array.from({ length: plan.part_count }, (_, index) => index + 1);
    return from(numbers).pipe(
      mergeMap(
        (number) => this.sendPart(fileId, file, plan, number, loaded, report),
        PART_CONCURRENCY,
      ),
      toArray(),
      map(() => undefined),
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
    return this.api.partUrls(fileId, [number]).pipe(
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
            map(() => undefined),
            retry({
              count: PART_ATTEMPTS - 1,
              delay: (_error, attempt) => {
                loaded[number - 1] = 0;
                report();
                return timer(RETRY_BASE_DELAY_MS * 2 ** (attempt - 1));
              },
            }),
            catchError(() => throwError(() => new StorageUploadError())),
          );
      }),
      tap({
        complete: () => {
          loaded[number - 1] = body.size;
          report();
        },
      }),
    );
  }
}
