import { DOCUMENT } from '@angular/common';
import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';

import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { DownloadService } from '@core/download/download.service';
import { PublicLinkPage } from './public-link.page';

const RESOLVE = '/api/v1/public/share-links/resolve';
const DOWNLOAD = '/api/v1/public/share-links/download';
const FILE = {
  file_name: 'plan.pdf',
  size_bytes: 1536,
  content_type: 'application/pdf',
  expires_at: '2026-12-01T10:00:00Z',
};

describe('PublicLinkPage', () => {
  const downloads = { start: vi.fn() };
  let fixture: ComponentFixture<PublicLinkPage>;
  let backend: HttpTestingController;
  const root = () => fixture.nativeElement as HTMLElement;

  const setup = (hash: string) => {
    TestBed.configureTestingModule({
      providers: [
        ...provideAuthTesting(),
        { provide: DownloadService, useValue: downloads },
        { provide: DOCUMENT, useValue: Object.assign(document, {}) },
      ],
    });
    window.location.hash = hash;
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(PublicLinkPage);
    fixture.detectChanges();
  };
  beforeEach(() => downloads.start.mockReset());
  afterEach(() => {
    window.location.hash = '';
    TestBed.inject(HttpTestingController).verify();
  });

  it('noToken_showsTheUnavailableMessageAndSendsNothing', () => {
    setup('');
    expect(root().textContent).toContain('This link is not available.');
  });

  it('token_isReadFromTheFragmentAndSentOnlyInTheBody', () => {
    setup('#secret-token-value');
    const req = backend.expectOne(RESOLVE);
    expect(req.request.body).toEqual({ token: 'secret-token-value' });
    expect(req.request.urlWithParams).not.toContain('secret');
    req.flush(FILE);
    fixture.detectChanges();
    expect(root().textContent).toContain('plan.pdf');
    expect(root().textContent).toContain('1.5 KB');
  });

  it('unusableLink_showsOneSafeMessage', () => {
    setup('#tok');
    backend.expectOne(RESOLVE).flush(ENVELOPE('link_not_found'), { status: 404, statusText: 'x' });
    fixture.detectChanges();
    expect(root().textContent).toContain('This link is not available.');
    expect(root().querySelector('button')).toBeNull();
  });

  it('download_startsTheBrowserDownloadFromTheReturnedLink', () => {
    setup('#tok');
    backend.expectOne(RESOLVE).flush(FILE);
    fixture.detectChanges();
    (root().querySelector('button') as HTMLButtonElement).click();
    backend
      .expectOne(DOWNLOAD)
      .flush({ url: 'https://bucket.s3.amazonaws.com/x', expires_in: 300 });
    expect(downloads.start).toHaveBeenCalledWith('https://bucket.s3.amazonaws.com/x');
  });

  it('download_failureShowsAMessageAndTheButtonWorksAgain', () => {
    setup('#tok');
    backend.expectOne(RESOLVE).flush(FILE);
    fixture.detectChanges();
    const button = root().querySelector('button') as HTMLButtonElement;
    button.click();
    backend.expectOne(DOWNLOAD).flush(ENVELOPE('rate_limited'), { status: 429, statusText: 'x' });
    fixture.detectChanges();
    expect(root().textContent).toContain('Too many attempts');
    expect(button.disabled).toBe(false);
    expect(downloads.start).not.toHaveBeenCalled();
  });

  it('download_aSecondClickWhileRunningIsIgnored', () => {
    setup('#tok');
    backend.expectOne(RESOLVE).flush(FILE);
    fixture.detectChanges();
    const button = root().querySelector('button') as HTMLButtonElement;
    button.click();
    button.click();
    expect(backend.match(DOWNLOAD)).toHaveLength(1);
  });
});
