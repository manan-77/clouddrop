import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SearchApi } from './search-api.service';

describe('SearchApi', () => {
  it('search_sendsTheWordsInTheBodyAndOnlyThePagingInTheUrl', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const api = TestBed.inject(SearchApi);
    const backend = TestBed.inject(HttpTestingController);
    api.search('when is the invoice due', 2, 50).subscribe();
    const req = backend.expectOne((r) => r.url === '/api/v1/search');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ query: 'when is the invoice due' });
    expect(req.request.params.get('page')).toBe('2');
    expect(req.request.params.get('page_size')).toBe('50');
    expect(req.request.urlWithParams).not.toContain('invoice');
    req.flush({ items: [], total: 0, page: 2, page_size: 50 });
    backend.verify();
  });
});
