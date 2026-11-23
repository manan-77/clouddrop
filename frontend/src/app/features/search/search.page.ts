import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import {
  catchError,
  debounceTime,
  map,
  type Observable,
  of,
  startWith,
  switchMap,
  tap,
} from 'rxjs';

import { type Page, type SearchHit } from '@core/api/models';
import { DEFAULT_PAGE_SIZE } from '@core/api/pagination';
import { SearchApi } from '@core/api/search-api.service';
import { fileDownloads } from '@core/download/file-downloads';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { IsInPipe } from '@shared/pipes/is-in.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { ErrorStateComponent } from '@shared/ui/error-state/error-state.component';
import { PagerComponent } from '@shared/ui/pager/pager.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

/** How long typing must pause before a search is sent. */
export const TYPING_PAUSE_MS = 300;

/** What is being asked for. A new object means "ask again", even for the same words. */
interface Request {
  readonly query: string;
  readonly page: number;
  readonly attempt: number;
}

type View =
  | { readonly status: 'idle' }
  // `keep`: the previous answer for the same words, still shown while the next page loads.
  | { readonly status: 'searching'; readonly keep: Page<SearchHit> | null }
  | { readonly status: 'ready'; readonly page: Page<SearchHit> }
  | { readonly status: 'error'; readonly message: string };

const IDLE: View = { status: 'idle' };

/**
 * Find files by what they say, not what they are called. The words stay in this component: they
 * are never put in the address bar, storage or a log.
 */
