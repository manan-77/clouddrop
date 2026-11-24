import { HttpErrorResponse, HttpEventType } from '@angular/common/http';
import { HttpTestingController, type TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { AnswersApi, AnswerStreamError, readEvents } from './answers-api.service';
import { type AnswerEvent, type Citation } from './models';

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
const DONE = frame({ type: 'done', citations: [CITATION], cut_off: false });

describe('readEvents', () => {
  it('returnsEveryCompleteEvent_andWhereItStopped', () => {
    const text = TOKEN('a') + TOKEN('b');
    const read = readEvents(text, 0);
    expect(read.events).toEqual([
      { type: 'token', text: 'a' },
      { type: 'token', text: 'b' },
    ]);
    expect(read.consumed).toBe(text.length);
  });

  it('leavesHalfAnEventForTheNextCall', () => {
    const whole = TOKEN('hello');
    const cut = whole.length - 5;
    const first = readEvents(whole.slice(0, cut), 0);
    expect(first.events).toEqual([]);
    expect(first.consumed).toBe(0);
    expect(readEvents(whole, first.consumed).events).toEqual([{ type: 'token', text: 'hello' }]);
  });

  it('startsWhereTheLastCallStopped_soNothingRepeats', () => {
    const text = TOKEN('a') + TOKEN('b');
    const first = readEvents(text, 0);
    expect(readEvents(text, first.consumed).events).toEqual([]);
  });

  it('ignoresFramesThatAreNotData_likeAComment', () => {
    expect(readEvents(': keep-alive\n\n' + TOKEN('a'), 0).events).toHaveLength(1);
  });

  it('keepsNewlinesInsideTheTextOfAToken', () => {
    expect(readEvents(TOKEN('line one\nline two'), 0).events).toEqual([
      { type: 'token', text: 'line one\nline two' },
    ]);
  });

  it('readsADoneEventWithAMissingPage', () => {
    const done = frame({
      type: 'done',
      citations: [{ ...CITATION, page: null }],
      cut_off: true,
    });
    expect(readEvents(done, 0).events).toEqual([
      { type: 'done', citations: [{ ...CITATION, page: null }], cut_off: true },
    ]);
  });

  it.each([
    ['not json', 'data: nope\n\n'],
    ['an unknown type', frame({ type: 'surprise' })],
    ['a token without text', frame({ type: 'token' })],
    ['a token whose text is a number', frame({ type: 'token', text: 5 })],
    ['a done without a flag', frame({ type: 'done', citations: [] })],
    [
      'a citation without a file name',
      frame({ type: 'done', citations: [{ ...CITATION, file_name: 1 }], cut_off: false }),
    ],
    ['an error without a code', frame({ type: 'error' })],
    ['a list', 'data: [1]\n\n'],
  ])('refuses_%s', (_name, text) => {
    expect(() => readEvents(text, 0)).toThrow(AnswerStreamError);
  });
});

describe('AnswersApi', () => {
  let api: AnswersApi;
  let backend: HttpTestingController;
  let events: AnswerEvent[];
  let failure: unknown;
  let completed: boolean;
  const progress = (request: TestRequest, partialText: string) =>
    request.event({
      type: HttpEventType.DownloadProgress,
      loaded: partialText.length,
      partialText,
    });
  const start = (question = 'when is the invoice due'): TestRequest => {
    api.ask(question).subscribe({
      next: (event) => events.push(event),
      error: (error: unknown) => (failure = error),
      complete: () => (completed = true),
    });
    return backend.expectOne(URL);
  };

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    api = TestBed.inject(AnswersApi);
    backend = TestBed.inject(HttpTestingController);
    events = [];
    failure = undefined;
    completed = false;
  });
  afterEach(() => backend.verify());

  it('ask_sendsTheQuestionInTheBodyAndNotInTheUrl', () => {
    const request = start('private words');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ question: 'private words' });
    expect(request.request.urlWithParams).toBe(URL);
    request.flush(DONE);
  });

  it('ask_givesEachEventAsItArrives_notAllAtTheEnd', () => {
    const request = start();
    progress(request, TOKEN('Due '));
    expect(events).toEqual([{ type: 'token', text: 'Due ' }]);
    progress(request, TOKEN('Due ') + TOKEN('on 5 March'));
    expect(events.map((e) => (e.type === 'token' ? e.text : e.type))).toEqual([
      'Due ',
      'on 5 March',
    ]);
    expect(completed).toBe(false);
    request.flush(TOKEN('Due ') + TOKEN('on 5 March') + DONE);
    expect(events.at(-1)?.type).toBe('done');
    expect(completed).toBe(true);
  });

  it('ask_anEventSplitAcrossTwoProgressUpdatesIsDeliveredOnceWhole', () => {
    const request = start();
    const all = TOKEN('whole');
    progress(request, all.slice(0, 12));
    expect(events).toEqual([]);
    progress(request, all);
    request.flush(all + DONE);
    expect(events.filter((e) => e.type === 'token')).toHaveLength(1);
  });

  it('ask_theFinalResponseDoesNotRepeatWhatProgressAlreadyGave', () => {
    const request = start();
    progress(request, TOKEN('a') + DONE);
    request.flush(TOKEN('a') + DONE);
    expect(events.map((e) => e.type)).toEqual(['token', 'done']);
  });

  it('ask_anErrorEventEndsTheStreamWithoutFailingTheRequest', () => {
    const request = start();
    request.flush(TOKEN('Du') + frame({ type: 'error', code: 'chat_unavailable' }));
    expect(events.at(-1)).toEqual({ type: 'error', code: 'chat_unavailable' });
    expect(failure).toBeUndefined();
    expect(completed).toBe(true);
  });

  it('ask_aStreamThatEndsWithoutDoneOrErrorIsAFailure_notAShortAnswer', () => {
    start().flush(TOKEN('half an ans'));
    expect(failure).toBeInstanceOf(AnswerStreamError);
  });

  it('ask_garbageInTheStreamIsAFailure', () => {
    start().flush('data: {oops\n\n');
    expect(failure).toBeInstanceOf(AnswerStreamError);
  });

  it('ask_aRefusedRequestKeepsTheServersErrorCode_evenThoughTheBodyWasReadAsText', () => {
    start().flush(JSON.stringify(ENVELOPE('rate_limited')), { status: 429, statusText: 'x' });
    expect(failure).toBeInstanceOf(HttpErrorResponse);
    expect((failure as HttpErrorResponse).status).toBe(429);
    expect(((failure as HttpErrorResponse).error as { error: { code: string } }).error.code).toBe(
      'rate_limited',
    );
  });

  it('ask_aFailureThatIsNotJsonIsPassedOnAsItWas', () => {
    start().flush('<html>bad gateway</html>', { status: 502, statusText: 'x' });
    expect(failure).toBeInstanceOf(HttpErrorResponse);
    expect((failure as HttpErrorResponse).error).toBe('<html>bad gateway</html>');
  });

  it('ask_unsubscribingCancelsTheRequest', () => {
    const subscription = api.ask('x').subscribe();
    const request = backend.expectOne(URL);
    subscription.unsubscribe();
    expect(request.cancelled).toBe(true);
  });
});
