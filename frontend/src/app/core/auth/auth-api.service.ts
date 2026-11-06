import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from '@core/api/api-base';
import {
  type LoginRequest,
  type RegisterRequest,
  type TokenResponse,
  type UserRead,
} from '@core/api/models';

/**
 * Cookie-bearing endpoints require this header: a cross-site form cannot send it, and a
 * cross-origin script needs a CORS preflight the API never grants.
 */
const CSRF_HEADERS = new HttpHeaders({ 'X-Requested-With': 'XMLHttpRequest' });

/** Transport only: no state, no navigation. */
@Injectable({ providedIn: 'root' })
export class AuthApi {
  private readonly http = inject(HttpClient);

  register(body: RegisterRequest): Observable<UserRead> {
    return this.http.post<UserRead>(`${API_BASE}/auth/register`, body);
  }

  login(body: LoginRequest): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(`${API_BASE}/auth/login`, body);
  }

  refresh(): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(`${API_BASE}/auth/refresh`, null, {
      headers: CSRF_HEADERS,
    });
  }

  logout(): Observable<void> {
    return this.http.post<void>(`${API_BASE}/auth/logout`, null, { headers: CSRF_HEADERS });
  }

  me(): Observable<UserRead> {
    return this.http.get<UserRead>(`${API_BASE}/auth/me`);
  }
}
