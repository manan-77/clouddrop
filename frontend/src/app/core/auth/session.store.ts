import { computed, Injectable, signal } from '@angular/core';

import { type UserRead } from '@core/api/models';

export type SessionStatus = 'unknown' | 'authenticated' | 'anonymous';

/**
 * In-memory session. The access token lives here and nowhere else: never in web storage, a URL or a
 * log. The refresh token is an HttpOnly cookie that scripts cannot read.
 */
@Injectable({ providedIn: 'root' })
export class SessionStore {
  private readonly token = signal<string | null>(null);

  readonly accessToken = this.token.asReadonly();
  readonly user = signal<UserRead | null>(null);
  readonly status = signal<SessionStatus>('unknown');
  readonly isAuthenticated = computed(() => this.status() === 'authenticated');

  setAccessToken(token: string): void {
    this.token.set(token);
  }

  establish(user: UserRead): void {
    this.user.set(user);
    this.status.set('authenticated');
  }

  clear(): void {
    this.token.set(null);
    this.user.set(null);
    this.status.set('anonymous');
  }
}
