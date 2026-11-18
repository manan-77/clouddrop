import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ShareLinksApi } from './share-links-api.service';

describe('ShareLinksApi', () => {
  const setup = () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    return { api: TestBed.inject(ShareLinksApi), backend: TestBed.inject(HttpTestingController) };
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('create_postsTheExpiryToTheFilesLinks', () => {
    const { api, backend } = setup();
    api.create('f 1', 7).subscribe();
    const req = backend.expectOne('/api/v1/files/f%201/share-links');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ expires_in_days: 7 });
    req.flush({});
  });

  it('list_andRevoke_targetTheFileAndLink', () => {
    const { api, backend } = setup();
    api.list('f1', 1, 50).subscribe();
    const list = backend.expectOne((r) => r.url === '/api/v1/files/f1/share-links');
    expect(list.request.params.get('page_size')).toBe('50');
    list.flush({ items: [], total: 0, page: 1, page_size: 50 });
    api.revoke('f1', 'l1').subscribe();
    const del = backend.expectOne('/api/v1/files/f1/share-links/l1');
    expect(del.request.method).toBe('DELETE');
    del.flush(null);
  });

  it('resolveAndDownload_putTheTokenInTheBodyNeverTheUrl', () => {
    const { api, backend } = setup();
    api.resolve('secret-token').subscribe();
    const resolve = backend.expectOne('/api/v1/public/share-links/resolve');
    expect(resolve.request.body).toEqual({ token: 'secret-token' });
    expect(resolve.request.urlWithParams).not.toContain('secret-token');
    resolve.flush({});
    api.download('secret-token').subscribe();
    const download = backend.expectOne('/api/v1/public/share-links/download');
    expect(download.request.body).toEqual({ token: 'secret-token' });
    expect(download.request.urlWithParams).not.toContain('secret-token');
    download.flush({});
  });
});
