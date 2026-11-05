import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { type EnvironmentProviders, type Provider } from '@angular/core';
import { provideRouter } from '@angular/router';

import { authInterceptor } from './auth.interceptor';

/** Providers shared by specs that exercise HTTP through the real interceptor. */
export function provideAuthTesting(): (Provider | EnvironmentProviders)[] {
  return [
    provideHttpClient(withInterceptors([authInterceptor])),
    provideHttpClientTesting(),
    provideRouter([]),
  ];
}

export const USER = {
  id: 'u1',
  email: 'ada@example.com',
  display_name: 'Ada',
  created_at: '2026-01-01T00:00:00Z',
};
export const TOKENS = (token: string) => ({
  access_token: token,
  token_type: 'bearer',
  expires_in: 900,
});
export const ENVELOPE = (code: string, details: { field: string; message: string }[] = []) => ({
  error: { code, message: 'server wording', request_id: 'r1', details },
});
