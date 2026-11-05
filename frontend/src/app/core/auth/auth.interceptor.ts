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
const AUTH_ENDPOINTS = ['login', 'register', 'refresh', 'logout'].map(
  (name) => `${API_BASE}/auth/${name}`,
);

const isApiRequest = (url: string): boolean => url.startsWith(`${API_BASE}/`);
const isAuthEndpoint = (url: string): boolean =>
  AUTH_ENDPOINTS.some((path) => url.split('?')[0] === path);

/**
 * Attaches the bearer token to same-origin API calls only, so it can never reach storage servers or
 * any other origin. A 401 triggers one shared refresh and one retry; there is no other 401 logic.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isApiRequest(req.url) || isAuthEndpoint(req.url)) {
    return next(req);
  }
  const auth = inject(AuthService);
  const session = inject(SessionStore);

  const withToken = (request: HttpRequest<unknown>, token: string | null): HttpRequest<unknown> =>
    token ? request.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : request;

  return next(withToken(req, session.accessToken())).pipe(
    catchError((error: unknown) => {
      if (
        !(error instanceof HttpErrorResponse) ||
        error.status !== 401 ||
        req.context.get(RETRIED)
      ) {
        return throwError(() => error);
      }
      return auth.refreshAccessToken().pipe(
        catchError(() => {
          auth.handleSessionExpired();
          return throwError(() => error);
        }),
        switchMap((token) =>
          next(withToken(req.clone({ context: new HttpContext().set(RETRIED, true) }), token)),
        ),
      );
    }),
  );
};
