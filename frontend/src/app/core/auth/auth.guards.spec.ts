import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import {
  type ActivatedRouteSnapshot,
  type CanActivateFn,
  type RouterStateSnapshot,
  UrlTree,
} from '@angular/router';
import { firstValueFrom, type Observable } from 'rxjs';

import { authGuard, guestGuard } from './auth.guards';
import { ENVELOPE, provideAuthTesting, TOKENS, USER } from './auth-testing';
import { SessionStore } from './session.store';

describe('route guards', () => {
  const setup = () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    const run = (guard: CanActivateFn) =>
      TestBed.runInInjectionContext(() =>
        guard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot),
      ) as Observable<boolean | UrlTree>;
    return {
      run,
      backend: TestBed.inject(HttpTestingController),
      session: TestBed.inject(SessionStore),
    };
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('authGuard_signedIn_allows', async () => {
    const { run, session } = setup();
    session.setAccessToken('t');
    session.establish(USER);
    expect(await firstValueFrom(run(authGuard))).toBe(true);
  });

  it('authGuard_cookieRestoresSession_allows', async () => {
    const { run, backend } = setup();
    const result = firstValueFrom(run(authGuard));
    backend.expectOne('/api/v1/auth/refresh').flush(TOKENS('t'));
    backend.expectOne('/api/v1/auth/me').flush(USER);
    expect(await result).toBe(true);
  });

  it('authGuard_noSession_redirectsToLogin', async () => {
    const { run, backend } = setup();
    const result = firstValueFrom(run(authGuard));
    backend
      .expectOne('/api/v1/auth/refresh')
      .flush(ENVELOPE('invalid_session'), { status: 401, statusText: 'Unauthorized' });
    const value = await result;
    expect(value instanceof UrlTree && value.toString()).toBe('/login');
  });

  it('guestGuard_signedIn_redirectsHome', async () => {
    const { run, session } = setup();
    session.setAccessToken('t');
    session.establish(USER);
    const value = await firstValueFrom(run(guestGuard));
    expect(value instanceof UrlTree && value.toString()).toBe('/');
  });

  it('guestGuard_anonymous_allows', async () => {
    const { run, session } = setup();
    session.clear();
    expect(await firstValueFrom(run(guestGuard))).toBe(true);
  });
});
