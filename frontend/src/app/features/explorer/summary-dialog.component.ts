import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  ElementRef,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import {
  catchError,
  EMPTY,
  finalize,
  map,
  type Observable,
  of,
  startWith,
  switchMap,
  timer,
} from 'rxjs';

import { type FileRead, type FileSummary } from '@core/api/models';
import { canWrite } from '@core/api/permissions';
import { pollDelayMs } from '@core/api/polling';
import { SummaryApi } from '@core/api/summary-api.service';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { DateTimePipe } from '@shared/pipes/date-time.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

/** Why a summary failed, from the short code the server stores. Unknown codes read generically. */
const FAILURES: Readonly<Record<string, string>> = {
  no_text: 'There is no text in this file to summarise.',
  bad_output: 'The summary could not be written this time.',
  chat_unavailable: 'The assistant was not available when the summary was written.',
  prompt_too_large: 'This file could not be summarised.',
  too_many_attempts: 'The summary could not be written after several tries.',
};
const FAILURE_FALLBACK = 'The summary could not be written.';

export const failureText = (code: string | null): string =>
  code !== null && Object.hasOwn(FAILURES, code) ? FAILURES[code] : FAILURE_FALLBACK;

type View =
  | { readonly status: 'loading' }
  | { readonly status: 'none' }
  | { readonly status: 'error'; readonly message: string }
  | { readonly status: 'loaded'; readonly summary: FileSummary };

const LOADING: View = { status: 'loading' };
const STALLED = 'stalled';

/** What a model made of one file: a summary, a category and tags. It is written in the background,
 * so this refreshes quietly while it is still being written. Everything is shown as text. */
