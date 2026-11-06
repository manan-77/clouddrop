import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { AuthApi } from './auth-api.service';

function setup() {
  TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
  return { api: TestBed.inject(AuthApi), backend: TestBed.inject(HttpTestingController) };
}

describe('AuthApi', () => {
  it.each(['refresh', 'logout'] as const)('%s_sendsTheCsrfHeader', (name) => {
    const { api, backend } = setup();
    if (name === 'refresh') {
      api.refresh().subscribe();
    } else {
      api.logout().subscribe();
    }
    const request = backend.expectOne(`/api/v1/auth/${name}`);
    expect(request.request.headers.get('X-Requested-With')).toBe('XMLHttpRequest');
    request.flush(null);
    backend.verify();
  });

  it('login_doesNotNeedTheCsrfHeader', () => {
    const { api, backend } = setup();
    api.login({ email: 'a@b.co', password: 'password-123' }).subscribe();
    const request = backend.expectOne('/api/v1/auth/login');
    expect(request.request.headers.has('X-Requested-With')).toBe(false);
    request.flush(null);
  });
});
