import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { catchError, map, of, startWith, switchMap } from 'rxjs';

import { FoldersApi } from '@core/api/folders-api.service';
import { type FileRead, type FolderRead, type Page } from '@core/api/models';
import { canWrite } from '@core/api/permissions';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { ErrorStateComponent } from '@shared/ui/error-state/error-state.component';
import { PagerComponent } from '@shared/ui/pager/pager.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

const PAGE_SIZE = 20;

type Listing =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; folders: Page<FolderRead> };

/**
 * Picks the folder to move a file into by browsing folders one level at a time. The parent runs
 * the request and reports busy/error; the server decides whether the move is allowed.
 */
@Component({
  selector: 'cd-move-dialog',
  imports: [
    ButtonComponent,
    DialogComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    PagerComponent,
    SkeletonComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <cd-dialog heading="Move file" [dismissible]="!busy()" (dismissed)="dismissed.emit()">
      <p>Choose where to move {{ file().name }}.</p>
      <nav aria-label="Destination">
        <ol class="trail">
          <li>
            <button
              cd-button
              variant="secondary"
              type="button"
              [disabled]="busy()"
              [attr.aria-current]="trail().length === 0 ? 'location' : null"
              (click)="goTo(0)"
            >
              All files
            </button>
          </li>
          @for (folder of trail(); track folder.id; let index = $index) {
            <li>
              <button
                cd-button
                variant="secondary"
                type="button"
                [disabled]="busy()"
                [attr.aria-current]="index === trail().length - 1 ? 'location' : null"
                (click)="goTo(index + 1)"
              >
                {{ folder.name }}
              </button>
            </li>
          }
        </ol>
      </nav>
      @let current = listing();
      <div aria-live="polite">
        @switch (current.status) {
          @case ('loading') {
            <cd-skeleton [lines]="3" />
          }
          @case ('error') {
            <cd-error-state [message]="errorMessage()" (retry)="reload()" />
          }
          @default {
            @if (folders(); as page) {
              @if (page.total === 0) {
                <cd-empty-state title="No folders here" />
              } @else {
                <ul class="choices">
                  @for (folder of page.items; track folder.id) {
                    <li>
                      <button
                        cd-button
                        variant="secondary"
                        type="button"
                        [disabled]="busy()"
                        [attr.aria-label]="'Open folder ' + folder.name"
                        (click)="open(folder)"
                      >
                        {{ folder.name }}
                      </button>
                    </li>
                  }
                </ul>
                <cd-pager
                  label="Destination folders pagination"
                  [page]="page.page"
                  [pageSize]="page.page_size"
                  [total]="page.total"
                  (pageChange)="setPage($event)"
                />
              }
            }
          }
        }
      </div>
      @if (error(); as text) {
        <p class="cd-form-error" role="alert">{{ text }}</p>
      }
      <div class="cd-actions">
        <button
          cd-button
          variant="secondary"
          type="button"
          [disabled]="busy()"
          (click)="dismissed.emit()"
        >
          Cancel
        </button>
        <button
          cd-button
          type="button"
          [busy]="busy()"
          [disabled]="!canMoveHere()"
          (click)="moved.emit(destinationId())"
        >
          Move here
        </button>
      </div>
    </cd-dialog>
  `,
  styles: `
    .trail,
    .choices {
      display: flex;
      flex-wrap: wrap;
      gap: var(--cd-space-2);
      list-style: none;
      margin: 0;
      padding: 0;
    }
  `,
})
export class MoveDialogComponent {
  readonly file = input.required<FileRead>();
  readonly busy = input(false);
  readonly error = input<string | null>(null);
  readonly moved = output<string | null>();
  /** The destination changed, so the parent can clear an error that belonged to the last one. */
  readonly navigated = output<void>();
  readonly dismissed = output<void>();

  /** Folders opened so far, from the top level down; empty is the top level. */
  protected readonly trail = signal<readonly FolderRead[]>([]);
  private readonly pageNumber = signal(1);
  private readonly tick = signal(0);
  private readonly resolver = inject(ErrorResolver);
  private readonly foldersApi = inject(FoldersApi);

  protected readonly destinationId = computed(() => this.trail().at(-1)?.id ?? null);
  private readonly query = computed(() => ({
    parentId: this.destinationId(),
    page: this.pageNumber(),
    tick: this.tick(),
  }));

  protected readonly listing = toSignal(
    toObservable(this.query).pipe(
      switchMap((query) =>
        this.foldersApi.list(query.parentId, query.page, PAGE_SIZE).pipe(
          map((folders): Listing => ({ status: 'ready', folders })),
          startWith<Listing>({ status: 'loading' }),
          catchError((error: unknown) =>
            of<Listing>({ status: 'error', message: this.resolver.resolve(error).message }),
          ),
        ),
      ),
    ),
    { initialValue: { status: 'loading' } as Listing },
  );
  protected readonly folders = computed(() => {
    const listing = this.listing();
    return listing.status === 'ready' ? listing.folders : null;
  });
  protected readonly errorMessage = computed(() => {
    const listing = this.listing();
    return listing.status === 'error' ? listing.message : '';
  });

  /** Not offered for the folder the file is already in, or one the caller cannot write to. */
  protected readonly canMoveHere = computed(() => {
    const here = this.trail().at(-1);
    return (
      this.listing().status === 'ready' &&
      this.destinationId() !== this.file().folder_id &&
      (!here || canWrite(here.role))
    );
  });

  protected open(folder: FolderRead): void {
    this.trail.update((trail) => [...trail, folder]);
    this.pageNumber.set(1);
    this.navigated.emit();
  }

  protected goTo(depth: number): void {
    this.trail.update((trail) => trail.slice(0, depth));
    this.pageNumber.set(1);
    this.navigated.emit();
  }

  protected setPage(page: number): void {
    this.pageNumber.set(page);
  }

  protected reload(): void {
    this.tick.update((tick) => tick + 1);
  }
}
