import { HttpClient, type HttpErrorResponse } from '@angular/common/http';
import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { provideAuthTesting, TOKENS } from './auth-testing';
import { SessionStore } from './session.store';

const UNAUTHORIZED = { status: 401, statusText: 'Unauthorized' };

describe('authInterceptor', () => {
  const setup = () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    const router = TestBed.inject(Router);
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    return {
      http: TestBed.inject(HttpClient),
      backend: TestBed.inject(HttpTestingController),
      session: TestBed.inject(SessionStore),
      router,
    };
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('apiCall_withToken_attachesBearer', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('t1');
    http.get('/api/v1/folders').subscribe();
    expect(backend.expectOne('/api/v1/folders').request.headers.get('Authorization')).toBe(
      'Bearer t1',
    );
  });

  it('apiCall_withoutToken_sendsNoAuthorization', () => {
    const { http, backend } = setup();
    http.get('/api/v1/folders').subscribe();
    expect(backend.expectOne('/api/v1/folders').request.headers.has('Authorization')).toBe(false);
  });

  it('storageUpload_neverReceivesTheToken', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('secret-token');
    http.post('https://bucket.s3.amazonaws.com/', {}).subscribe();
    const request = backend.expectOne('https://bucket.s3.amazonaws.com/').request;
    expect(request.headers.has('Authorization')).toBe(false);
  });

  it.each(['login', 'register', 'refresh', 'logout'])(
    'authEndpoint_%s_getsNoTokenAndIsNeverRefreshedOn401',
    (name) => {
      const { http, backend, session } = setup();
      session.setAccessToken('t1');
      http.post(`/api/v1/auth/${name}`, {}).subscribe({ error: () => undefined });
      const request = backend.expectOne(`/api/v1/auth/${name}`);
      expect(request.request.headers.has('Authorization')).toBe(false);
      request.flush(null, UNAUTHORIZED);
      backend.expectNone('/api/v1/auth/refresh');
    },
  );

  it('unauthorized_refreshesOnceAndRetriesWithNewToken', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('old');
    let result: unknown;
    http.get('/api/v1/folders').subscribe((value) => (result = value));
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    backend.expectOne('/api/v1/auth/refresh').flush(TOKENS('new'));
    const retry = backend.expectOne('/api/v1/folders');
    expect(retry.request.headers.get('Authorization')).toBe('Bearer new');
    retry.flush({ ok: true });
    expect(result).toEqual({ ok: true });
    expect(session.accessToken()).toBe('new');
  });

  it('concurrentUnauthorized_shareOneRefreshRequest', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('old');
    http.get('/api/v1/folders').subscribe();
    http.get('/api/v1/files').subscribe();
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    backend.expectOne('/api/v1/files').flush(null, UNAUTHORIZED);
    const refreshes = backend.match('/api/v1/auth/refresh');
    expect(refreshes.length).toBe(1);
    refreshes[0].flush(TOKENS('new'));
    backend.expectOne('/api/v1/folders').flush({});
    backend.expectOne('/api/v1/files').flush({});
  });

  it('refreshFails_clearsSessionSendsToLoginAndKeepsOriginalError', () => {
    const { http, backend, session, router } = setup();
    session.setAccessToken('old');
    session.establish({ id: 'u', email: 'a@b.c', display_name: 'A', created_at: '' });
    let error: HttpErrorResponse | undefined;
    http.get('/api/v1/folders').subscribe({ error: (e: HttpErrorResponse) => (error = e) });
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    backend.expectOne('/api/v1/auth/refresh').flush(null, UNAUTHORIZED);
    expect(error?.status).toBe(401);
    expect(session.status()).toBe('anonymous');
    expect(session.accessToken()).toBeNull();
    expect(router.navigateByUrl).toHaveBeenCalledWith('/login');
  });

  it('retryUnauthorizedAgain_failsWithoutASecondRefresh', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('old');
    let error: HttpErrorResponse | undefined;
    http.get('/api/v1/folders').subscribe({ error: (e: HttpErrorResponse) => (error = e) });
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    backend.expectOne('/api/v1/auth/refresh').flush(TOKENS('new'));
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    backend.expectNone('/api/v1/auth/refresh');
    expect(error?.status).toBe(401);
  });

  it('serverError_passesThroughWithoutRefresh', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('t');
    let error: HttpErrorResponse | undefined;
    http.get('/api/v1/folders').subscribe({ error: (e: HttpErrorResponse) => (error = e) });
    backend.expectOne('/api/v1/folders').flush(null, { status: 500, statusText: 'Server Error' });
    backend.expectNone('/api/v1/auth/refresh');
    expect(error?.status).toBe(500);
  });
});
