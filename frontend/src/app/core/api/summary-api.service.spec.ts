import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SummaryApi } from './summary-api.service';

describe('SummaryApi', () => {
  const setup = () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    return { api: TestBed.inject(SummaryApi), backend: TestBed.inject(HttpTestingController) };
  };

  it('get_readsTheSummaryOfThatFile', () => {
    const { api, backend } = setup();
    api.get('f 1').subscribe();
    const req = backend.expectOne('/api/v1/files/f%201/summary');
    expect(req.request.method).toBe('GET');
    req.flush({});
    backend.verify();
  });

  it('request_postsWithNoBodyToAskForANewOne', () => {
    const { api, backend } = setup();
    api.request('f1').subscribe();
    const req = backend.expectOne('/api/v1/files/f1/summary');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toBeNull();
    req.flush({}, { status: 202, statusText: 'Accepted' });
    backend.verify();
  });
});
