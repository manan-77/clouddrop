import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  type OnInit,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { FilesApi } from '@core/api/files-api.service';
import { type Page, type SharedItem } from '@core/api/models';
import { SharingApi } from '@core/api/sharing-api.service';
import { DownloadService } from '@core/download/download.service';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { DateTimePipe } from '@shared/pipes/date-time.pipe';
import { FileSizePipe } from '@shared/pipes/file-size.pipe';
import { IsInPipe } from '@shared/pipes/is-in.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { ErrorStateComponent } from '@shared/ui/error-state/error-state.component';
import { PagerComponent } from '@shared/ui/pager/pager.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; page: Page<SharedItem> };

const PAGE_SIZE = 50;

/** What other people shared with me: the top of each shared tree, opened in the normal explorer. */
@Component({
  selector: 'cd-shared-with-me-page',
  imports: [
    RouterLink,
    ButtonComponent,
    DateTimePipe,
    EmptyStateComponent,
    ErrorStateComponent,
    FileSizePipe,
    IsInPipe,
    PagerComponent,
    SkeletonComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="cd-toolbar">
      <h1>Shared with me</h1>
    </div>
    <p class="cd-form-error" role="alert">{{ notice() }}</p>
    @switch (state().status) {
      @case ('loading') {
        <cd-skeleton [lines]="4" />
      }
      @case ('error') {
        <cd-error-state [message]="errorText()" (retry)="load(pageNumber())" />
      }
      @default {
        @if (items().length === 0) {
          <cd-empty-state
            title="Nothing has been shared with you"
            description="When someone shares a folder or file with you, it shows up here."
          />
        } @else {
          <div class="cd-table-wrap">
            <table class="cd-table">
              <caption class="cd-visually-hidden">
                Shared with me
              </caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Shared by</th>
                  <th scope="col">Your access</th>
                  <th scope="col">Size</th>
                  <th scope="col">Modified</th>
                  <th scope="col"><span class="cd-visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                @for (item of items(); track item.id) {
                  <tr>
                    <td>
                      @if (item.resource_type === 'folder') {
                        <a [routerLink]="['/folders', item.id]">{{ item.name }}</a>
                      } @else {
                        {{ item.name }}
                      }
                    </td>
                    <td>{{ item.owner_name }}</td>
                    <td>{{ item.role === 'editor' ? 'Can edit' : 'Can view' }}</td>
                    <td>{{ item.size_bytes === null ? '' : (item.size_bytes | fileSize) }}</td>
                    <td>{{ item.updated_at | cdDateTime }}</td>
                    <td class="cd-actions">
                      @if (item.resource_type === 'file') {
                        <button
                          cd-button
                          variant="secondary"
                          type="button"
                          [busy]="item.id | isIn: downloading()"
                          [attr.aria-label]="'Download ' + item.name"
                          (click)="download(item)"
                        >
                          Download
                        </button>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <cd-pager
            label="Shared items pagination"
            [page]="pageNumber()"
            [pageSize]="pageSize"
            [total]="total()"
            (pageChange)="load($event)"
          />
        }
      }
    }
  `,
})
export class SharedWithMePage implements OnInit {
  protected readonly pageSize = PAGE_SIZE;
  protected readonly state = signal<State>({ status: 'loading' });
  protected readonly items = signal<readonly SharedItem[]>([]);
  protected readonly total = signal(0);
  protected readonly pageNumber = signal(1);
  protected readonly errorText = signal('');
  protected readonly notice = signal<string | null>(null);
  protected readonly downloading = signal<readonly string[]>([]);

  private readonly sharing = inject(SharingApi);
  private readonly files = inject(FilesApi);
  private readonly downloads = inject(DownloadService);
  private readonly resolver = inject(ErrorResolver);
  private readonly destroyRef = inject(DestroyRef);

  ngOnInit(): void {
    this.load(1);
  }

  protected load(page: number): void {
    this.state.set({ status: 'loading' });
    this.sharing
      .sharedWithMe(page, PAGE_SIZE)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.items.set(result.items);
          this.total.set(result.total);
          this.pageNumber.set(result.page);
          this.state.set({ status: 'ready', page: result });
        },
        error: (error: unknown) => {
          this.errorText.set(this.resolver.resolve(error).message);
          this.state.set({ status: 'error', message: this.errorText() });
        },
      });
  }

  protected download(item: SharedItem): void {
    if (this.downloading().includes(item.id)) {
      return;
    }
    this.notice.set(null);
    this.downloading.update((ids) => [...ids, item.id]);
    this.files
      .download(item.id)
      .pipe(
        finalize(() => this.downloading.update((ids) => ids.filter((id) => id !== item.id))),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (link) => this.downloads.start(link.url),
        error: (error: unknown) => this.notice.set(this.resolver.resolve(error).message),
      });
  }
}