@Component({
  selector: 'cd-search-page',
  imports: [
    ButtonComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    IsInPipe,
    PagerComponent,
    SkeletonComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    .results {
      display: grid;
      gap: var(--cd-space-3);
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .result {
      display: grid;
      gap: var(--cd-space-2);
      padding: var(--cd-space-4);
      border: 1px solid var(--cd-border);
      border-radius: var(--cd-radius-md);
      background: var(--cd-surface);
    }
    .head {
      display: flex;
      flex-wrap: wrap;
      gap: var(--cd-space-2) var(--cd-space-4);
      align-items: baseline;
      justify-content: space-between;
    }
    .name {
      font-weight: 600;
      overflow-wrap: anywhere;
    }
    .meta {
      color: var(--cd-text-muted);
      font-size: var(--cd-font-size-sm);
    }
    .snippet {
      margin: 0;
      overflow-wrap: anywhere;
      white-space: pre-line;
    }
    .actions {
      justify-self: start;
    }
    .box {
      margin-bottom: var(--cd-space-5);
    }
  `,
  template: `
    <div class="cd-toolbar">
      <h1>Search</h1>
    </div>
    <div class="cd-field box">
      <label for="search-box">Search your files by meaning</label>
      <input
        id="search-box"
        class="cd-input"
        type="search"
        autocomplete="off"
        spellcheck="false"
        aria-describedby="search-hint"
        [value]="term()"
        (input)="typed($event)"
        (keydown.enter)="commit()"
      />
      <p id="search-hint" class="cd-hint">
        Describe what you are looking for, for example "when is the invoice due". Your words are not
        saved.
      </p>
    </div>
    @if (downloads.error(); as message) {
      <p class="cd-form-error" role="alert">{{ message }}</p>
    }
    <p class="cd-visually-hidden" role="status">{{ announcement() }}</p>
    @if (skeleton()) {
      <cd-skeleton [lines]="4" />
    } @else if (failure(); as message) {
      <cd-error-state [message]="message" (retry)="retry()" />
    } @else if (results(); as found) {
      @if (found.items.length === 0) {
        <cd-empty-state
          title="No matching files"
          description="Try other words, or describe it differently. Only files that finished processing can be found."
        />
      } @else {
        <ul class="results" aria-label="Search results" [attr.aria-busy]="loading()">
          @for (hit of found.items; track hit.chunk_id) {
            <li class="result">
              <div class="head">
                <span class="name">{{ hit.file_name }}</span>
                @if (hit.page !== null) {
                  <span class="meta">Page {{ hit.page }}</span>
                }
              </div>
              <p class="snippet">{{ hit.snippet }}</p>
              <button
                class="actions"
                cd-button
                variant="secondary"
                type="button"
                [busy]="hit.file_id | isIn: downloads.busy()"
                [attr.aria-label]="'Download ' + hit.file_name"
                (click)="downloads.start(hit.file_id)"
              >
                Download
              </button>
            </li>
          }
        </ul>
        <cd-pager
          label="Search results pagination"
          [page]="request().page"
          [pageSize]="pageSize"
          [total]="found.total"
          (pageChange)="goTo($event)"
        />
      }
    } @else {
      <cd-empty-state
        title="Search your files"
        description="Type what you remember about a document and the best matches appear here."
      />
    }
  `,
})
export class SearchPage {
  protected readonly pageSize = DEFAULT_PAGE_SIZE;
  protected readonly term = signal('');
  protected readonly request = signal<Request>({ query: '', page: 1, attempt: 0 });
  protected readonly downloads = fileDownloads();

  private readonly api = inject(SearchApi);
  private readonly resolver = inject(ErrorResolver);

  // `switchMap` drops the older request, so a slower answer can never replace a newer one, and
  // "searching" is set inside it: set before it, the cancelled request could undo it.
  private readonly view = toSignal(
    toObservable(this.request).pipe(switchMap((request) => this.run(request))),
    { initialValue: IDLE },
  );

  // Not signals: only `run()` reads them, when a request starts. What to keep on screen is decided
  // there, from the request just before this one, never from state that outlives it.
  private previousQuery = '';
  private lastAnswer: { query: string; page: Page<SearchHit> } | null = null;

  protected readonly loading = computed(() => this.view().status === 'searching');
  protected readonly failure = computed(() => {
    const view = this.view();
    return view.status === 'error' ? view.message : null;
  });
  protected readonly results = computed(() => {
    const view = this.view();
    if (view.status === 'ready') {
      return view.page;
    }
    return view.status === 'searching' ? view.keep : null;
  });
  /** Nothing to show yet for these words: the placeholder, not a blank gap. */
  protected readonly skeleton = computed(() => this.loading() && this.results() === null);
  /** Spoken, not shown: one persistent region whose text changes. */
  protected readonly announcement = computed(() => {
    const view = this.view();
    if (view.status === 'searching') {
      return 'Searching';
    }
    if (view.status !== 'ready') {
      return '';
    }
    const total = view.page.total;
    return total === 0 ? 'No matching files' : `${total} ${total === 1 ? 'file' : 'files'} found`;
  });

  constructor() {
    toObservable(this.term)
      .pipe(
        debounceTime(TYPING_PAUSE_MS),
        // No distinctUntilChanged here: `ask()` already ignores unchanged words, and a filter that
        // remembers only what this stream emitted would swallow a real edit back to old words.
        map((words) => words.trim()),
        takeUntilDestroyed(),
      )
      .subscribe((query) => this.ask(query));
  }

  protected typed(event: Event): void {
    this.term.set((event.target as HTMLInputElement).value);
  }

  /** Enter searches at once instead of waiting for the typing pause. */
  protected commit(): void {
    this.ask(this.term().trim());
  }

  protected goTo(page: number): void {
    this.request.update((current) => (current.page === page ? current : { ...current, page }));
  }

  protected retry(): void {
    this.request.update((current) => ({ ...current, attempt: current.attempt + 1 }));
  }

  /** The same words again is not a new search: no repeat request, no flicker. */
  private ask(query: string): void {
    if (query !== this.request().query) {
      this.request.set({ query, page: 1, attempt: 0 });
    }
  }

  private run(request: Request): Observable<View> {
    // Keep the list only when this request directly follows one for the same words (another page
    // of them). After other words, or after clearing the box, an older list would be stale.
    const followsSameWords = request.query === this.previousQuery;
    this.previousQuery = request.query;
    if (request.query === '') {
      this.lastAnswer = null;
      return of(IDLE);
    }
    const keep =
      followsSameWords && this.lastAnswer?.query === request.query ? this.lastAnswer.page : null;
    return this.api.search(request.query, request.page, DEFAULT_PAGE_SIZE).pipe(
      tap((found) => {
        // An empty page of a non-empty result is the server contradicting itself: never keep it.
        if (found.items.length > 0 || found.total === 0) {
          this.lastAnswer = { query: request.query, page: found };
        }
        this.stepBackIfPastTheEnd(request, found);
      }),
      map((found): View => ({ status: 'ready', page: found })),
      catchError((error: unknown) => {
        this.lastAnswer = null; // a retry must not show an older page as if it were current
        return of<View>({ status: 'error', message: this.resolver.resolve(error).message });
      }),
      startWith<View>({ status: 'searching', keep }),
    );
  }

  /** Results shrank while paging: go to the last page that exists (strictly earlier, so no loop). */
  private stepBackIfPastTheEnd(request: Request, found: Page<SearchHit>): void {
    const lastPage = Math.max(1, Math.ceil(found.total / DEFAULT_PAGE_SIZE));
    if (found.items.length === 0 && found.total > 0 && lastPage < request.page) {
      this.request.update((current) =>
        current === request ? { ...current, page: lastPage } : current,
      );
    }
  }
}
