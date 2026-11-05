import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { AuthService } from './auth.service';
import { ENVELOPE, provideAuthTesting, TOKENS, USER } from './auth-testing';
import { SessionStore } from './session.store';

describe('AuthService', () => {
  const setup = () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    const router = TestBed.inject(Router);
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    return {
      service: TestBed.inject(AuthService),
      backend: TestBed.inject(HttpTestingController),
      session: TestBed.inject(SessionStore),
      router,
    };
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('login_success_setsTokenThenLoadsUserWithThatToken', () => {
    const { service, backend, session } = setup();
    service.login('ada@example.com', 'a-long-password').subscribe();
    const login = backend.expectOne('/api/v1/auth/login');
    expect(login.request.body).toEqual({ email: 'ada@example.com', password: 'a-long-password' });
    login.flush(TOKENS('t1'));
    const me = backend.expectOne('/api/v1/auth/me');
    expect(me.request.headers.get('Authorization')).toBe('Bearer t1');
    me.flush(USER);
    expect(session.isAuthenticated()).toBe(true);
    expect(session.user()?.display_name).toBe('Ada');
  });

  it('login_wrongPassword_staysAnonymousAndSurfacesTheError', () => {
    const { service, backend, session } = setup();
    let failed = false;
    service.login('a@b.c', 'x').subscribe({ error: () => (failed = true) });
    backend
      .expectOne('/api/v1/auth/login')
      .flush(ENVELOPE('invalid_credentials'), { status: 401, statusText: 'Unauthorized' });
    expect(failed).toBe(true);
    expect(session.isAuthenticated()).toBe(false);
    expect(session.accessToken()).toBeNull();
  });

  it('login_userLookupFails_clearsTheToken', () => {
    const { service, backend, session } = setup();
    service.login('a@b.c', 'x').subscribe({ error: () => undefined });
    backend.expectOne('/api/v1/auth/login').flush(TOKENS('t1'));
    backend.expectOne('/api/v1/auth/me').flush(null, { status: 500, statusText: 'Server Error' });
    expect(session.accessToken()).toBeNull();
    expect(session.status()).toBe('anonymous');
  });

  it('registerAndSignIn_success_registersThenLogsInThenLoadsUser', () => {
    const { service, backend, session } = setup();
    service.registerAndSignIn('ada@example.com', 'a-long-password', 'Ada').subscribe();
    const register = backend.expectOne('/api/v1/auth/register');
    expect(register.request.body).toEqual({
      email: 'ada@example.com',
      password: 'a-long-password',
      display_name: 'Ada',
    });
    register.flush(USER);
    backend.expectOne('/api/v1/auth/login').flush(TOKENS('t1'));
    backend.expectOne('/api/v1/auth/me').flush(USER);
    expect(session.isAuthenticated()).toBe(true);
  });

  it('ensureSession_validCookie_restoresOnceForConcurrentCallers', () => {
    const { service, backend, session } = setup();
    const results: boolean[] = [];
    service.ensureSession().subscribe((ok) => results.push(ok));
    service.ensureSession().subscribe((ok) => results.push(ok));
    backend.expectOne('/api/v1/auth/refresh').flush(TOKENS('t2'));
    backend.expectOne('/api/v1/auth/me').flush(USER);
    expect(results).toEqual([true, true]);
    expect(session.isAuthenticated()).toBe(true);
  });

  it('ensureSession_noCookie_returnsFalseAndDoesNotAskAgain', () => {
    const { service, backend, session } = setup();
    const results: boolean[] = [];
    service.ensureSession().subscribe((ok) => results.push(ok));
    backend
      .expectOne('/api/v1/auth/refresh')
      .flush(ENVELOPE('invalid_session'), { status: 401, statusText: 'Unauthorized' });
    expect(results).toEqual([false]);
    expect(session.status()).toBe('anonymous');
    service.ensureSession().subscribe((ok) => results.push(ok));
    backend.expectNone('/api/v1/auth/refresh');
    expect(results).toEqual([false, false]);
  });

  it('logout_apiFails_stillClearsTheSessionAndGoesToLogin', () => {
    const { service, backend, session, router } = setup();
    session.setAccessToken('t1');
    session.establish(USER);
    service.logout().subscribe();
    backend
      .expectOne('/api/v1/auth/logout')
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(session.isAuthenticated()).toBe(false);
    expect(session.accessToken()).toBeNull();
    expect(router.navigateByUrl).toHaveBeenCalledWith('/login');
  });
});
