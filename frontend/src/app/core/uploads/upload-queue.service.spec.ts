import { HttpEventType } from '@angular/common/http';
import { HttpTestingController, type TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ENVELOPE, provideAuthTesting, TOKENS } from '@core/auth/auth-testing';
import { SessionStore } from '@core/auth/session.store';
import {
  EMPTY_FILE_MESSAGE,
  MAX_PARALLEL_UPLOADS,
  STORAGE_FAILED_MESSAGE,
  TOO_LARGE_MESSAGE,
  UploadQueue,
  type UploadItem,
} from './upload-queue.service';

const STORAGE = 'https://bucket.s3.amazonaws.com/';
const pdf = (name = 'report.pdf', body = 'hello') =>
  new File([body], name, { type: 'application/pdf' });
const fileRead = (id: string, name = 'report.pdf') => ({
  id,
  folder_id: null,
  name,
  content_type: 'application/pdf',
  size_bytes: 5,
  status: 'pending_upload',
  created_at: '',
  updated_at: '',
});
const initResponse = (id: string) => ({
  file: fileRead(id),
  upload: {
    url: STORAGE,
    fields: { key: `workspaces/w/files/${id}/v1`, 'Content-Type': 'application/pdf', policy: 'p' },
    expires_in: 900,
  },
});

