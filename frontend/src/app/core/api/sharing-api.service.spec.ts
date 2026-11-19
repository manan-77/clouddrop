import { MAX_PAGE_SIZE } from './pagination';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SharingApi } from './sharing-api.service';

describe('SharingApi', () => {
  const setup = () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    return { api: TestBed.inject(SharingApi), backend: TestBed.inject(HttpTestingController) };
  };

  it('list_usesTheResourcePathAndPaging', () => {
    const { api, backend } = setup();
    api.list('folders', 'f 1', 2, 100).subscribe();
    const req = backend.expectOne((r) => r.url === '/api/v1/folders/f%201/permissions');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('page')).toBe('2');
    expect(req.request.params.get('page_size')).toBe('100');
    req.flush({ items: [], total: 0, page: 2, page_size: MAX_PAGE_SIZE });
  });

  it('grant_postsEmailAndRole', () => {
    const { api, backend } = setup();
    api.grant('files', 'a', 'x@y.co', 'editor').subscribe();
    const req = backend.expectOne('/api/v1/files/a/permissions');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ email: 'x@y.co', role: 'editor' });
    req.flush({});
  });

  it('changeRoleAndRevoke_targetTheGrant', () => {
    const { api, backend } = setup();
    api.changeRole('files', 'a', 'p1', 'viewer').subscribe();
    const patch = backend.expectOne('/api/v1/files/a/permissions/p1');
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ role: 'viewer' });
    patch.flush({});
    api.revoke('folders', 'b', 'p2').subscribe();
    const del = backend.expectOne('/api/v1/folders/b/permissions/p2');
    expect(del.request.method).toBe('DELETE');
    del.flush(null);
  });

  it('sharedWithMe_isPaged', () => {
    const { api, backend } = setup();
    api.sharedWithMe(3, 50).subscribe();
    const req = backend.expectOne((r) => r.url === '/api/v1/shared-with-me');
    expect(req.request.params.get('page')).toBe('3');
    req.flush({ items: [], total: 0, page: 3, page_size: 50 });
  });
});
