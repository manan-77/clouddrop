import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { type FileRead, type FileStatus, type Page } from '@core/api/models';
import { DEFAULT_PAGE_SIZE } from '@core/api/pagination';
import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { ExplorerStore, MAX_POLLS, POLL_DELAYS_MS } from './explorer.store';

const STAMP = '2026-01-02T10:00:00Z';
const FOLDERS = (r: { url: string }) => r.url === '/api/v1/folders';
const FILES = (r: { url: string }) => r.url === '/api/v1/files';
const file = (id: string, status: FileStatus): FileRead => ({
  id,
  folder_id: null,
  name: `${id}.pdf`,
  content_type: 'application/pdf',
  size_bytes: 10,
  status,
  created_at: STAMP,
  updated_at: STAMP,
  role: 'owner',
});
const page = <T>(items: T[]): Page<T> => ({
  items,
  total: items.length,
  page: 1,
  page_size: DEFAULT_PAGE_SIZE,
});

describe('ExplorerStore refreshing files that are still being processed', () => {
  let store: ExplorerStore;
  let backend: HttpTestingController;
  const statuses = () => store.view().files?.items.map((f) => f.status);
  const load = (...files: FileRead[]) => {
    backend.expectOne(FOLDERS).flush(page([]));
    backend.expectOne(FILES).flush(page(files));
  };
  const open = (...files: FileRead[]) => {
    store.open(null);
    TestBed.tick();
    load(...files);
  };
  /** Moves the clock and lets the store react (the refresh is started by an effect). */
  const wait = async (ms: number) => {
    await vi.advanceTimersByTimeAsync(ms);
    TestBed.tick();
  };
  const noRequests = () => {
    backend.expectNone(FOLDERS);
    backend.expectNone(FILES);
  };

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({ providers: [...provideAuthTesting(), ExplorerStore] });
    store = TestBed.inject(ExplorerStore);
    backend = TestBed.inject(HttpTestingController);
  });
  afterEach(() => {
    vi.useRealTimers();
    backend.verify();
  });

  it.each(['pending_upload', 'uploaded', 'scanning', 'processing'] as const)(
    'aFileThatIs_%s_isRefreshedAfterAPause_withoutAnyLoadingScreen',
    async (status) => {
      open(file('a', status));
      await wait(POLL_DELAYS_MS[0] - 1);
      noRequests();
      await wait(1);
      expect(store.view().status).toBe('ready'); // a refresh is not a loading state
      load(file('a', 'ready'));
      expect(statuses()).toEqual(['ready']);
    },
  );

  it.each(['ready', 'failed', 'infected', 'needs_ocr'] as const)(
    'aFileThatIs_%s_isNeverRefreshed',
    async (status) => {
      open(file('a', status));
      await wait(120_000);
      noRequests();
    },
  );

  it('refreshingStopsOnceEveryFileHasSettled', async () => {
    open(file('a', 'processing'), file('b', 'uploaded'));
    await wait(POLL_DELAYS_MS[0]);
    load(file('a', 'ready'), file('b', 'processing'));
    await wait(POLL_DELAYS_MS[1]);
    load(file('a', 'ready'), file('b', 'ready'));
    await wait(120_000);
    noRequests();
  });

  it('thePausesGrow_thenStayAtTheLongest', async () => {
    open(file('a', 'processing'));
    const expected = [...POLL_DELAYS_MS, POLL_DELAYS_MS.at(-1)!, POLL_DELAYS_MS.at(-1)!];
    for (const delay of expected) {
      await wait(delay - 1);
      noRequests();
      await wait(1);
      load(file('a', 'processing'));
    }
  });

  it('aFileThatNeverSettlesIsRefreshedOnlyAFewTimes_notForever', async () => {
    open(file('a', 'processing'));
    for (let polls = 0; polls < MAX_POLLS; polls += 1) {
      await wait(POLL_DELAYS_MS.at(-1)!);
      load(file('a', 'processing'));
    }
    await wait(600_000);
    noRequests();
  });

  it('aFailedRefreshIsNotShown_andRefreshingGoesOn', async () => {
    open(file('a', 'processing'));
    await wait(POLL_DELAYS_MS[0]);
    backend.expectOne(FOLDERS).flush(ENVELOPE('internal_error'), { status: 500, statusText: 'x' });
    backend.match(FILES); // cancelled together with the failed one
    expect(store.view().status).toBe('ready');
    expect(store.view().error).toBeNull();
    expect(statuses()).toEqual(['processing']);
    await wait(POLL_DELAYS_MS[1]);
    load(file('a', 'ready'));
    expect(statuses()).toEqual(['ready']);
  });

  it('openingAnotherFolder_dropsThePendingRefresh_andShowsTheLoadingScreen', async () => {
    open(file('a', 'processing'));
    await wait(POLL_DELAYS_MS[0] - 100);
    store.open('other');
    TestBed.tick();
    expect(store.view().status).toBe('loading');
    backend.expectOne((r) => r.url === '/api/v1/folders/other/path').flush([]);
    backend.expectOne((r) => r.url === '/api/v1/folders').flush(page([]));
    backend.expectOne(FILES).flush(page([]));
    await wait(10_000);
    noRequests();
  });

  it('aRealReloadStartsTheRefreshPausesOverAgain', async () => {
    open(file('a', 'processing'));
    await wait(POLL_DELAYS_MS[0]);
    load(file('a', 'processing'));
    await wait(POLL_DELAYS_MS[1]);
    load(file('a', 'processing'));
    store.reload();
    TestBed.tick();
    expect(store.view().status).toBe('loading'); // an action the user took still shows loading
    load(file('a', 'processing'));
    await wait(POLL_DELAYS_MS[0] - 1);
    noRequests();
    await wait(1);
    load(file('a', 'ready'));
  });
});
