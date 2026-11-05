import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Router } from '@angular/router';
import {
  catchError,
  defer,
  finalize,
  map,
  of,
  type Observable,
  shareReplay,
  switchMap,
  tap,
  throwError,
} from 'rxjs';

import { type UserRead } from '@core/api/models';
import { AuthApi } from './auth-api.service';
import { SessionStore } from './session.store';

/** A refresh or restore finished after the user signed out or in again, so its result was dropped. */
export class SessionChangedError extends Error {
  constructor() {
    super('The session changed while a request was in flight');
  }
}

/** The account was created but the automatic sign-in after it failed. */
export class AccountCreatedSignInError extends Error {
  constructor(cause: unknown) {
    super('Account created but sign-in failed', { cause });
  }
}

const isUnauthorized = (error: unknown): boolean =>
  error instanceof HttpErrorResponse && error.status === 401;

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(AuthApi);
  private readonly session = inject(SessionStore);
  private readonly router = inject(Router);

  private refreshing$: Observable<string> | null = null;
  private restoring$: Observable<boolean> | null = null;

  login(email: string, password: string): Observable<UserRead> {
    return defer(() => {
      // Anything still in flight from the previous session must not overwrite this one.
      this.session.bumpGeneration();
      return this.api.login({ email, password });
    }).pipe(
      tap((tokens) => this.session.setAccessToken(tokens.access_token)),
      switchMap(() => this.api.me()),
      tap((user) => this.session.establish(user)),
      catchError((error: unknown) => {
        this.session.clear();
        return throwError(() => error);
      }),
    );
  }

  registerAndSignIn(email: string, password: string, displayName: string): Observable<UserRead> {
    return this.api
      .register({ email, password, display_name: displayName })
      .pipe(
        switchMap(() =>
          this.login(email, password).pipe(
            catchError((error: unknown) => throwError(() => new AccountCreatedSignInError(error))),
          ),
        ),
      );
  }

  /** Local state is always cleared; if the server call failed the cookie may still be valid. */
  logout(): Observable<void> {
    return this.api.logout().pipe(
      catchError(() => of(undefined)),
      finalize(() => {
        this.session.clear();
        void this.router.navigateByUrl('/login');
      }),
    );
  }

  /** Single flight: concurrent callers share one refresh request. */
  refreshAccessToken(): Observable<string> {
    if (!this.refreshing$) {
      const generation = this.session.generation;
      this.refreshing$ = this.api.refresh().pipe(
        map((tokens) => tokens.access_token),
        tap((token) => {
          if (this.session.generation !== generation) {
            throw new SessionChangedError();
          }
          this.session.setAccessToken(token);
        }),
        finalize(() => {
          this.refreshing$ = null;
        }),
        shareReplay({ bufferSize: 1, refCount: true }),
      );
    }
    return this.refreshing$;
  }

  /** Resolves true when a session exists, restoring it from the refresh cookie on first use. */
  ensureSession(): Observable<boolean> {
    if (this.session.status() !== 'unknown') {
      return of(this.session.isAuthenticated());
    }
    const generation = this.session.generation;
    this.restoring$ ??= this.refreshAccessToken().pipe(
      switchMap(() => this.api.me()),
      tap((user) => {
        if (this.session.generation !== generation) {
          throw new SessionChangedError();
        }
        this.session.establish(user);
      }),
      map(() => true),
      catchError((error: unknown) => {
        if (error instanceof SessionChangedError) {
          return of(this.session.isAuthenticated());
        }
        if (isUnauthorized(error)) {
          this.session.clear();
        }
        // Any other failure (network, 5xx) leaves the status unknown so the next navigation tries again.
        return of(false);
      }),
      finalize(() => {
        this.restoring$ = null;
      }),
      shareReplay({ bufferSize: 1, refCount: true }),
    );
    return this.restoring$;
  }

  handleSessionExpired(): void {
    this.session.clear();
    void this.router.navigateByUrl('/login');
  }
}