@Component({
  selector: 'cd-summary-dialog',
  imports: [ButtonComponent, DateTimePipe, DialogComponent, SkeletonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    .text {
      margin: 0 0 var(--cd-space-3);
      overflow-wrap: anywhere;
      white-space: pre-line;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: var(--cd-space-2);
      margin: 0 0 var(--cd-space-3);
      padding: 0;
      list-style: none;
    }
    .chip {
      padding: var(--cd-space-1) var(--cd-space-3);
      border: 1px solid var(--cd-border-strong);
      border-radius: var(--cd-radius-lg);
      font-size: var(--cd-font-size-sm);
    }
    .category {
      font-weight: 600;
    }
  `,
  template: `
    <cd-dialog [heading]="'Summary of ' + file().name" (dismissed)="dismissed.emit()">
      <p class="cd-visually-hidden" role="status">{{ announcement() }}</p>
      @if (view().status === 'loading') {
        <cd-skeleton [lines]="3" />
      } @else if (errorText(); as message) {
        <p class="cd-form-error" role="alert">{{ message }}</p>
        <button cd-button variant="secondary" type="button" (click)="reload()">Try again</button>
      } @else if (summary(); as current) {
        @if (current.summary) {
          <p class="text">{{ current.summary }}</p>
          @if (current.category) {
            <ul class="chips" aria-label="Category and tags">
              <li class="chip category">{{ current.category }}</li>
              @for (tag of current.tags; track tag) {
                <li class="chip">{{ tag }}</li>
              }
            </ul>
          }
          @if (current.partial) {
            <p class="cd-hint">This file is long: only the start was read.</p>
          }
          @if (current.generated_at) {
            <p class="cd-hint">Written {{ current.generated_at | cdDateTime }}.</p>
          }
        }
        @if (current.status === 'pending') {
          <p class="cd-hint">
            {{
              current.summary ? 'A new summary is being written.' : 'The summary is being written.'
            }}
          </p>
          @if (stalled()) {
            <p class="cd-hint">
              This is taking longer than usual. Close this and look again later.
            </p>
          } @else {
            <cd-skeleton [lines]="2" />
          }
        } @else if (current.status === 'failed') {
          <p class="cd-form-error" role="alert">{{ failure() }}</p>
        }
      } @else {
        <p>There is no summary yet. One is written soon after a file is ready.</p>
      }
      <div class="cd-actions">
        @if (canRequest()) {
          <button
            cd-button
            variant="secondary"
            type="button"
            [busy]="asking()"
            [disabled]="!canAsk()"
            (click)="ask()"
          >
            {{ hasSummary() ? 'Write again' : 'Write summary' }}
          </button>
        }
        <button #closeButton cd-button variant="secondary" type="button" (click)="dismissed.emit()">
          Close
        </button>
      </div>
      @if (askError(); as message) {
        <p class="cd-form-error" role="alert">{{ message }}</p>
      }
    </cd-dialog>
  `,
})
export class SummaryDialogComponent {
  readonly file = input.required<FileRead>();
  readonly dismissed = output<void>();

  protected readonly asking = signal(false);
  /** It was still not there when the refreshing gave up: say so instead of waiting for ever. */
  protected readonly stalled = signal(false);
  protected readonly askError = signal<string | null>(null);

  private readonly api = inject(SummaryApi);
  private readonly resolver = inject(ErrorResolver);
  private readonly destroyRef = inject(DestroyRef);
  // A new object means "fetch again". `quiet` is a refresh the person did not ask for. `seed` is an
  // answer the server has just given, shown at once instead of asking for it again.
  private readonly trigger = signal<{ readonly quiet: boolean; readonly seed?: FileSummary }>({
    quiet: false,
  });
  private polls = 0;
  private latest: View = LOADING;
  // Read with `viewChild` on the plain element, so it is the button and not a component.
  private readonly closeButton = viewChild.required('closeButton', {
    read: ElementRef<HTMLButtonElement>,
  });

  protected readonly view = toSignal(
    toObservable(this.trigger).pipe(
      switchMap((trigger) => this.fetch(trigger.quiet, trigger.seed)),
    ),
    { initialValue: LOADING },
  );

  protected readonly summary = computed(() => {
    const view = this.view();
    return view.status === 'loaded' ? view.summary : null;
  });
  protected readonly errorText = computed(() => {
    const view = this.view();
    return view.status === 'error' ? view.message : null;
  });
  protected readonly failure = computed(() => failureText(this.summary()?.error_code ?? null));
  protected readonly hasSummary = computed(() => !!this.summary()?.summary);
  protected readonly canRequest = computed(() => canWrite(this.file().role));
  protected readonly canAsk = computed(
    () =>
      this.summary()?.status !== 'pending' && !this.asking() && this.view().status !== 'loading',
  );
  protected readonly announcement = computed(() => {
    switch (this.summary()?.status) {
      case 'pending':
        return 'Writing the summary';
      case 'ready':
        return 'Summary ready';
      default:
        return '';
    }
  });

  constructor() {
    // While nothing is there yet, or it is still being written, look again after a pause.
    toObservable(this.view)
      .pipe(
        switchMap((view) => this.nextPoll(view)),
        takeUntilDestroyed(),
      )
      .subscribe((next) => (next === STALLED ? this.stalled.set(true) : this.refresh()));
  }

  protected reload(): void {
    this.stalled.set(false);
    this.trigger.set({ quiet: false });
    this.keepFocus();
  }

  protected ask(): void {
    if (this.asking() || !this.canAsk()) {
      return;
    }
    this.asking.set(true);
    this.askError.set(null);
    this.keepFocus(); // this button turns off while it is working
    this.api
      .request(this.file().id)
      .pipe(
        finalize(() => this.asking.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        // The answer is the pending summary (the old text is still in it): show it at once, and
        // the refresh takes over from there.
        next: (pending) => {
          this.polls = 0;
          this.stalled.set(false);
          this.trigger.set({ quiet: true, seed: pending });
        },
        error: (error: unknown) => this.askError.set(this.resolver.resolve(error).message),
      });
  }

  /** The button that was pressed disappears or turns off: focus must not fall out of the dialog. */
  private keepFocus(): void {
    this.closeButton().nativeElement.focus();
  }

  private refresh(): void {
    this.polls += 1;
    this.trigger.set({ quiet: true });
  }

  private nextPoll(view: View): Observable<unknown> {
    const waiting =
      view.status === 'none' || (view.status === 'loaded' && view.summary.status === 'pending');
    if (!waiting) {
      return EMPTY;
    }
    const delay = pollDelayMs(this.polls);
    // Asynchronous even when giving up: a signal must not be written while the view is changing.
    return delay === null ? timer(0).pipe(map(() => STALLED)) : timer(delay);
  }

  private fetch(quiet: boolean, seed?: FileSummary): Observable<View> {
    if (seed) {
      this.latest = { status: 'loaded', summary: seed };
      return of(this.latest);
    }
    if (!quiet) {
      this.polls = 0;
    }
    const loaded = this.api.get(this.file().id).pipe(
      map((summary): View => ({ status: 'loaded', summary })),
      catchError((error: unknown) => {
        const resolved = this.resolver.resolve(error);
        if (resolved.code === 'summary_not_found') {
          return of<View>({ status: 'none' });
        }
        // A failed refresh keeps what is on screen (a copy, so the next one is still scheduled).
        return of<View>(
          quiet ? { ...this.latest } : { status: 'error', message: resolved.message },
        );
      }),
    );
    const view = loaded.pipe(
      map((next) => {
        this.latest = next;
        return next;
      }),
    );
    return quiet ? view : view.pipe(startWith(LOADING));
  }
}
