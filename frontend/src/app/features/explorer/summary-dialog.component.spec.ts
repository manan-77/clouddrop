import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';

import { type CallerRole, type FileRead, type FileSummary } from '@core/api/models';
import { MAX_POLLS, POLL_DELAYS_MS } from '@core/api/polling';
import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { failureText, SummaryDialogComponent } from './summary-dialog.component';

const URL = '/api/v1/files/f1/summary';
const FILE = (role: CallerRole = 'owner'): FileRead => ({
  id: 'f1',
  folder_id: null,
  name: 'plan.pdf',
  content_type: 'application/pdf',
  size_bytes: 10,
  status: 'ready',
  created_at: '2026-01-02T10:00:00Z',
  updated_at: '2026-01-02T10:00:00Z',
  role,
});
const summary = (extra: Partial<FileSummary> = {}): FileSummary => ({
  status: 'ready',
  summary: 'A supply agreement between two companies.',
  category: 'Contract',
  tags: ['supply', 'payment'],
  partial: false,
  model: 'qwen3:4b-instruct',
  prompt_version: '2',
  error_code: null,
  generated_at: '2026-01-02T10:00:00Z',
  ...extra,
});
const NOT_FOUND = ENVELOPE('summary_not_found');

describe('SummaryDialogComponent', () => {
  let fixture: ComponentFixture<SummaryDialogComponent>;
  let backend: HttpTestingController;
  const root = () => fixture.nativeElement as HTMLElement;
  const text = (selector: string) => root().querySelector(selector)?.textContent?.trim() ?? '';
  const button = (label: string) =>
    [...root().querySelectorAll('button')].find((b) => b.textContent?.trim() === label) as
      HTMLButtonElement | undefined;
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const wait = async (ms: number) => {
    await vi.advanceTimersByTimeAsync(ms);
    await settle();
  };
  const open = async (role: CallerRole = 'owner') => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SummaryDialogComponent);
    fixture.componentRef.setInput('file', FILE(role));
    await settle();
  };
  const answer = async (body: FileSummary | null, status = 200) => {
    const request = backend.expectOne(URL);
    if (body) {
      request.flush(body);
    } else {
      request.flush(NOT_FOUND, { status, statusText: 'x' });
    }
    await settle();
  };

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    backend.verify();
  });

  it('showsAPlaceholder_thenTheSummaryCategoryAndTags', async () => {
    await open();
    expect(root().querySelector('cd-skeleton')).not.toBeNull();
    await answer(summary());
    expect(text('.text')).toBe('A supply agreement between two companies.');
    expect([...root().querySelectorAll('.chip')].map((c) => c.textContent?.trim())).toEqual([
      'Contract',
      'supply',
      'payment',
    ]);
    expect(text('[role="status"]')).toBe('Summary ready');
    expect(root().querySelector('cd-skeleton')).toBeNull();
    expect(text('cd-dialog')).toContain('Summary of plan.pdf');
  });

  it('everythingIsShownAsText_neverAsHtml', async () => {
    await open();
    await answer(summary({ summary: '<img src=x onerror=alert(1)>', tags: ['<b>x</b>'] }));
    expect(root().querySelector('.text img, .chip b')).toBeNull();
    expect(text('.text')).toBe('<img src=x onerror=alert(1)>');
  });

  it('aLongDocumentSaysOnlyTheStartWasRead', async () => {
    await open();
    await answer(summary({ partial: true }));
    expect(text('cd-dialog')).toContain('only the start was read');
  });

  describe('nothing written yet', () => {
    it('saysSo_offersToWriteOneToSomeoneWhoCan_andNotToAViewer', async () => {
      await open('owner');
      await answer(null, 404);
      expect(text('cd-dialog')).toContain('There is no summary yet');
      expect(button('Write summary')).toBeDefined();
    });

    it('aViewerCanOnlyReadIt', async () => {
      await open('viewer');
      await answer(summary());
      expect(button('Write again')).toBeUndefined();
      expect(button('Write summary')).toBeUndefined();
      expect(button('Close')).toBeDefined();
    });

    it('looksAgainAfterAPause_andShowsItWhenItAppears', async () => {
      await open();
      await answer(null, 404);
      await wait(POLL_DELAYS_MS[0] - 1);
      backend.expectNone(URL);
      await wait(1);
      await answer(summary());
      expect(text('.text')).toContain('supply agreement');
    });
  });

  describe('being written', () => {
    it('showsAPlaceholderWithoutTextYet_andRefreshesQuietlyUntilItIsReady', async () => {
      await open();
      await answer(summary({ status: 'pending', summary: null, category: null, tags: [] }));
      expect(text('cd-dialog')).toContain('The summary is being written.');
      expect(root().querySelector('cd-skeleton')).not.toBeNull();
      expect(text('[role="status"]')).toBe('Writing the summary');
      await wait(POLL_DELAYS_MS[0]);
      const refresh = backend.expectOne(URL);
      // A refresh the person did not ask for is not a loading screen: the dialog keeps its content.
      expect(text('cd-dialog')).toContain('The summary is being written.');
      refresh.flush(summary());
      await settle();
      expect(text('.text')).toContain('supply agreement');
      await wait(120_000);
      backend.expectNone(URL);
    });

    it('theOldTextStaysWhileANewOneIsWritten', async () => {
      await open();
      await answer(summary({ status: 'pending' }));
      expect(text('.text')).toContain('supply agreement');
      expect(text('cd-dialog')).toContain('A new summary is being written.');
      expect(button('Write again')!.disabled).toBe(true);
    });

    it('stopsRefreshingAfterTheLimit', async () => {
      await open();
      await answer(summary({ status: 'pending' }));
      for (let polls = 0; polls < MAX_POLLS; polls += 1) {
        await wait(POLL_DELAYS_MS.at(-1)!);
        await answer(summary({ status: 'pending' }));
      }
      await wait(600_000);
      backend.expectNone(URL);
    });

    it('aFailedRefreshKeepsWhatIsShown_andRefreshingGoesOn', async () => {
      await open();
      await answer(summary({ status: 'pending' }));
      await wait(POLL_DELAYS_MS[0]);
      backend.expectOne(URL).flush(ENVELOPE('internal_error'), { status: 500, statusText: 'x' });
      await settle();
      expect(root().querySelector('[role="alert"]')).toBeNull();
      expect(text('.text')).toContain('supply agreement');
      await wait(POLL_DELAYS_MS[1]);
      await answer(summary());
      expect(text('[role="status"]')).toBe('Summary ready');
    });
  });

  describe('failed', () => {
    it.each([
      ['no_text', 'no text in this file'],
      ['bad_output', 'could not be written this time'],
      ['chat_unavailable', 'assistant was not available'],
      ['something_new', 'could not be written.'],
    ])('code_%s_isExplainedInWords', async (code, expected) => {
      await open();
      await answer(
        summary({ status: 'failed', summary: null, category: null, tags: [], error_code: code }),
      );
      expect(text('[role="alert"]')).toContain(expected);
      expect(button('Write summary')).toBeDefined();
    });

    it('aCodeThatNamesSomethingOnEveryObjectIsNotMistakenForAKnownOne', () => {
      expect(failureText('constructor')).toBe('The summary could not be written.');
      expect(failureText('__proto__')).toBe('The summary could not be written.');
      expect(failureText(null)).toBe('The summary could not be written.');
    });

    it('theOldSummaryIsStillShownWhenAnewOneFailed', async () => {
      await open();
      await answer(summary({ status: 'failed', error_code: 'bad_output' }));
      expect(text('.text')).toContain('supply agreement');
      expect(text('[role="alert"]')).toContain('could not be written this time');
    });
  });

  describe('asking for a new one', () => {
    it('posts_keepsTheTextOnScreen_andFollowsItUntilReady', async () => {
      await open();
      await answer(summary());
      button('Write again')!.click();
      await settle();
      backend
        .expectOne(URL)
        .flush(summary({ status: 'pending' }), { status: 202, statusText: 'x' });
      await settle();
      // The server's answer is shown at once: the pending note, the old text, and no second request.
      expect(root().querySelector('cd-skeleton')).not.toBeNull();
      expect(text('cd-dialog')).toContain('A new summary is being written.');
      expect(text('.text')).toContain('supply agreement');
      expect(button('Write again')!.disabled).toBe(true);
      backend.expectNone(URL);
      await wait(POLL_DELAYS_MS[0]);
      await answer(summary({ summary: 'A newer summary.' }));
      expect(text('.text')).toBe('A newer summary.');
    });

    it('aDoubleClickMakesOneRequest', async () => {
      await open();
      await answer(summary());
      const again = button('Write again')!;
      again.click();
      again.click();
      await settle();
      const posts = backend.match(URL).filter((r) => r.request.method === 'POST');
      expect(posts).toHaveLength(1);
      posts[0].flush(summary({ status: 'pending' }), { status: 202, statusText: 'x' });
      await settle();
    });

    it.each([
      [429, 'rate_limited', 'Too many attempts'],
      [409, 'file_not_ready', 'not available yet'],
    ])('aRefusal_%s_isShown_andTheButtonWorksAgain', async (status, code, expected) => {
      await open();
      await answer(summary());
      button('Write again')!.click();
      await settle();
      backend.expectOne(URL).flush(ENVELOPE(code), { status, statusText: 'x' });
      await settle();
      expect(text('[role="alert"]')).toContain(expected);
      expect(text('.text')).toContain('supply agreement');
      expect(button('Write again')!.disabled).toBe(false);
    });
  });

  describe('failures to load', () => {
    it('aFailure_isShownWithTryAgain_andTryAgainLoadsAgain', async () => {
      await open();
      backend.expectOne(URL).flush(ENVELOPE('internal_error'), { status: 500, statusText: 'x' });
      await settle();
      expect(text('[role="alert"]')).toContain('Something went wrong');
      button('Try again')!.click();
      await settle();
      expect(root().querySelector('cd-skeleton')).not.toBeNull();
      await answer(summary());
      expect(text('.text')).toContain('supply agreement');
    });

    it('anErrorIsNotRefreshedOnItsOwn', async () => {
      await open();
      backend.expectOne(URL).flush(ENVELOPE('internal_error'), { status: 500, statusText: 'x' });
      await settle();
      await wait(120_000);
      backend.expectNone(URL);
    });
  });

  it('closeAsksTheOwnerToClose', async () => {
    await open();
    await answer(summary());
    let closed = 0;
    fixture.componentInstance.dismissed.subscribe(() => (closed += 1));
    button('Close')!.click();
    expect(closed).toBe(1);
  });

  it('leavingCancelsTheRequestAndTheTimer', async () => {
    await open();
    const request = backend.expectOne(URL);
    fixture.destroy();
    expect(request.cancelled).toBe(true);
  });

  it('leavingWhileWaitingToRefreshSendsNothingMore', async () => {
    await open();
    await answer(summary({ status: 'pending' }));
    fixture.destroy();
    await vi.advanceTimersByTimeAsync(60_000);
    backend.expectNone(URL);
  });
});
