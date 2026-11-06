import { HttpEventType } from '@angular/common/http';
import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { provideAuthTesting } from '@core/auth/auth-testing';
import { MultipartTransfer, PART_ATTEMPTS, PART_CONCURRENCY } from './multipart-transfer.service';
import { StorageUploadError } from './storage-upload-error';

const PLAN = { part_size_bytes: 4, part_count: 3, expires_in: 900 };
const FILE = new File(['0123456789'], 'a.pdf', { type: 'application/pdf' });
const STORAGE = (n: number) => `https://bucket.s3.amazonaws.com/key?partNumber=${n}`;
const PARTS_URL = '/api/v1/files/f1/uploads/parts';

describe('MultipartTransfer', () => {
  const setup = () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    return {
      transfer: TestBed.inject(MultipartTransfer),
      backend: TestBed.inject(HttpTestingController),
    };
  };
  const presign = (backend: HttpTestingController, n: number, url = STORAGE(n)) => {
    const call = backend.expectOne(
      (r) => r.url === PARTS_URL && (r.body as { part_numbers: number[] }).part_numbers[0] === n,
    );
    call.flush({ parts: [{ part_number: n, url }], expires_in: 900 });
  };
  afterEach(() => {
    vi.useRealTimers();
    TestBed.inject(HttpTestingController).verify();
  });

  it('send_slicesTheFileIntoPartsAndPutsEachToItsOwnSignedAddress', () => {
    const { transfer, backend } = setup();
    const progress: number[] = [];
    let done = false;
    transfer.send('f1', FILE, PLAN, (p) => progress.push(p)).subscribe(() => (done = true));
    for (const n of [1, 2, 3]) {
      presign(backend, n);
    }
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
    expect(progress.at(-1)).toBeLessThanOrEqual(99);
  });

  it('send_onlyRunsTheConfiguredNumberOfPartsAtOnce', () => {
    const { transfer, backend } = setup();
    transfer.send('f1', FILE, { ...PLAN, part_count: 3 }, () => undefined).subscribe();
    const first = backend.match((r) => r.url === PARTS_URL);
    expect(first).toHaveLength(Math.min(PART_CONCURRENCY, 3));
    first.forEach((r, i) =>
      r.flush({ parts: [{ part_number: i + 1, url: STORAGE(i + 1) }], expires_in: 900 }),
    );
    backend.match((r) => r.url.startsWith('https://')).forEach((r) => r.flush(''));
  });

  it('send_aFailedPartIsRetriedOnItsOwnThenSucceeds', () => {
    vi.useFakeTimers();
    const { transfer, backend } = setup();
    let done = false;
    transfer
      .send('f1', FILE, { part_size_bytes: 10, part_count: 1, expires_in: 900 }, () => undefined)
      .subscribe(() => (done = true));
    presign(backend, 1);
    backend.expectOne(STORAGE(1)).flush('', { status: 500, statusText: 'Server Error' });
    vi.advanceTimersByTime(600);
    backend.expectOne(STORAGE(1)).flush('', { status: 200, statusText: 'OK' });
    expect(done).toBe(true);
  });

  it('send_failsWithAStorageErrorAfterTheAttemptsAreUsedUp', () => {
    vi.useFakeTimers();
    const { transfer, backend } = setup();
    let error: unknown;
    transfer
      .send('f1', FILE, { part_size_bytes: 10, part_count: 1, expires_in: 900 }, () => undefined)
      .subscribe({ error: (e: unknown) => (error = e) });
    presign(backend, 1);
    for (let attempt = 0; attempt < PART_ATTEMPTS; attempt++) {
      backend.expectOne(STORAGE(1)).error(new ProgressEvent('error'));
      vi.advanceTimersByTime(5000);
    }
    expect(error).toBeInstanceOf(StorageUploadError);
  });

  it.each(['/same-origin/put', 'javascript:alert(1)', `${window.location.origin}/put`])(
    'send_refusesAnAddressThatIsNotOnAnotherOrigin_%s',
    (url) => {
      const { transfer, backend } = setup();
      let error: unknown;
      transfer
        .send('f1', FILE, { part_size_bytes: 10, part_count: 1, expires_in: 900 }, () => undefined)
        .subscribe({ error: (e: unknown) => (error = e) });
      presign(backend, 1, url);
      expect(error).toBeInstanceOf(StorageUploadError);
      backend.expectNone(() => true);
    },
  );
});