describe('UploadQueue', () => {
  const setup = () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    TestBed.inject(SessionStore).setAccessToken('secret-token');
    return { queue: TestBed.inject(UploadQueue), backend: TestBed.inject(HttpTestingController) };
  };
  const isInit = (r: { url: string; method: string }) =>
    r.method === 'POST' && r.url === '/api/v1/files/uploads';
  const only = (queue: UploadQueue): UploadItem => queue.items()[0];
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('upload_happyPath_goesThroughEveryStepAndEmitsCompleted', () => {
    const { queue, backend } = setup();
    const completed: UploadItem[] = [];
    queue.completed$.subscribe((item) => completed.push(item));
    queue.add([pdf()], 'folder-1');

    const init = backend.expectOne(isInit);
    expect(init.request.body).toEqual({
      name: 'report.pdf',
      content_type: 'application/pdf',
      size_bytes: 5,
      folder_id: 'folder-1',
    });
    expect(only(queue).status).toBe('requesting');
    init.flush(initResponse('f1'));
    expect(only(queue).status).toBe('uploading');

    const storage = backend.expectOne(STORAGE);
    storage.event({ type: HttpEventType.UploadProgress, loaded: 50, total: 100 });
    expect(only(queue).progress).toBe(50);
    storage.flush(null, { status: 204, statusText: 'No Content' });
    expect(only(queue).status).toBe('completing');

    backend.expectOne('/api/v1/files/f1/uploads/complete').flush(fileRead('f1'));
    expect(only(queue).status).toBe('done');
    expect(only(queue).fileId).toBe('f1');
    expect(completed.map((item) => item.name)).toEqual(['report.pdf']);
  });

  it('storageRequest_isAFormWithTheFileLastAndNeverCarriesTheToken', () => {
    const { queue, backend } = setup();
    queue.add([pdf()], null);
    backend.expectOne(isInit).flush(initResponse('f1'));
    const request = backend.expectOne(STORAGE).request;
    const form = request.body as FormData;
    expect([...form.keys()]).toEqual(['key', 'Content-Type', 'policy', 'file']);
    expect(form.get('file')).toBeInstanceOf(File);
    expect(request.headers.has('Authorization')).toBe(false);
  });

  it('apiCalls_carryTheTokenButStorageDoesNot', () => {
    const { queue, backend } = setup();
    queue.add([pdf()], null);
    const init = backend.expectOne(isInit);
    expect(init.request.headers.get('Authorization')).toBe('Bearer secret-token');
    init.flush(initResponse('f1'));
    expect(backend.expectOne(STORAGE).request.headers.has('Authorization')).toBe(false);
  });

  it('manyFiles_onlyThreeRunAtOnceAndTheNextStartsWhenASlotFrees', () => {
    const { queue, backend } = setup();
    queue.add(
      [1, 2, 3, 4, 5].map((n) => pdf(`f${n}.pdf`)),
      null,
    );
    const initial = backend.match(isInit);
    expect(initial.length).toBe(MAX_PARALLEL_UPLOADS);
    expect(queue.items().filter((i) => i.status === 'queued').length).toBe(2);

    initial[0].flush(initResponse('a'));
    backend.expectOne(STORAGE).flush(null, { status: 204, statusText: 'No Content' });
    backend.expectOne('/api/v1/files/a/uploads/complete').flush(fileRead('a'));

    expect(backend.match(isInit).length).toBe(1);
    expect(queue.items().filter((i) => i.status === 'queued').length).toBe(1);
  });

  it('cancel_whileUploading_stopsTheRequestAndNeverCompletes', () => {
    const { queue, backend } = setup();
    queue.add([pdf()], null);
    backend.expectOne(isInit).flush(initResponse('f1'));
    const storage: TestRequest = backend.expectOne(STORAGE);
    queue.cancel(only(queue).id);
    expect(storage.cancelled).toBe(true);
    expect(only(queue).status).toBe('cancelled');
    backend.expectNone('/api/v1/files/f1/uploads/complete');
  });

  it('cancel_whileQueued_neverStarts', () => {
    const { queue, backend } = setup();
    queue.add(
      [1, 2, 3, 4].map((n) => pdf(`f${n}.pdf`)),
      null,
    );
    const fourth = queue.items()[3];
    queue.cancel(fourth.id);
    backend.match(isInit).forEach((r) => r.flush(initResponse('x')));
    backend.match(STORAGE).forEach((r) => r.flush(null, { status: 204, statusText: 'No Content' }));
    backend
      .match((r) => r.url.endsWith('/uploads/complete'))
      .forEach((r) => r.flush(fileRead('x')));
    backend.expectNone(isInit);
    expect(queue.items()[3].status).toBe('cancelled');
  });

  it('storageFailure_marksFailedWithAFriendlyMessageAndDoesNotComplete', () => {
    const { queue, backend } = setup();
    queue.add([pdf()], null);
    backend.expectOne(isInit).flush(initResponse('f1'));
    backend.expectOne(STORAGE).flush('<Error><Code>EntityTooLarge</Code></Error>', {
      status: 400,
      statusText: 'Bad Request',
    });
    expect(only(queue).status).toBe('failed');
    expect(only(queue).error).toBe(STORAGE_FAILED_MESSAGE);
    backend.expectNone('/api/v1/files/f1/uploads/complete');
  });

  it('initRejected_marksFailedWithTheMappedServerMessage', () => {
    const { queue, backend } = setup();
    queue.add([pdf()], null);
    backend
      .expectOne(isInit)
      .flush(ENVELOPE('unsupported_file_type'), { status: 422, statusText: 'Unprocessable' });
    expect(only(queue).status).toBe('failed');
    expect(only(queue).error).toBe('This type of file is not supported.');
  });

  it('completeRejected_marksFailedWithTheMappedMessage', () => {
    const { queue, backend } = setup();
    queue.add([pdf()], null);
    backend.expectOne(isInit).flush(initResponse('f1'));
    backend.expectOne(STORAGE).flush(null, { status: 204, statusText: 'No Content' });
    backend
      .expectOne('/api/v1/files/f1/uploads/complete')
      .flush(ENVELOPE('upload_size_mismatch'), { status: 422, statusText: 'Unprocessable' });
    expect(only(queue).error).toContain('did not match the expected size');
  });

  it('emptyAndOversizeFiles_failImmediatelyWithoutAnyRequest', () => {
    const { queue, backend } = setup();
    queue.add([new File([], 'empty.pdf', { type: 'application/pdf' })], null);
    const huge = pdf('huge.pdf');
    Object.defineProperty(huge, 'size', { value: 200 * 1024 * 1024 });
    queue.add([huge], null);
    expect(queue.items().map((i) => [i.status, i.error])).toEqual([
      ['failed', EMPTY_FILE_MESSAGE],
      ['failed', TOO_LARGE_MESSAGE],
    ]);
    backend.expectNone(isInit);
  });

  it('retry_afterFailure_startsAFreshUpload', () => {
    const { queue, backend } = setup();
    queue.add([pdf()], null);
    backend.expectOne(isInit).flush(ENVELOPE('internal_error'), { status: 500, statusText: 'x' });
    queue.retry(only(queue).id);
    expect(only(queue).status).toBe('requesting');
    expect(only(queue).error).toBeNull();
    backend.expectOne(isInit).flush(initResponse('f2'));
    backend.expectOne(STORAGE).flush(null, { status: 204, statusText: 'No Content' });
    backend.expectOne('/api/v1/files/f2/uploads/complete').flush(fileRead('f2'));
    expect(only(queue).status).toBe('done');
  });

  it('remove_onlyFinishedItemsCanBeRemoved', () => {
    const { queue, backend } = setup();
    queue.add([pdf()], null);
    queue.remove(only(queue).id);
    expect(queue.items().length).toBe(1);
    backend.expectOne(isInit).flush(ENVELOPE('internal_error'), { status: 500, statusText: 'x' });
    queue.remove(only(queue).id);
    expect(queue.items().length).toBe(0);
  });

  it('unauthorizedInit_refreshesTheTokenAndStillUploads', () => {
    const { queue, backend } = setup();
    queue.add([pdf()], null);
    backend.expectOne(isInit).flush(null, { status: 401, statusText: 'Unauthorized' });
    backend.expectOne('/api/v1/auth/refresh').flush(TOKENS('fresh'));
    const retry = backend.expectOne(isInit);
    expect(retry.request.headers.get('Authorization')).toBe('Bearer fresh');
    retry.flush(initResponse('f1'));
    backend.expectOne(STORAGE).flush(null, { status: 204, statusText: 'No Content' });
    backend.expectOne('/api/v1/files/f1/uploads/complete').flush(fileRead('f1'));
    expect(only(queue).status).toBe('done');
  });
});
