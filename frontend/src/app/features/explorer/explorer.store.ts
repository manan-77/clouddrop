import { computed, inject, Injectable, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import {
  catchError,
  filter,
  forkJoin,
  map,
  of,
  startWith,
  switchMap,
  tap,
  type Observable,
} from 'rxjs';

import { FilesApi } from '@core/api/files-api.service';
import { FoldersApi } from '@core/api/folders-api.service';
import { type FileRead, type FolderRead, type Page } from '@core/api/models';
import { DownloadService } from '@core/download/download.service';
import { ErrorResolver } from '@core/error/error-resolver.service';

export const FOLDER_PAGE_SIZE = 50;
export const FILE_PAGE_SIZE = 20;

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
}

const lastPage = (page: Page<unknown>): number =>
  Math.max(1, Math.ceil(page.total / page.page_size));

/** Everything the explorer page shows for one folder. Provide it on the page, not globally. */
@Injectable()
export class ExplorerStore {
  private readonly foldersApi = inject(FoldersApi);
  private readonly filesApi = inject(FilesApi);
  private readonly downloads = inject(DownloadService);
  private readonly resolver = inject(ErrorResolver);

  // Null until the page says which folder to open, so nothing loads (and gets cancelled) twice.
  private readonly query = signal<Query | null>(null);

  readonly folderId = computed(() => this.query()?.folderId ?? null);
  readonly view = toSignal(
    toObservable(this.query).pipe(
      filter((query): query is Query => query !== null),
      switchMap((query) => this.load(query)),
      tap((view) => this.stepBackFromEmptyPage(view)),
    ),
    { initialValue: LOADING },
  );

  open(folderId: string | null): void {
    this.query.update((q) =>
      q && q.folderId === folderId && q.folderPage === 1 && q.filePage === 1
        ? q
        : { folderId, folderPage: 1, filePage: 1, tick: q?.tick ?? 0 },
    );
  }

  setFolderPage(page: number): void {
    this.query.update((q) => (q ? { ...q, folderPage: page } : q));
  }

  setFilePage(page: number): void {
    this.query.update((q) => (q ? { ...q, filePage: page } : q));
  }

  reload(): void {
    this.query.update((q) => (q ? { ...q, tick: q.tick + 1 } : q));
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

  deleteFile(fileId: string): Observable<void> {
    return this.filesApi.remove(fileId).pipe(tap(() => this.reload()));
  }

  downloadFile(fileId: string): Observable<void> {
    return this.filesApi.download(fileId).pipe(map((link) => this.downloads.start(link.url)));
  }

  private load(query: Query): Observable<ExplorerView> {
    return forkJoin({
      path: query.folderId ? this.foldersApi.path(query.folderId) : of<FolderRead[]>([]),
      folders: this.foldersApi.list(query.folderId, query.folderPage, FOLDER_PAGE_SIZE),
      files: this.filesApi.list(query.folderId, query.filePage, FILE_PAGE_SIZE),
    }).pipe(
      map((result): ExplorerView => ({ status: 'ready', error: null, ...result })),
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

  /** After deleting the last item on a page, show the previous page instead of an empty one. */
  private stepBackFromEmptyPage(view: ExplorerView): void {
    if (view.status !== 'ready' || !view.folders || !view.files) {
      return;
    }
    if (view.folders.items.length === 0 && view.folders.total > 0) {
      this.setFolderPage(lastPage(view.folders));
    }
    if (view.files.items.length === 0 && view.files.total > 0) {
      this.setFilePage(lastPage(view.files));
    }
  }
}
