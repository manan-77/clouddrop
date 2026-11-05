import { inject, Injectable } from '@angular/core';
import { Router } from '@angular/router';
import {
  catchError,
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

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(AuthApi);
  private readonly session = inject(SessionStore);
  private readonly router = inject(Router);

  private refreshing$: Observable<string> | null = null;
  private restoring$: Observable<boolean> | null = null;

  login(email: string, password: string): Observable<UserRead> {
    return this.api.login({ email, password }).pipe(
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
      .pipe(switchMap(() => this.login(email, password)));
  }

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
    this.refreshing$ ??= this.api.refresh().pipe(
      map((tokens) => tokens.access_token),
      tap((token) => this.session.setAccessToken(token)),
      finalize(() => {
        this.refreshing$ = null;
      }),
      shareReplay({ bufferSize: 1, refCount: true }),
    );
    return this.refreshing$;
  }

  /** Resolves true when a session exists, restoring it from the refresh cookie on first use. */
  ensureSession(): Observable<boolean> {
    if (this.session.status() !== 'unknown') {
      return of(this.session.isAuthenticated());
    }
    this.restoring$ ??= this.refreshAccessToken().pipe(
      switchMap(() => this.api.me()),
      tap((user) => this.session.establish(user)),
      map(() => true),
      catchError(() => {
        this.session.clear();
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
