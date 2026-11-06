import { HttpClient, HttpEventType } from '@angular/common/http';
import { DestroyRef, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  catchError,
  EMPTY,
  filter,
  finalize,
  map,
  mergeMap,
  of,
  Subject,
  switchMap,
  takeUntil,
  tap,
  throwError,
  type Observable,
} from 'rxjs';

import { type UploadInstructions } from '@core/api/models';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { UploadsApi } from './uploads-api.service';

export type UploadStatus =
  'queued' | 'requesting' | 'uploading' | 'completing' | 'done' | 'failed' | 'cancelled';

export interface UploadItem {
  readonly id: string;
  readonly file: File;
  readonly name: string;
  readonly size: number;
  readonly folderId: string | null;
  readonly status: UploadStatus;
  readonly progress: number;
  readonly error: string | null;
  readonly fileId: string | null;
}

export const MAX_PARALLEL_UPLOADS = 3;
/** Mirrors the server default for a quick message only; the server stays the authority. */
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
export const STORAGE_FAILED_MESSAGE = 'The upload to storage failed. Please try again.';
export const EMPTY_FILE_MESSAGE = 'This file is empty.';
export const TOO_LARGE_MESSAGE = 'This file is too large to upload.';

const ACTIVE: ReadonlySet<UploadStatus> = new Set([
  'queued',
  'requesting',
  'uploading',
  'completing',
]);
const FINISHED: ReadonlySet<UploadStatus> = new Set(['done', 'failed', 'cancelled']);

class StorageUploadError extends Error {}

let sequence = 0;

/**
 * Uploads files straight to storage with a presigned form: ask the API for instructions, send the
 * file to storage (never through our server and never with our token), then tell the API it is
 * complete. At most three uploads run at once; each can be cancelled or retried.
 */
@Injectable({ providedIn: 'root' })
export class UploadQueue {
  private readonly api = inject(UploadsApi);
  private readonly http = inject(HttpClient);
  private readonly resolver = inject(ErrorResolver);

  readonly items = signal<readonly UploadItem[]>([]);

  private readonly completedSubject = new Subject<UploadItem>();
  /** Emits each upload that finished successfully, so a listing can refresh. */
  readonly completed$ = this.completedSubject.asObservable();

  private readonly starts = new Subject<string>();
  private readonly cancels = new Subject<string>();

  constructor() {
    this.starts
      .pipe(
        mergeMap((id) => this.run(id), MAX_PARALLEL_UPLOADS),
        takeUntilDestroyed(inject(DestroyRef)),
      )
      .subscribe();
  }

  add(files: readonly File[], folderId: string | null): void {
    const created = files.map((file) => this.create(file, folderId));
    this.items.update((list) => [...list, ...created]);
    created.filter((item) => item.status === 'queued').forEach((item) => this.starts.next(item.id));
  }

  cancel(id: string): void {
    const item = this.find(id);
    if (item && ACTIVE.has(item.status)) {
      this.patch(id, { status: 'cancelled' });
      this.cancels.next(id);
    }
  }

  retry(id: string): void {
    if (this.find(id)?.status === 'failed') {
      this.patch(id, { status: 'queued', progress: 0, error: null, fileId: null });
      this.starts.next(id);
    }
  }

  remove(id: string): void {
    const item = this.find(id);
    if (item && FINISHED.has(item.status)) {
      this.items.update((list) => list.filter((entry) => entry.id !== id));
    }
  }

  private create(file: File, folderId: string | null): UploadItem {
    const base = {
      id: `upload-${++sequence}`,
      file,
      name: file.name,
      size: file.size,
      folderId,
      progress: 0,
      fileId: null,
    };
    if (file.size === 0) {
      return { ...base, status: 'failed', error: EMPTY_FILE_MESSAGE };
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      return { ...base, status: 'failed', error: TOO_LARGE_MESSAGE };
    }
    return { ...base, status: 'queued', error: null };
  }

  private run(id: string): Observable<void> {
    const item = this.find(id);
    if (item?.status !== 'queued') {
      return EMPTY;
    }
    this.patch(id, { status: 'requesting', progress: 0 });
    return this.api
      .init({
        name: item.name,
        content_type: item.file.type,
        size_bytes: item.size,
        folder_id: item.folderId,
      })
      .pipe(
        tap((response) => this.patch(id, { status: 'uploading', fileId: response.file.id })),
        switchMap((response) =>
          this.sendToStorage(id, response.upload, item.file).pipe(map(() => response.file.id)),
        ),
        tap(() => this.patch(id, { status: 'completing', progress: 100 })),
        switchMap((fileId) => this.api.complete(fileId)),
        tap(() => {
          this.patch(id, { status: 'done' });
          const done = this.find(id);
          if (done) {
            this.completedSubject.next(done);
          }
        }),
        map(() => undefined),
        catchError((error: unknown) => {
          this.patch(id, {
            status: 'failed',
            error:
              error instanceof StorageUploadError
                ? STORAGE_FAILED_MESSAGE
                : this.resolver.resolve(error).message,
          });
          return of(undefined);
        }),
        takeUntil(this.cancels.pipe(filter((cancelled) => cancelled === id))),
        finalize(() => undefined),
      );
  }

  private sendToStorage(id: string, upload: UploadInstructions, file: File): Observable<void> {
    // Storage requires the file field last. File is a Blob: the browser streams it from disk.
    const form = new FormData();
    for (const [name, value] of Object.entries(upload.fields)) {
      form.append(name, value);
    }
    form.append('file', file);
    return this.http.post(upload.url, form, { reportProgress: true, observe: 'events' }).pipe(
      tap((event) => {
        if (event.type === HttpEventType.UploadProgress && event.total) {
          this.patch(id, { progress: Math.round((100 * event.loaded) / event.total) });
        }
      }),
      filter((event) => event.type === HttpEventType.Response),
      map(() => undefined),
      catchError(() => throwError(() => new StorageUploadError())),
    );
  }

  private find(id: string): UploadItem | undefined {
    return this.items().find((item) => item.id === id);
  }

  private patch(id: string, change: Partial<UploadItem>): void {
    this.items.update((list) =>
      list.map((item) => (item.id === id ? { ...item, ...change } : item)),
    );
  }
}
