import { Location } from '@angular/common';
import { HttpEventType } from '@angular/common/http';
import { HttpTestingController, type TestRequest } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { type Citation } from '@core/api/models';
import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { DownloadService } from '@core/download/download.service';
import { AskPage } from './ask.page';

const URL = '/api/v1/answers';
const CITATION: Citation = {
  label: 's1',
  file_id: 'f1',
  file_name: 'bill.pdf',
  chunk_id: 'c1',
  page: 2,
};
const frame = (event: object) => `data: ${JSON.stringify(event)}\n\n`;
const TOKEN = (text: string) => frame({ type: 'token', text });
const done = (citations: Citation[] = [CITATION], cutOff = false) =>
  frame({ type: 'done', citations, cut_off: cutOff });

describe('AskPage', () => {
  const downloads = { start: vi.fn() };
  let fixture: ComponentFixture<AskPage>;
  let backend: HttpTestingController;
  const root = () => fixture.nativeElement as HTMLElement;
  const text = (selector: string) => root().querySelector(selector)?.textContent?.trim() ?? '';
  const box = () => root().querySelector('textarea') as HTMLTextAreaElement;
  const announcement = () => text('[role="status"]');
  const askButton = () => root().querySelector('button[type="submit"]') as HTMLButtonElement;
  const button = (label: string) =>
    [...root().querySelectorAll('button')].find(
      (b) => b.textContent?.trim() === label || b.getAttribute('aria-label') === label,
    ) as HTMLButtonElement | undefined;
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const type = async (words: string) => {
    box().value = words;
    box().dispatchEvent(new Event('input'));
    await settle();
  };
  const ask = async (question = 'when is the invoice due'): Promise<TestRequest> => {
    await type(question);
    askButton().click();
    await settle();
    return backend.expectOne(URL);
  };
  const progress = async (request: TestRequest, partialText: string) => {
    request.event({
      type: HttpEventType.DownloadProgress,
      loaded: partialText.length,
      partialText,
    });
    await settle();
  };
  const finish = async (request: TestRequest, body: string) => {
    request.flush(body);
    await settle();
  };

  beforeEach(async () => {
    downloads.start.mockReset();
    TestBed.configureTestingModule({
      providers: [
        ...provideAuthTesting(),
        provideRouter([]),
        { provide: DownloadService, useValue: downloads },
      ],
    });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AskPage);
    await settle();
  });
  afterEach(() => backend.verify());

  it('nothingAskedYet_invitesAQuestion_andTheAskButtonIsOff', () => {
    expect(text('cd-empty-state')).toContain('Ask about your files');
    expect(askButton().disabled).toBe(true);
    expect(announcement()).toBe('');
  });

  it('theAskButtonStaysOffForOnlySpaces_andNothingIsSent', async () => {
    await type('     ');
    expect(askButton().disabled).toBe(true);
    box().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true }));
    await settle();
    backend.expectNone(URL);
  });

  it('asking_sendsTheTrimmedQuestionInTheBody_andShowsAPlaceholderUntilTheFirstWords', async () => {
    const request = await ask('  when is the invoice due  ');
    expect(request.request.body).toEqual({ question: 'when is the invoice due' });
    expect(root().querySelector('cd-skeleton')).not.toBeNull();
    expect(announcement()).toBe('Answering');
    expect(button('Stop')).toBeDefined();
    expect(askButton().disabled).toBe(true);
    await finish(request, done([]));
  });

  it('theAnswerGrowsAsWordsArrive_andSourcesAppearWhenItIsDone', async () => {
    const request = await ask();
    await progress(request, TOKEN('It is due '));
    expect(text('.text')).toBe('It is due');
    expect(root().querySelector('cd-skeleton')).toBeNull();
    expect(root().querySelector('.sources')).toBeNull();
    await progress(request, TOKEN('It is due ') + TOKEN('on 5 March [s1].'));
    expect(text('.text')).toBe('It is due on 5 March [s1].');
    await finish(request, TOKEN('It is due ') + TOKEN('on 5 March [s1].') + done());
    expect(announcement()).toBe('Answer ready, 1 source');
    expect(text('.sources')).toContain('bill.pdf');
    expect(text('.sources')).toContain('[s1], page 2');
    expect(button('Stop')).toBeUndefined();
    expect(askButton().disabled).toBe(false);
  });

  it('onlyTheSourcesTheServerListedAreShown_notLabelsThatMerelyAppearInTheText', async () => {
    const request = await ask();
    await finish(request, TOKEN('See [s1] and [s9].') + done([CITATION]));
    expect([...root().querySelectorAll('.source .name')].map((n) => n.textContent)).toEqual([
      'bill.pdf',
    ]);
  });

  it('theAnswerIsShownAsText_neverAsHtml', async () => {
    const request = await ask();
    await finish(request, TOKEN('<img src=x onerror=alert(1)> <b>bold</b>') + done([]));
    expect(root().querySelector('.text img, .text b')).toBeNull();
    expect(text('.text')).toBe('<img src=x onerror=alert(1)> <b>bold</b>');
  });

  it('aSourceNameIsShownAsText_neverAsHtml', async () => {
    const request = await ask();
    await finish(request, TOKEN('x') + done([{ ...CITATION, file_name: '<b>evil</b>.pdf' }]));
    expect(root().querySelector('.source b')).toBeNull();
    expect(text('.source .name')).toBe('<b>evil</b>.pdf');
  });

  it('aSourceWithoutAPageShowsNoPage', async () => {
    const request = await ask();
    await finish(request, TOKEN('x') + done([{ ...CITATION, page: null }]));
    expect(text('.source .meta')).toBe('[s1]');
  });

  it('twoSourcesAreAnnouncedInThePlural', async () => {
    const request = await ask();
    const two = [CITATION, { ...CITATION, label: 's2', chunk_id: 'c2' }];
    await finish(request, TOKEN('x') + done(two));
    expect(announcement()).toBe('Answer ready, 2 sources');
  });

  it('stop_cancelsTheRequest_keepsWhatWasWritten_andAllowsAnotherQuestion', async () => {
    const request = await ask();
    await progress(request, TOKEN('Half an'));
    button('Stop')!.click();
    await settle();
    expect(request.cancelled).toBe(true);
    expect(text('.text')).toBe('Half an');
    expect(text('.answer')).toContain('Stopped.');
    expect(announcement()).toBe('Stopped');
    expect(askButton().disabled).toBe(false);
    const next = await ask('another question');
    await finish(next, done([]));
  });

  it('aQuestionAskedWhileOneIsBeingAnswered_isIgnored_notALostAnswer', async () => {
    const request = await ask();
    await progress(request, TOKEN('first '));
    box().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true }));
    await settle();
    backend.expectNone(URL);
    expect(request.cancelled).toBe(false);
    expect(text('.text')).toBe('first');
    await finish(request, TOKEN('first ') + done([]));
  });

  it('twoAsksInTheSameInstant_makeOneRequest', async () => {
    await type('a question');
    const press = () =>
      box().dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, cancelable: true }),
      );
    press();
    press(); // before the screen has had a chance to update
    await settle();
    const request = backend.expectOne(URL);
    await finish(request, done([]));
  });

  it('afterAnAnswerAnotherQuestionStartsFresh_withNoOldTextOrSources', async () => {
    await finish(await ask(), TOKEN('old answer') + done());
    const next = await ask('a second question');
    expect(next.request.body).toEqual({ question: 'a second question' });
    expect(root().querySelector('.text')).toBeNull();
    expect(root().querySelector('.sources')).toBeNull();
    await finish(next, TOKEN('new') + done([]));
    expect(text('.text')).toBe('new');
  });

  it('ctrlEnterAsksFromTheKeyboard', async () => {
    await type('keyboard question');
    box().dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, cancelable: true }),
    );
    await settle();
    expect(backend.expectOne(URL).request.body).toEqual({ question: 'keyboard question' });
  });

  it('theOutputLimitIsExplained', async () => {
    await finish(await ask(), TOKEN('cut') + done([], true));
    expect(text('.answer')).toContain('reached the length limit');
  });

  describe('failures', () => {
    it.each([
      ['chat_unavailable', 503, 'The assistant is unavailable right now'],
      ['search_unavailable', 503, 'Search is unavailable right now'],
      ['question_too_long', 422, 'That question is too long'],
      ['rate_limited', 429, 'Too many attempts'],
    ])('%s_beforeTheAnswerStarts_showsAReadableMessage', async (code, status, expected) => {
      const request = await ask();
      request.flush(JSON.stringify(ENVELOPE(code)), { status, statusText: 'x' });
      await settle();
      expect(text('[role="alert"]')).toContain(expected);
      expect(root().querySelector('cd-skeleton')).toBeNull();
      expect(askButton().disabled).toBe(false);
    });

    it('anErrorEventPartWay_keepsWhatWasWritten_andSaysWhatWentWrong', async () => {
      const request = await ask();
      await finish(request, TOKEN('Due on') + frame({ type: 'error', code: 'chat_unavailable' }));
      expect(text('.text')).toBe('Due on');
      expect(text('[role="alert"]')).toContain('The assistant is unavailable right now');
      expect(root().querySelector('.sources')).toBeNull();
      expect(askButton().disabled).toBe(false);
    });

    it('aStreamThatJustStops_isAFailure_notASilentShortAnswer', async () => {
      await finish(await ask(), TOKEN('half'));
      expect(text('[role="alert"]')).toContain('Something went wrong');
      expect(text('.text')).toBe('half');
    });

    it('aNetworkFailure_isAReadableMessage', async () => {
      const request = await ask();
      request.error(new ProgressEvent('error'));
      await settle();
      expect(text('[role="alert"]')).toContain('Could not reach the server');
    });

    it('afterAFailureAnotherQuestionCanBeAsked', async () => {
      const request = await ask();
      request.flush(JSON.stringify(ENVELOPE('rate_limited')), { status: 429, statusText: 'x' });
      await settle();
      const next = await ask('try again');
      await finish(next, TOKEN('ok') + done([]));
      expect(text('.text')).toBe('ok');
      expect(root().querySelector('[role="alert"]')).toBeNull();
    });
  });

  it('aSourceCanBeDownloaded', async () => {
    await finish(await ask(), TOKEN('x') + done());
    button('Download bill.pdf')!.click();
    await settle();
    backend
      .expectOne('/api/v1/files/f1/download')
      .flush({ url: 'https://bucket.s3.amazonaws.com/x', expires_in: 300 });
    expect(downloads.start).toHaveBeenCalledWith('https://bucket.s3.amazonaws.com/x');
  });

  it('theQuestionNeverReachesTheAddressBar', async () => {
    await finish(await ask('private question'), TOKEN('x') + done([]));
    expect(TestBed.inject(Location).path()).toBe('');
  });

  it('leavingThePageCancelsTheRequest', async () => {
    const request = await ask();
    fixture.destroy();
    expect(request.cancelled).toBe(true);
  });
});
