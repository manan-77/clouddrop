import { Location } from '@angular/common';
import { HttpTestingController, type TestRequest } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { type SearchHit } from '@core/api/models';
import { DEFAULT_PAGE_SIZE } from '@core/api/pagination';
import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { DownloadService } from '@core/download/download.service';
import { SearchPage, TYPING_PAUSE_MS } from './search.page';

const SEARCH = (r: { url: string }) => r.url === '/api/v1/search';
const hit = (n: number, extra: Partial<SearchHit> = {}): SearchHit => ({
  file_id: `f${n}`,
  file_name: `doc${n}.pdf`,
  chunk_id: `c${n}`,
  page: n,
  snippet: `passage ${n}`,
  score: 0.8,
  ...extra,
});
const found = (items: SearchHit[], total = items.length, page = 1) => ({
  items,
  total,
  page,
  page_size: DEFAULT_PAGE_SIZE,
});

describe('SearchPage', () => {
  const downloads = { start: vi.fn() };
  let fixture: ComponentFixture<SearchPage>;
  let backend: HttpTestingController;
  const root = () => fixture.nativeElement as HTMLElement;
  const text = (selector: string) => root().querySelector(selector)?.textContent?.trim() ?? '';
  const input = () => root().querySelector('input') as HTMLInputElement;
  const announcement = () => text('[role="status"]');
  const results = () => [...root().querySelectorAll('.result')];
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const type = async (words: string) => {
    input().value = words;
    input().dispatchEvent(new Event('input'));
    await settle();
  };
  const pause = async (ms = TYPING_PAUSE_MS) => {
    await vi.advanceTimersByTimeAsync(ms);
    await settle();
  };
  const search = async (words: string): Promise<TestRequest> => {
    await type(words);
    await pause();
    return backend.expectOne(SEARCH);
  };
  const click = async (label: string) => {
    const button = [...root().querySelectorAll('button')].find(
      (b) => b.textContent?.trim() === label || b.getAttribute('aria-label') === label,
    );
    (button as HTMLButtonElement).click();
    await settle();
  };

  beforeEach(async () => {
    vi.useFakeTimers();
    downloads.start.mockReset();
    TestBed.configureTestingModule({
      providers: [
        ...provideAuthTesting(),
        provideRouter([]),
        { provide: DownloadService, useValue: downloads },
      ],
    });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SearchPage);
    await settle();
  });
  afterEach(() => {
    // First: a failing verify() must not leave fake timers behind for the next test.
    vi.useRealTimers();
    backend.verify();
  });

  it('nothingTypedYet_invitesASearch_andSendsNothing', async () => {
    await pause(5000);
    expect(text('cd-empty-state')).toContain('Search your files');
    expect(announcement()).toBe('');
  });

  it('typing_waitsForAPause_thenSendsOneRequest_withTheWordsOnlyInTheBody', async () => {
    await type('inv');
    await pause(100);
    await type('invoice due');
    await pause(TYPING_PAUSE_MS - 1);
    backend.expectNone(SEARCH);
    await pause(1);
    const request = backend.expectOne(SEARCH);
    expect(request.request.body).toEqual({ query: 'invoice due' });
    expect(request.request.params.get('page')).toBe('1');
    expect(request.request.params.get('page_size')).toBe(String(DEFAULT_PAGE_SIZE));
    expect(request.request.urlWithParams).not.toContain('invoice');
    request.flush(found([]));
  });

  it('whileSearching_showsAPlaceholderAndAnnouncesIt', async () => {
    const request = await search('invoice');
    expect(root().querySelector('cd-skeleton')).not.toBeNull();
    expect(announcement()).toBe('Searching');
    request.flush(found([hit(1)]));
  });

  it('results_showNameSnippetAndPage_andAnnounceTheCount', async () => {
    (await search('invoice')).flush(found([hit(1), hit(2, { page: null })]));
    await settle();
    expect(results()).toHaveLength(2);
    expect(results()[0].textContent).toContain('doc1.pdf');
    expect(results()[0].textContent).toContain('passage 1');
    expect(results()[0].textContent).toContain('Page 1');
    expect(results()[1].textContent).not.toContain('Page');
    expect(announcement()).toBe('2 files found');
    expect(root().querySelector('cd-skeleton')).toBeNull();
  });

  it('aSingleResult_isAnnouncedInTheSingular', async () => {
    (await search('invoice')).flush(found([hit(1)]));
    await settle();
    expect(announcement()).toBe('1 file found');
  });

  it('theSnippetIsShownAsText_neverAsHtml', async () => {
    (await search('x')).flush(
      found([hit(1, { snippet: '<img src=x onerror=alert(1)> <b>bold</b>' })]),
    );
    await settle();
    expect(root().querySelector('.snippet img, .snippet b')).toBeNull();
    expect(text('.snippet')).toBe('<img src=x onerror=alert(1)> <b>bold</b>');
  });

  it('noMatches_saysSoInsteadOfShowingNothing', async () => {
    (await search('zebra')).flush(found([]));
    await settle();
    expect(text('cd-empty-state')).toContain('No matching files');
    expect(announcement()).toBe('No matching files');
  });

  it('aNewerSearch_cancelsTheOlderOne_andOnlyItsAnswerIsShown', async () => {
    const older = await search('first');
    await type('second');
    await pause();
    expect(older.cancelled).toBe(true);
    backend.expectOne(SEARCH).flush(found([hit(2)]));
    await settle();
    expect(results().map((r) => r.querySelector('.name')?.textContent)).toEqual(['doc2.pdf']);
  });

  it('clearingTheBox_returnsToTheInvitation_andCancelsTheRequest', async () => {
    const request = await search('invoice');
    await type('');
    await pause();
    expect(request.cancelled).toBe(true);
    expect(text('cd-empty-state')).toContain('Search your files');
  });

  it('editingBackToEarlierWordsAfterEnter_isStillSearched_notLost', async () => {
    (await search('abc')).flush(found([hit(1)]));
    await settle();
    await type('xyz');
    input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
    backend.expectOne(SEARCH); // "xyz" is in flight
    await type('abc'); // edited back before the typing pause ended
    await pause();
    const again = backend.expectOne(SEARCH);
    expect(again.request.body).toEqual({ query: 'abc' });
    again.flush(found([hit(1)]));
    await settle();
    expect(input().value).toBe('abc');
  });

  it('onlySpaces_isNotASearch', async () => {
    await type('    ');
    await pause();
    backend.expectNone(SEARCH);
  });

  it('enter_searchesAtOnce_andThePauseThatFollowsDoesNotRepeatIt', async () => {
    await type('invoice');
    input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
    backend.expectOne(SEARCH).flush(found([hit(1)]));
    await pause();
    backend.expectNone(SEARCH);
  });

  it('enterWithTheSameWords_doesNotAskAgain', async () => {
    (await search('invoice')).flush(found([hit(1)]));
    await settle();
    input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
    backend.expectNone(SEARCH);
    expect(results()).toHaveLength(1);
  });

  it.each([
    ['search_unavailable', 503, 'Search is unavailable right now'],
    ['rate_limited', 429, 'Too many attempts'],
    ['internal_error', 500, 'Something went wrong on our side'],
  ])('failure_%s_showsAReadableMessageWithRetry', async (code, status, expected) => {
    (await search('invoice')).flush(ENVELOPE(code), { status, statusText: 'x' });
    await settle();
    expect(text('cd-error-state')).toContain(expected);
    expect(root().querySelector('cd-skeleton')).toBeNull();
    await click('Try again');
    backend.expectOne(SEARCH).flush(found([hit(1)]));
    await settle();
    expect(results()).toHaveLength(1);
    expect(root().querySelector('cd-error-state')).toBeNull();
  });

  describe('paging', () => {
    const firstPage = async () => {
      (await search('invoice')).flush(found([hit(1), hit(2)], DEFAULT_PAGE_SIZE * 3));
      await settle();
    };

    it('nextPage_asksForItWithTheSameWords_andKeepsTheListWhileLoading', async () => {
      await firstPage();
      await click('Next');
      const request = backend.expectOne(SEARCH);
      expect(request.request.params.get('page')).toBe('2');
      expect(request.request.body).toEqual({ query: 'invoice' });
      await settle(); // render the loading state before looking at the page
      // The list and the pager stay, so keyboard focus is not thrown away.
      expect(results()).toHaveLength(2);
      expect(root().querySelector('cd-pager')).not.toBeNull();
      expect(root().querySelector('cd-skeleton')).toBeNull();
      expect(root().querySelector('.results')?.getAttribute('aria-busy')).toBe('true');
      request.flush(found([hit(3)], DEFAULT_PAGE_SIZE * 3, 2));
      await settle();
      expect(results().map((r) => r.querySelector('.name')?.textContent)).toEqual(['doc3.pdf']);
      expect(root().querySelector('.results')?.getAttribute('aria-busy')).toBe('false');
    });

    it('aDifferentSearch_replacesTheOldListWithAPlaceholder_notStaleResults', async () => {
      await firstPage();
      await type('other words');
      await pause();
      expect(results()).toHaveLength(0);
      expect(root().querySelector('cd-skeleton')).not.toBeNull();
      backend.expectOne(SEARCH).flush(found([]));
    });

    it('aPagePastTheEnd_stepsBackToTheLastPageThatExists_once', async () => {
      await firstPage();
      await click('Next');
      backend.expectOne(SEARCH).flush(found([], 30, 2)); // results shrank to one page
      await settle();
      const back = backend.expectOne(SEARCH);
      expect(back.request.params.get('page')).toBe('1');
      back.flush(found([hit(1)], 30));
      await settle();
      backend.expectNone(SEARCH);
      expect(results()).toHaveLength(1);
    });

    it('aServerThatSaysThereAreResultsButSendsNone_neverMakesTheScreenLoopOnItsOwn', async () => {
      (await search('invoice')).flush(found([], 30)); // page 1 empty although the total is 30
      await settle();
      backend.expectNone(SEARCH);
      expect(text('cd-empty-state')).toContain('No matching files');
    });

    it('whilePastTheEndIsBeingCorrected_neverSaysThereAreNoMatches', async () => {
      await firstPage();
      await click('Next');
      backend.expectOne(SEARCH).flush(found([], 30, 2));
      await settle();
      const back = backend.expectOne(SEARCH);
      expect(root().querySelector('cd-empty-state')).toBeNull();
      expect(results()).toHaveLength(2); // the last good page stays until the right one arrives
      back.flush(found([hit(1)], 30));
    });

    it('theSameWordsAgainAfterClearingTheBox_startFresh_notFromAnOldPage', async () => {
      await firstPage();
      await click('Next');
      backend.expectOne(SEARCH).flush(found([hit(3)], DEFAULT_PAGE_SIZE * 3, 2));
      await settle();
      await type('');
      await pause();
      await type('invoice');
      await pause();
      const fresh = backend.expectOne(SEARCH);
      await settle();
      expect(fresh.request.params.get('page')).toBe('1');
      expect(results()).toHaveLength(0); // not page 2's list under a pager that says page 1
      expect(root().querySelector('cd-skeleton')).not.toBeNull();
      fresh.flush(found([hit(1)]));
    });

    it('theSameWordsAgainAfterOtherWordsWereAsked_startFresh_too', async () => {
      await firstPage();
      await click('Next');
      backend.expectOne(SEARCH).flush(found([hit(3)], DEFAULT_PAGE_SIZE * 3, 2));
      await settle();
      await type('other');
      await pause();
      const other = backend.expectOne(SEARCH); // still in flight
      await type('invoice');
      await pause();
      expect(other.cancelled).toBe(true);
      const fresh = backend.expectOne(SEARCH);
      await settle();
      expect(results()).toHaveLength(0);
      fresh.flush(found([hit(1)]));
    });

    it('retryingAfterAFailedPage_neverShowsAnOlderPageAsIfItWereCurrent', async () => {
      await firstPage();
      await click('Next');
      backend.expectOne(SEARCH).flush(ENVELOPE('internal_error'), { status: 500, statusText: 'x' });
      await settle();
      await click('Try again');
      const retried = backend.expectOne(SEARCH);
      await settle();
      expect(results()).toHaveLength(0);
      expect(root().querySelector('cd-skeleton')).not.toBeNull();
      expect(retried.request.params.get('page')).toBe('2');
    });
  });

  describe('opening a file', () => {
    it('download_asksForALinkAndHandsItToTheBrowser', async () => {
      (await search('invoice')).flush(found([hit(1)]));
      await settle();
      await click('Download doc1.pdf');
      backend
        .expectOne('/api/v1/files/f1/download')
        .flush({ url: 'https://bucket.s3.amazonaws.com/x', expires_in: 300 });
      expect(downloads.start).toHaveBeenCalledWith('https://bucket.s3.amazonaws.com/x');
    });

    it('download_failureShowsAMessage_andTheListStays', async () => {
      (await search('invoice')).flush(found([hit(1)]));
      await settle();
      await click('Download doc1.pdf');
      backend
        .expectOne('/api/v1/files/f1/download')
        .flush(ENVELOPE('file_not_ready'), { status: 409, statusText: 'x' });
      await settle();
      expect(text('[role="alert"]')).toContain('This file is not available yet.');
      expect(results()).toHaveLength(1);
    });
  });

  it('theWordsNeverReachTheAddressBar', async () => {
    (await search('private words')).flush(found([hit(1)]));
    await settle();
    expect(TestBed.inject(Location).path()).toBe('');
  });

  it('leavingThePageCancelsTheRequest', async () => {
    const request = await search('invoice');
    fixture.destroy();
    expect(request.cancelled).toBe(true);
  });
});
