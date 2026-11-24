import { computed, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import {
  catchError,
  EMPTY,
  filter,
  forkJoin,
  map,
  of,
  startWith,
  switchMap,
  tap,
  timer,
  type Observable,
} from 'rxjs';

import { FilesApi } from '@core/api/files-api.service';
import { FoldersApi } from '@core/api/folders-api.service';
import { type FileRead, type FileStatus, type FolderRead, type Page } from '@core/api/models';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { DEFAULT_PAGE_SIZE } from '@core/api/pagination';
import { pollDelayMs } from '@core/api/polling';

export interface ExplorerView {
  status: 'loading' | 'ready' | 'error';
  path: FolderRead[];
  folders: Page<FolderRead> | null;
  files: Page<FileRead> | null;
  error: string | null;
}

const LOADING: ExplorerView = {
  status: 'loading',
  path: [],
  folders: null,
  files: null,
  error: null,
};

interface Query {
  folderId: string | null;
  folderPage: number;
  filePage: number;
  tick: number;
  /** A refresh nobody asked for (polling): no loading state, and a failure is not shown. */
  quiet: boolean;
}

/** Statuses that will still change by themselves, so the list is refreshed until they settle. */
const IN_PROGRESS: ReadonlySet<FileStatus> = new Set([
  'pending_upload',
  'uploaded',
  'scanning',
  'processing',
]);

const lastPage = (page: Page<unknown>): number =>
  Math.max(1, Math.ceil(page.total / page.page_size));

/** Everything the explorer page shows for one folder. Provide it on the page, not globally. */
@Injectable()
export class ExplorerStore {
  private readonly foldersApi = inject(FoldersApi);
  private readonly filesApi = inject(FilesApi);
  private readonly resolver = inject(ErrorResolver);

  // Null until the page says which folder to open, so nothing loads (and gets cancelled) twice.
  private readonly query = signal<Query | null>(null);

  // Refreshes done since the last real load, and the last good answer (for a failed refresh).
  private polls = 0;
  private latest: ExplorerView = LOADING;

  readonly folderId = computed(() => this.query()?.folderId ?? null);
  readonly view = toSignal(
    toObservable(this.query).pipe(
      filter((query): query is Query => query !== null),
      switchMap((query) => this.load(query)),
      tap((view) => {
        if (view.status === 'ready') {
          this.latest = view;
        }
        this.stepBackFromEmptyPage(view);
      }),
    ),
    { initialValue: LOADING },
  );

  constructor() {
    // switchMap: a new answer, a new folder or leaving the page drops the pending timer.
    toObservable(this.view)
      .pipe(
        switchMap((view) => this.nextPoll(view)),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.refreshQuietly());
  }

  open(folderId: string | null): void {
    this.query.update((q) =>
      q && q.folderId === folderId && q.folderPage === 1 && q.filePage === 1
        ? q
        : { folderId, folderPage: 1, filePage: 1, tick: q?.tick ?? 0, quiet: false },
    );
  }

  setFolderPage(page: number): void {
    this.query.update((q) =>
      q && q.folderPage !== page ? { ...q, folderPage: page, quiet: false } : q,
    );
  }

  setFilePage(page: number): void {
    this.query.update((q) =>
      q && q.filePage !== page ? { ...q, filePage: page, quiet: false } : q,
    );
  }

  reload(): void {
    this.query.update((q) => (q ? { ...q, tick: q.tick + 1, quiet: false } : q));
  }

  createFolder(name: string): Observable<FolderRead> {
    return this.foldersApi.create(name, this.folderId()).pipe(tap(() => this.reload()));
  }

  renameFolder(folderId: string, name: string): Observable<FolderRead> {
    return this.foldersApi.rename(folderId, name).pipe(tap(() => this.reload()));
  }

  deleteFolder(folderId: string): Observable<void> {
    return this.foldersApi.remove(folderId).pipe(tap(() => this.reload()));
  }

  renameFile(fileId: string, name: string): Observable<FileRead> {
    return this.filesApi.rename(fileId, name).pipe(tap(() => this.reload()));
  }

  moveFile(fileId: string, folderId: string | null): Observable<FileRead> {
    return this.filesApi.move(fileId, folderId).pipe(tap(() => this.reload()));
  }

  deleteFile(fileId: string): Observable<void> {
    return this.filesApi.remove(fileId).pipe(tap(() => this.reload()));
  }

  /** How long to wait before refreshing, or never: only while a listed file is still changing. */
  private nextPoll(view: ExplorerView): Observable<unknown> {
    const changing =
      view.status === 'ready' && !!view.files?.items.some((file) => IN_PROGRESS.has(file.status));
    const delay = pollDelayMs(this.polls);
    return changing && delay !== null ? timer(delay) : EMPTY;
  }

  private refreshQuietly(): void {
    this.polls += 1;
    this.query.update((q) => (q ? { ...q, tick: q.tick + 1, quiet: true } : q));
  }

  private load(query: Query): Observable<ExplorerView> {
    const loaded = forkJoin({
      path: query.folderId ? this.foldersApi.path(query.folderId) : of<FolderRead[]>([]),
      folders: this.foldersApi.list(query.folderId, query.folderPage, DEFAULT_PAGE_SIZE),
      files: this.filesApi.list(query.folderId, query.filePage, DEFAULT_PAGE_SIZE),
    }).pipe(map((result): ExplorerView => ({ status: 'ready', error: null, ...result })));
    if (query.quiet) {
      // A copy of the last good answer on failure: the screen keeps what it shows, and the new
      // object lets the next poll be scheduled (the same object would not look like a change).
      return loaded.pipe(catchError(() => of<ExplorerView>({ ...this.latest })));
    }
    this.polls = 0;
    return loaded.pipe(
      startWith(LOADING),
      catchError((error: unknown) =>
        of<ExplorerView>({
          ...LOADING,
          status: 'error',
          error: this.resolver.resolve(error).message,
        }),
      ),
    );
  }

  /**
   * After deleting the last item on a page, show the last page that still exists. Only steps back
   * when the last page is genuinely earlier, so inconsistent counts can never cause a reload loop.
   */
  private stepBackFromEmptyPage(view: ExplorerView): void {
    if (view.status !== 'ready' || !view.folders || !view.files) {
      return;
    }
    if (
      view.folders.items.length === 0 &&
      view.folders.total > 0 &&
      lastPage(view.folders) < view.folders.page
    ) {
      this.setFolderPage(lastPage(view.folders));
    }
    if (
      view.files.items.length === 0 &&
      view.files.total > 0 &&
      lastPage(view.files) < view.files.page
    ) {
      this.setFilePage(lastPage(view.files));
    }
  }
}
