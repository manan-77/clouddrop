import {
  HttpContext,
  HttpContextToken,
  HttpErrorResponse,
  type HttpInterceptorFn,
  type HttpRequest,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';

import { API_BASE } from '@core/api/api-base';
import { AuthService } from './auth.service';
import { SessionStore } from './session.store';

const RETRIED = new HttpContextToken<boolean>(() => false);
const AUTH_ENDPOINT = new RegExp(`^${API_BASE}/auth/(login|register|refresh|logout)/?([?#].*)?$`);
// Dot segments and encoded dots could point a "same-origin API" URL somewhere else.
const SUSPICIOUS = /%2e|\/\.\.?(\/|$|\?|#)/i;

const isApiRequest = (url: string): boolean =>
  url.startsWith(`${API_BASE}/`) && !SUSPICIOUS.test(url);

function retryContext(original: HttpContext): HttpContext {
  const context = new HttpContext();
  for (const key of original.keys()) {
    context.set(key, original.get(key));
  }
  return context.set(RETRIED, true);
}

/**
 * Attaches the bearer token to same-origin API calls only, so it can never reach storage servers or
 * any other origin. A 401 triggers one shared refresh and one retry; there is no other 401 logic.
 *
 * The retry also covers writes. That is a deliberate exception to "never auto-retry a write": a 401
 * is produced by the auth layer before any handler runs, so the first attempt had no side effect
 * (see ADR 0006).
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isApiRequest(req.url) || AUTH_ENDPOINT.test(req.url)) {
    return next(req);
  }
  const auth = inject(AuthService);
  const session = inject(SessionStore);

  const withToken = (request: HttpRequest<unknown>, token: string | null): HttpRequest<unknown> =>
    token ? request.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : request;
  const usedToken = session.accessToken();
  const retry = (token: string) =>
    next(withToken(req.clone({ context: retryContext(req.context) }), token));

  return next(withToken(req, usedToken)).pipe(
    catchError((error: unknown) => {
      if (
        !(error instanceof HttpErrorResponse) ||
        error.status !== 401 ||
        req.context.get(RETRIED)
      ) {
        return throwError(() => error);
      }
      const current = session.accessToken();
      if (current && current !== usedToken) {
        // Another request already refreshed while this one was in flight.
        return retry(current);
      }
      return auth.refreshAccessToken().pipe(
        catchError((refreshError: unknown) => {
          // Only a rejected refresh ends the session; a network blip or 5xx must not sign anyone out.
          if (refreshError instanceof HttpErrorResponse && refreshError.status === 401) {
            auth.handleSessionExpired();
          }
          return throwError(() => error);
        }),
        switchMap(retry),
      );
    }),
  );
};
