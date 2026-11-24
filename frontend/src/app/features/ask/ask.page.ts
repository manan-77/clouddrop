import {
  ChangeDetectionStrategy,
  Component,
  computed,
  type ElementRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import {
  catchError,
  exhaustMap,
  map,
  merge,
  type Observable,
  of,
  scan,
  startWith,
  Subject,
  takeWhile,
} from 'rxjs';

import { AnswersApi } from '@core/api/answers-api.service';
import { type AnswerEvent, type Citation } from '@core/api/models';
import { fileDownloads } from '@core/download/file-downloads';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { IsInPipe } from '@shared/pipes/is-in.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

/** The longest question the server accepts (docs/api.md, Answers). */
export const MAX_QUESTION_CHARS = 500;

interface AnswerState {
  readonly status: 'idle' | 'answering' | 'done' | 'stopped' | 'error';
  readonly text: string;
  /** Only what the server verified, sent with the end of the answer. */
  readonly citations: readonly Citation[];
  readonly cutOff: boolean;
  readonly error: string | null;
}

const IDLE: AnswerState = { status: 'idle', text: '', citations: [], cutOff: false, error: null };
const ANSWERING: AnswerState = { ...IDLE, status: 'answering' };

type Step =
  | { readonly kind: 'event'; readonly event: AnswerEvent }
  | { readonly kind: 'failed'; readonly message: string }
  | { readonly kind: 'stop' };

/**
 * Ask a question about your files and watch the answer being written. The question stays in this
 * component: it is never put in the address bar, storage or a log. The answer is shown as plain
 * text, never as HTML.
 */
@Component({
  selector: 'cd-ask-page',
  imports: [ButtonComponent, EmptyStateComponent, IsInPipe, SkeletonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    .box {
      margin-bottom: var(--cd-space-5);
    }
    textarea.cd-input {
      resize: vertical;
    }
    .actions {
      display: flex;
      gap: var(--cd-space-3);
    }
    .answer {
      display: grid;
      gap: var(--cd-space-3);
      padding: var(--cd-space-4);
      border: 1px solid var(--cd-border);
      border-radius: var(--cd-radius-md);
      background: var(--cd-surface);
    }
    .text {
      margin: 0;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }
    .sources {
      display: grid;
      gap: var(--cd-space-2);
      margin: var(--cd-space-3) 0 0;
      padding: 0;
      list-style: none;
    }
    .source {
      display: flex;
      flex-wrap: wrap;
      gap: var(--cd-space-2) var(--cd-space-4);
      align-items: center;
      justify-content: space-between;
      padding: var(--cd-space-3);
      border: 1px solid var(--cd-border);
      border-radius: var(--cd-radius-md);
    }
    .name {
      font-weight: 600;
      overflow-wrap: anywhere;
    }
    .meta {
      margin-inline-start: var(--cd-space-2);
      color: var(--cd-text-muted);
      font-size: var(--cd-font-size-sm);
    }
    .title {
      margin: var(--cd-space-5) 0 var(--cd-space-2);
    }
  `,
  template: `
    <div class="cd-toolbar">
      <h1>Ask</h1>
    </div>
    <form class="cd-form box" (submit)="submit($event)">
      <div class="cd-field">
        <label for="ask-box">Ask a question about your files</label>
        <textarea
          #askBox
          id="ask-box"
          class="cd-input"
          rows="3"
          [attr.maxlength]="maxChars"
          aria-describedby="ask-hint"
          [value]="question()"
          (input)="typed($event)"
          (keydown.control.enter)="submit($event)"
          (keydown.meta.enter)="submit($event)"
        ></textarea>
        <p id="ask-hint" class="cd-hint">
          Answers use only files you can open. Up to {{ maxChars }} characters. Press Ctrl+Enter to
          ask. Your question is not saved.
        </p>
      </div>
      <div class="actions">
        <button cd-button type="submit" [busy]="answering()" [disabled]="!canAsk()">Ask</button>
        @if (answering()) {
          <button cd-button variant="secondary" type="button" (click)="stop()">Stop</button>
        }
      </div>
    </form>
    @if (downloads.error(); as message) {
      <p class="cd-form-error" role="alert">{{ message }}</p>
    }
    <p class="cd-visually-hidden" role="status">{{ announcement() }}</p>
    @if (answer().status === 'idle') {
      <cd-empty-state
        title="Ask about your files"
        description="Ask in your own words. The answer is written from your files and lists where it came from."
      />
    } @else {
      <section class="answer" aria-label="Answer" [attr.aria-busy]="answering()">
        @if (answer().text) {
          <p class="text">{{ answer().text }}</p>
        } @else if (answering()) {
          <cd-skeleton [lines]="3" />
        }
        @if (answer().cutOff) {
          <p class="cd-hint">The answer stopped because it reached the length limit.</p>
        }
        @if (answer().status === 'stopped') {
          <p class="cd-hint">Stopped.</p>
        }
        @if (answer().error; as message) {
          <p class="cd-form-error" role="alert">{{ message }}</p>
        }
      </section>
      @if (answer().citations.length > 0) {
        <h2 class="title">Sources</h2>
        <ul class="sources" aria-label="Sources">
          @for (source of answer().citations; track source.chunk_id) {
            <li class="source">
              <span>
                <span class="name">{{ source.file_name }}</span>
                <span class="meta"
                  >[{{ source.label }}]{{
                    source.page === null ? '' : ', page ' + source.page
                  }}</span
                >
              </span>
              <button
                cd-button
                variant="secondary"
                type="button"
                [busy]="source.file_id | isIn: downloads.busy()"
                [attr.aria-label]="'Download ' + source.file_name"
                (click)="downloads.start(source.file_id)"
              >
                Download
              </button>
            </li>
          }
        </ul>
      }
    }
  `,
})
export class AskPage {
  protected readonly maxChars = MAX_QUESTION_CHARS;
  protected readonly question = signal('');
  protected readonly downloads = fileDownloads();

  // Read with `viewChild` on a plain element, so it is the element and not a component.
  private readonly box = viewChild.required<ElementRef<HTMLTextAreaElement>>('askBox');
  private readonly api = inject(AnswersApi);
  private readonly resolver = inject(ErrorResolver);
  private readonly asked = new Subject<string>();
  private readonly stopped = new Subject<void>();

  // exhaustMap: a question asked while one is being answered is ignored (the button is off, but
  // Ctrl+Enter is not). Leaving the page unsubscribes, which cancels the request.
  protected readonly answer = toSignal(
    this.asked.pipe(exhaustMap((question) => this.answerTo(question))),
    { initialValue: IDLE },
  );

  protected readonly answering = computed(() => this.answer().status === 'answering');
  protected readonly canAsk = computed(() => this.question().trim() !== '' && !this.answering());
  /** Spoken, not shown: the text itself is not read out piece by piece. */
  protected readonly announcement = computed(() => {
    const state = this.answer();
    switch (state.status) {
      case 'answering':
        return 'Answering';
      case 'stopped':
        return 'Stopped';
      case 'done': {
        const count = state.citations.length;
        return count === 0
          ? 'Answer ready'
          : `Answer ready, ${count} ${count === 1 ? 'source' : 'sources'}`;
      }
      default:
        return '';
    }
  });

  protected typed(event: Event): void {
    this.question.set((event.target as HTMLTextAreaElement).value);
  }

  protected submit(event: Event): void {
    event.preventDefault();
    const question = this.question().trim();
    if (question === '' || this.answering()) {
      return;
    }
    this.downloads.clearError();
    this.asked.next(question);
    this.focusQuestion();
  }

  protected stop(): void {
    this.stopped.next();
    this.focusQuestion();
  }

  /** The Ask button turns off and the Stop button goes away: focus must not fall to the page top. */
  private focusQuestion(): void {
    this.box().nativeElement.focus();
  }

  private answerTo(question: string): Observable<AnswerState> {
    const steps = merge(
      this.api.ask(question).pipe(
        map((event): Step => ({ kind: 'event', event })),
        catchError((error: unknown) =>
          of<Step>({ kind: 'failed', message: this.resolver.resolve(error).message }),
        ),
      ),
      this.stopped.pipe(map((): Step => ({ kind: 'stop' }))),
    );
    return steps.pipe(
      scan((state, step) => this.apply(state, step), ANSWERING),
      startWith(ANSWERING),
      // The last state (done, stopped or failed) is passed on, then this answer is over, which
      // also drops the Stop listener and the request.
      takeWhile((state) => state.status === 'answering', true),
    );
  }

  private apply(state: AnswerState, step: Step): AnswerState {
    if (step.kind === 'stop') {
      return { ...state, status: 'stopped' };
    }
    if (step.kind === 'failed') {
      return { ...state, status: 'error', error: step.message };
    }
    const { event } = step;
    switch (event.type) {
      case 'token':
        return { ...state, text: state.text + event.text };
      case 'done':
        return { ...state, status: 'done', citations: event.citations, cutOff: event.cut_off };
      case 'error':
        return { ...state, status: 'error', error: this.resolver.describe(event.code) };
    }
  }
}
