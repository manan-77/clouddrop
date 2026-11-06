import { HttpEventType } from '@angular/common/http';
import { HttpTestingController, type TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { provideAuthTesting } from '@core/auth/auth-testing';
import { SessionStore } from '@core/auth/session.store';
import { MultipartTransfer, PART_ATTEMPTS, PART_CONCURRENCY } from './multipart-transfer.service';
import { StorageUploadError } from './storage-upload-error';

const PLAN = { part_size_bytes: 4, part_count: 3, expires_in: 900 };
const ONE = { part_size_bytes: 10, part_count: 1, expires_in: 900 };
const FILE = new File(['0123456789'], 'a.pdf', { type: 'application/pdf' });
const STORAGE = (n: number, v = 1) => `https://bucket.s3.amazonaws.com/key?partNumber=${n}&v=${v}`;
const PARTS_URL = '/api/v1/files/f1/uploads/parts';
const isPresign = (n: number) => (r: { url: string; body: unknown }) =>
  r.url === PARTS_URL && (r.body as { part_numbers: number[] }).part_numbers[0] === n;

describe('MultipartTransfer', () => {
  const setup = () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    TestBed.inject(SessionStore).setAccessToken('secret-token');
    return {
      transfer: TestBed.inject(MultipartTransfer),
      backend: TestBed.inject(HttpTestingController),
    };
  };
  const presign = (backend: HttpTestingController, n: number, url = STORAGE(n)): TestRequest => {
    const call = backend.expectOne(isPresign(n));
    call.flush({ parts: [{ part_number: n, url }], expires_in: 900 });
    return call;
  };
  afterEach(() => {
    vi.useRealTimers();
    TestBed.inject(HttpTestingController).verify();
  });

  it('send_slicesTheFileIntoPartsAndPutsEachToItsOwnSignedAddressWithoutTheToken', () => {
    const { transfer, backend } = setup();
    const progress: number[] = [];
    let done = false;
    transfer
      .send('f1', FILE, PLAN, (p) => progress.push(p))
      .subscribe({ complete: () => (done = true) });
    const presigns = [1, 2, 3].map((n) => backend.expectOne(isPresign(n)));
    presigns.forEach((call, i) => {
      expect(call.request.headers.get('Authorization')).toBe('Bearer secret-token');
      call.flush({ parts: [{ part_number: i + 1, url: STORAGE(i + 1) }], expires_in: 900 });
    });
    const sizes = [1, 2, 3].map((n) => {
      const put = backend.expectOne(STORAGE(n));
      expect(put.request.method).toBe('PUT');
      expect(put.request.headers.has('Authorization')).toBe(false);
      const size = (put.request.body as Blob).size;
      put.event({ type: HttpEventType.UploadProgress, loaded: size, total: size });
      put.flush('', { status: 200, statusText: 'OK' });
      return size;
    });
    expect(sizes).toEqual([4, 4, 2]);
    expect(done).toBe(true);
    expect(progress.at(-1)).toBe(99);
    expect(progress).toEqual([...progress].sort((a, b) => a - b));
  });

  it('send_onlyRunsTheConfiguredNumberOfPartsAtOnce', () => {
    const { transfer, backend } = setup();
    const count = PART_CONCURRENCY + 2;
    const file = new File(['x'.repeat(count)], 'a.pdf');
    const subscription = transfer
      .send('f1', file, { part_size_bytes: 1, part_count: count, expires_in: 900 }, () => undefined)
      .subscribe();
    const open = backend.match((r) => r.url === PARTS_URL);
    expect(open).toHaveLength(PART_CONCURRENCY);
    open[0].flush({ parts: [{ part_number: 1, url: STORAGE(1) }], expires_in: 900 });
    backend.expectOne(STORAGE(1)).flush('');
    expect(backend.match((r) => r.url === PARTS_URL)).toHaveLength(1);
    subscription.unsubscribe();
  });

  it('send_aFailedPartIsRetriedWithAFreshlySignedAddress', () => {
    vi.useFakeTimers();
    const { transfer, backend } = setup();
    let done = false;
    transfer.send('f1', FILE, ONE, () => undefined).subscribe({ complete: () => (done = true) });
    presign(backend, 1, STORAGE(1, 1));
    backend.expectOne(STORAGE(1, 1)).flush('', { status: 500, statusText: 'Server Error' });
    vi.advanceTimersByTime(600);
    presign(backend, 1, STORAGE(1, 2));
    backend.expectOne(STORAGE(1, 2)).flush('', { status: 200, statusText: 'OK' });
    expect(done).toBe(true);
  });

  it('send_aTransientFailureOfThePresignCallIsRetriedToo', () => {
    vi.useFakeTimers();
    const { transfer, backend } = setup();
    let done = false;
    transfer.send('f1', FILE, ONE, () => undefined).subscribe({ complete: () => (done = true) });
    backend.expectOne(isPresign(1)).error(new ProgressEvent('error'));
    vi.advanceTimersByTime(600);
    presign(backend, 1);
    backend.expectOne(STORAGE(1)).flush('');
    expect(done).toBe(true);
  });

  it('send_failsWithAStorageErrorAfterTheAttemptsAreUsedUp', () => {
    vi.useFakeTimers();
    const { transfer, backend } = setup();
    let error: unknown;
    transfer
      .send('f1', FILE, ONE, () => undefined)
      .subscribe({ error: (e: unknown) => (error = e) });
    for (let attempt = 0; attempt < PART_ATTEMPTS; attempt++) {
      presign(backend, 1);
      backend.expectOne(STORAGE(1)).error(new ProgressEvent('error'));
      vi.advanceTimersByTime(5000);
    }
    expect(error).toBeInstanceOf(StorageUploadError);
  });

  it.each([403, 400, 404])('send_doesNotRetryAnUnrecoverableStatus_%s', (status) => {
    const { transfer, backend } = setup();
    let error: unknown;
    transfer
      .send('f1', FILE, ONE, () => undefined)
      .subscribe({ error: (e: unknown) => (error = e) });
    presign(backend, 1);
    backend.expectOne(STORAGE(1)).flush('', { status, statusText: 'x' });
    expect(error).toBeInstanceOf(StorageUploadError);
    backend.expectNone(() => true);
  });

  it('send_anApiRejectionOfThePresignCallIsNotRetriedAndKeepsItsOwnError', () => {
    const { transfer, backend } = setup();
    let error: unknown;
    transfer
      .send('f1', FILE, ONE, () => undefined)
      .subscribe({ error: (e: unknown) => (error = e) });
    backend.expectOne(isPresign(1)).flush(null, { status: 409, statusText: 'Conflict' });
    expect(error).not.toBeInstanceOf(StorageUploadError);
    backend.expectNone(() => true);
  });

  it('send_unsubscribingCancelsInFlightPuts', () => {
    const { transfer, backend } = setup();
    const subscription = transfer.send('f1', FILE, ONE, () => undefined).subscribe();
    presign(backend, 1);
    const put = backend.expectOne(STORAGE(1));
    subscription.unsubscribe();
    expect(put.cancelled).toBe(true);
  });

  it('send_oneFailingPartCancelsItsSiblings', () => {
    const { transfer, backend } = setup();
    let error: unknown;
    transfer
      .send('f1', FILE, PLAN, () => undefined)
      .subscribe({ error: (e: unknown) => (error = e) });
    [1, 2, 3].forEach((n) => presign(backend, n));
    const [first, second, third] = [1, 2, 3].map((n) => backend.expectOne(STORAGE(n)));
    first.flush('', { status: 403, statusText: 'Forbidden' });
    expect(error).toBeInstanceOf(StorageUploadError);
    expect(second.cancelled && third.cancelled).toBe(true);
  });

  it('send_progressDropsBackWhenAPartIsRetried', () => {
    vi.useFakeTimers();
    const { transfer, backend } = setup();
    const progress: number[] = [];
    transfer.send('f1', FILE, ONE, (p) => progress.push(p)).subscribe();
    presign(backend, 1);
    const put = backend.expectOne(STORAGE(1));
    put.event({ type: HttpEventType.UploadProgress, loaded: 8, total: 10 });
    put.flush('', { status: 503, statusText: 'x' });
    expect(progress.at(-1)).toBe(0);
    expect(Math.max(...progress)).toBe(80);
    vi.advanceTimersByTime(600);
    presign(backend, 1);
    backend.expectOne(STORAGE(1)).flush('');
  });

  it.each([
    [{ part_size_bytes: 4, part_count: 2, expires_in: 900 }],
    [{ part_size_bytes: 0, part_count: 1, expires_in: 900 }],
  ])('send_refusesAPlanThatDoesNotCoverTheFile_%j', (plan) => {
    const { transfer, backend } = setup();
    let error: unknown;
    transfer
      .send('f1', FILE, plan, () => undefined)
      .subscribe({ error: (e: unknown) => (error = e) });
    expect(error).toBeInstanceOf(StorageUploadError);
    backend.expectNone(() => true);
  });

  it.each(['/same-origin/put', 'javascript:alert(1)', `${window.location.origin}/put`])(
    'send_refusesAnAddressThatIsNotOnAnotherOrigin_%s',
    (url) => {
      const { transfer, backend } = setup();
      let error: unknown;
      transfer
        .send('f1', FILE, ONE, () => undefined)
        .subscribe({ error: (e: unknown) => (error = e) });
      presign(backend, 1, url);
      expect(error).toBeInstanceOf(StorageUploadError);
      backend.expectNone(() => true);
    },
  );
});
