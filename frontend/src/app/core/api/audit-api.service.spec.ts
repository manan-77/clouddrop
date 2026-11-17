import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AuditApi } from './audit-api.service';

describe('AuditApi', () => {
  it('forResource_filtersByResourceIdAndPages', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const api = TestBed.inject(AuditApi);
    const backend = TestBed.inject(HttpTestingController);
    api.forResource('r 1', 2, 50).subscribe();
    const req = backend.expectOne((r) => r.url === '/api/v1/audit-events');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('resource_id')).toBe('r 1');
    expect(req.request.params.get('page')).toBe('2');
    expect(req.request.params.get('page_size')).toBe('50');
    req.flush({ items: [], total: 0, page: 2, page_size: 50 });
    backend.verify();
  });
});
