import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { finalize, type Observable } from 'rxjs';

import { type FileRead, type FolderRead } from '@core/api/models';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { ErrorStateComponent } from '@shared/ui/error-state/error-state.component';
import { PagerComponent } from '@shared/ui/pager/pager.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { ConfirmDialogComponent } from './confirm-dialog.component';
import { ExplorerStore } from './explorer.store';
import { FileTableComponent } from './file-table.component';
import { FolderTableComponent } from './folder-table.component';
import { NameDialogComponent } from './name-dialog.component';

type Dialog =
  | { kind: 'create-folder' }
  | { kind: 'rename-folder'; folder: FolderRead }
  | { kind: 'rename-file'; file: FileRead }
  | { kind: 'delete-folder'; folder: FolderRead }
  | { kind: 'delete-file'; file: FileRead };

@Component({
  selector: 'cd-explorer-page',
  imports: [
    RouterLink,
    ButtonComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    FileTableComponent,
    FolderTableComponent,
    NameDialogComponent,
    PagerComponent,
    SkeletonComponent,
  ],
  providers: [ExplorerStore],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './explorer.page.html',
})
export class ExplorerPage {
  /** Bound from the route (`folders/:folderId`); absent at the root. */
  readonly folderId = input<string | undefined>();

  protected readonly store = inject(ExplorerStore);
  protected readonly dialog = signal<Dialog | null>(null);
  protected readonly busy = signal(false);
  protected readonly dialogError = signal<string | null>(null);
  protected readonly notice = signal<string | null>(null);

  private readonly resolver = inject(ErrorResolver);
  private readonly destroyRef = inject(DestroyRef);

  constructor() {
    effect(() => this.store.open(this.folderId() ?? null));
  }

  protected show(dialog: Dialog): void {
    this.dialogError.set(null);
    this.dialog.set(dialog);
  }

  protected closeDialog(): void {
    this.dialog.set(null);
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
    this.notice.set(null);
    this.store
      .downloadFile(file.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
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
