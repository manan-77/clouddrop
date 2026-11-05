import { HttpClient, type HttpErrorResponse } from '@angular/common/http';
import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { AuthService } from './auth.service';
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

  it.each([
    '//evil.example/api/v1/folders',
    'http://localhost/api/v1/folders',
    '/api/v1/../admin',
    '/api/v1/%2e%2e/admin',
  ])('suspiciousUrl_%s_neverReceivesTheToken', (url) => {
    const { http, backend, session } = setup();
    session.setAccessToken('secret-token');
    http.get(url).subscribe();
    expect(backend.expectOne(url).request.headers.has('Authorization')).toBe(false);
  });

  it.each(['/api/v1/auth/login/', '/api/v1/auth/login?x=1', '/api/v1/auth/refresh/'])(
    'authEndpointVariant_%s_isStillTreatedAsAuthEndpoint',
    (url) => {
      const { http, backend, session } = setup();
      session.setAccessToken('t1');
      http.post(url, {}).subscribe({ error: () => undefined });
      const request = backend.expectOne(url);
      expect(request.request.headers.has('Authorization')).toBe(false);
      request.flush(null, UNAUTHORIZED);
      backend.expectNone('/api/v1/auth/refresh');
    },
  );

  it('unauthorizedWrite_isRetriedOnceWithTheSameBody', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('old');
    http.post('/api/v1/folders', { name: 'Reports' }).subscribe();
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    backend.expectOne('/api/v1/auth/refresh').flush(TOKENS('new'));
    const retry = backend.expectOne('/api/v1/folders');
    expect(retry.request.method).toBe('POST');
    expect(retry.request.body).toEqual({ name: 'Reports' });
    expect(retry.request.headers.get('Authorization')).toBe('Bearer new');
    retry.flush({});
  });

  it('unauthorizedAfterAnotherRequestRefreshed_retriesWithCurrentTokenWithoutRefreshing', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('old');
    http.get('/api/v1/folders').subscribe();
    const first = backend.expectOne('/api/v1/folders');
    session.setAccessToken('newer');
    first.flush(null, UNAUTHORIZED);
    backend.expectNone('/api/v1/auth/refresh');
    const retry = backend.expectOne('/api/v1/folders');
    expect(retry.request.headers.get('Authorization')).toBe('Bearer newer');
    retry.flush({});
  });

  it('refreshNetworkError_keepsTheSessionAndSurfacesTheOriginalError', () => {
    const { http, backend, session, router } = setup();
    session.setAccessToken('old');
    session.establish({ id: 'u', email: 'a@b.c', display_name: 'A', created_at: '' });
    let error: HttpErrorResponse | undefined;
    http.get('/api/v1/folders').subscribe({ error: (e: HttpErrorResponse) => (error = e) });
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    backend.expectOne('/api/v1/auth/refresh').error(new ProgressEvent('error'));
    expect(error?.status).toBe(401);
    expect(session.isAuthenticated()).toBe(true);
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('refreshAfterAnEarlierFailedRefresh_startsAFreshRequest', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('old');
    http.get('/api/v1/folders').subscribe({ error: () => undefined });
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    backend.expectOne('/api/v1/auth/refresh').flush(null, UNAUTHORIZED);

    session.setAccessToken('again');
    http.get('/api/v1/files').subscribe({ error: () => undefined });
    backend.expectOne('/api/v1/files').flush(null, UNAUTHORIZED);
    backend.expectOne('/api/v1/auth/refresh').flush(TOKENS('fresh'));
    backend.expectOne('/api/v1/files').flush({});
  });

  it('logoutWhileRefreshInFlight_neverResurrectsTheSession', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('old');
    session.establish({ id: 'u', email: 'a@b.c', display_name: 'A', created_at: '' });
    let error: HttpErrorResponse | undefined;
    http.get('/api/v1/folders').subscribe({ error: (e: HttpErrorResponse) => (error = e) });
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    const refresh = backend.expectOne('/api/v1/auth/refresh');

    TestBed.inject(AuthService).logout().subscribe();
    backend.expectOne('/api/v1/auth/logout').flush(null);
    refresh.flush(TOKENS('stale'));

    backend.expectNone('/api/v1/folders');
    expect(error?.status).toBe(401);
    expect(session.accessToken()).toBeNull();
    expect(session.status()).toBe('anonymous');
  });

  it('loginWhileRefreshInFlight_keepsTheNewSessionAndDropsTheStaleToken', () => {
    const { http, backend, session } = setup();
    session.setAccessToken('old');
    http.get('/api/v1/folders').subscribe({ error: () => undefined });
    backend.expectOne('/api/v1/folders').flush(null, UNAUTHORIZED);
    const refresh = backend.expectOne('/api/v1/auth/refresh');

    TestBed.inject(AuthService).login('a@b.c', 'password-12345').subscribe();
    refresh.flush(TOKENS('stale'));
    backend.expectOne('/api/v1/auth/login').flush(TOKENS('fresh'));
    backend.expectOne('/api/v1/auth/me').flush({
      id: 'u',
      email: 'a@b.c',
      display_name: 'A',
      created_at: '',
    });
    expect(session.accessToken()).toBe('fresh');
    expect(session.isAuthenticated()).toBe(true);
    backend.expectNone('/api/v1/folders');
  });
});
