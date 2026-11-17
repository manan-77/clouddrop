import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { finalize, map, type Observable } from 'rxjs';

import { type FileRead } from '@core/api/models';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { UploadQueue } from '@core/uploads/upload-queue.service';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { ErrorStateComponent } from '@shared/ui/error-state/error-state.component';
import { PagerComponent } from '@shared/ui/pager/pager.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { canWrite } from '@core/api/permissions';
import { ConfirmDialogComponent } from './confirm-dialog.component';
import { type Dialog } from './explorer-dialog';
import { DropZoneDirective } from './drop-zone.directive';
import { ExplorerStore } from './explorer.store';
import { FileTableComponent } from './file-table.component';
import { FolderTableComponent } from './folder-table.component';
import { NameDialogComponent } from './name-dialog.component';
import { SharingDialogsComponent } from './sharing-dialogs.component';
import { UploadButtonComponent } from './upload-button.component';
import { UploadPanelComponent } from './upload-panel.component';

@Component({
  selector: 'cd-explorer-page',
  imports: [
    RouterLink,
    ButtonComponent,
    ConfirmDialogComponent,
    DropZoneDirective,
    EmptyStateComponent,
    ErrorStateComponent,
    FileTableComponent,
    FolderTableComponent,
    NameDialogComponent,
    PagerComponent,
    SharingDialogsComponent,
    SkeletonComponent,
    UploadButtonComponent,
    UploadPanelComponent,
  ],
  providers: [ExplorerStore],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './explorer.page.html',
})
export class ExplorerPage {
  protected readonly store = inject(ExplorerStore);
  protected readonly uploads = inject(UploadQueue);
  protected readonly dialog = signal<Dialog | null>(null);
  protected readonly busy = signal(false);
  protected readonly dialogError = signal<string | null>(null);
  protected readonly notice = signal<string | null>(null);
  protected readonly downloading = signal<readonly string[]>([]);

  private readonly resolver = inject(ErrorResolver);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);

  // Read from the route path only (never a query string), so /?folderId=x cannot open a folder.
  private readonly folderId = toSignal(
    this.route.paramMap.pipe(map((params) => params.get('folderId'))),
    { initialValue: this.route.snapshot.paramMap.get('folderId') },
  );

  protected readonly currentFolderId = computed(() => this.folderId() ?? null);

  /**
   * The role-based answer for the folder on screen, or null while it is unknown. A view only
   * counts when it belongs to the current folder (the store follows the route a tick later, so
   * the previous folder's view can still be on screen right after a navigation).
   */
  private readonly writableNow = computed<boolean | null>(() => {
    const view = this.store.view();
    if (view.status !== 'ready') {
      return null;
    }
    const folderId = this.currentFolderId();
    const last = view.path[view.path.length - 1];
    const belongsHere = folderId === null ? view.path.length === 0 : last?.id === folderId;
    if (!belongsHere) {
      return null;
    }
    return folderId === null || canWrite(last.role);
  });

  /** The last known answer per folder, so a reload does not unmount the toolbar buttons. */
  private readonly lastWritable = signal<{ folderId: string | null; writable: boolean } | null>(
    null,
  );

  /**
   * Whether to offer upload and new-folder here. Unknown (first load, another folder's view) and
   * failed loads offer nothing; a reload of the same folder keeps the last answer.
   */
  protected readonly canWriteHere = computed(() => {
    const now = this.writableNow();
    if (now !== null) {
      return now;
    }
    const last = this.lastWritable();
    return (
      this.store.view().status === 'loading' &&
      last?.folderId === this.currentFolderId() &&
      last.writable
    );
  });

  constructor() {
    effect(() => {
      const writable = this.writableNow();
      if (writable !== null) {
        this.lastWritable.set({ folderId: this.currentFolderId(), writable });
      } else if (this.store.view().status === 'error') {
        // A failed load forgets the answer: the access may be gone, and Retry must start unknown.
        this.lastWritable.set(null);
      }
    });
    // A finished upload into the folder on screen refreshes the listing.
    this.uploads.completed$.pipe(takeUntilDestroyed()).subscribe((item) => {
      if (item.folderId === this.currentFolderId()) {
        this.store.reload();
      }
    });
    effect(() => {
      this.store.open(this.currentFolderId());
      // A dialog or message belongs to the folder it was opened in.
      this.dialog.set(null);
      this.dialogError.set(null);
      this.notice.set(null);
    });
  }

  protected addFiles(files: File[]): void {
    if (!this.canWriteHere()) {
      return;
    }
    this.uploads.add(files, this.currentFolderId());
  }

  protected show(dialog: Dialog): void {
    if (this.busy()) {
      return;
    }
    this.dialogError.set(null);
    this.dialog.set(dialog);
  }

  protected closeDialog(): void {
    if (!this.busy()) {
      this.dialog.set(null);
    }
  }

  protected submitName(name: string): void {
    const dialog = this.dialog();
    switch (dialog?.kind) {
      case 'create-folder':
        this.run(this.store.createFolder(name));
        break;
      case 'rename-folder':
        this.run(this.store.renameFolder(dialog.folder.id, name));
        break;
      case 'rename-file':
        this.run(this.store.renameFile(dialog.file.id, name));
        break;
      default:
        break;
    }
  }

  protected confirmDelete(): void {
    const dialog = this.dialog();
    if (dialog?.kind === 'delete-folder') {
      this.run(this.store.deleteFolder(dialog.folder.id));
    } else if (dialog?.kind === 'delete-file') {
      this.run(this.store.deleteFile(dialog.file.id));
    }
  }

  protected download(file: FileRead): void {
    if (this.downloading().includes(file.id)) {
      return;
    }
    this.notice.set(null);
    this.downloading.update((ids) => [...ids, file.id]);
    this.store
      .downloadFile(file.id)
      .pipe(
        finalize(() => this.downloading.update((ids) => ids.filter((id) => id !== file.id))),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        error: (error: unknown) => this.notice.set(this.resolver.resolve(error).message),
      });
  }

  private run(operation: Observable<unknown>): void {
    if (this.busy()) {
      return;
    }
    this.busy.set(true);
    this.dialogError.set(null);
    operation
      .pipe(
        finalize(() => this.busy.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: () => this.dialog.set(null),
        error: (error: unknown) => this.dialogError.set(this.resolver.resolve(error).message),
      });
  }
}
