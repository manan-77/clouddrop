import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { BehaviorSubject } from 'rxjs';

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

  let fragment$: BehaviorSubject<string | null>;
  // The route's fragment is the token, so the spec drives it like the router would.
  const setup = (hash: string) => {
    fragment$ = new BehaviorSubject<string | null>(hash.replace(/^#/, '') || null);
    TestBed.configureTestingModule({
      providers: [
        ...provideAuthTesting(),
        { provide: DownloadService, useValue: downloads },
        { provide: ActivatedRoute, useValue: { fragment: fragment$ } },
      ],
    });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(PublicLinkPage);
    fixture.detectChanges();
  };
  beforeEach(() => downloads.start.mockReset());
  afterEach(() => TestBed.inject(HttpTestingController).verify());

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

  it('download_aRefusedUrlShowsAMessageInsteadOfDoingNothing', () => {
    downloads.start.mockImplementationOnce(() => {
      throw new Error('Refusing to download from a non-http link');
    });
    setup('#tok');
    backend.expectOne(RESOLVE).flush(FILE);
    fixture.detectChanges();
    (root().querySelector('button') as HTMLButtonElement).click();
    backend.expectOne(DOWNLOAD).flush({ url: 'javascript:alert(1)', expires_in: 300 });
    fixture.detectChanges();
    expect(root().textContent).toContain('The download could not be started.');
    expect(root().textContent).not.toContain('javascript');
  });

  it('aNewFragmentInTheSameTab_resolvesTheNewLinkAndDownloadsThatOne', () => {
    setup('#first-token');
    backend.expectOne(RESOLVE).flush(FILE);
    fixture.detectChanges();
    expect(root().textContent).toContain('plan.pdf');
    // Another link pasted into the same tab: no page reload, only the fragment changes.
    fragment$.next('second-token');
    fixture.detectChanges();
    expect(root().textContent).not.toContain('plan.pdf');
    const again = backend.expectOne(RESOLVE);
    expect(again.request.body).toEqual({ token: 'second-token' });
    again.flush({ ...FILE, file_name: 'other.pdf' });
    fixture.detectChanges();
    expect(root().textContent).toContain('other.pdf');
    (root().querySelector('button') as HTMLButtonElement).click();
    expect(backend.expectOne(DOWNLOAD).request.body).toEqual({ token: 'second-token' });
  });

  it('aNewFragmentThatIsEmpty_dropsTheOldFileAndShowsTheUnavailableMessage', () => {
    setup('#first-token');
    backend.expectOne(RESOLVE).flush(FILE);
    fixture.detectChanges();
    fragment$.next(null);
    fixture.detectChanges();
    expect(root().textContent).not.toContain('plan.pdf');
    expect(root().textContent).toContain('This link is not available.');
    expect(root().querySelector('button')).toBeNull();
  });

  it('aNewFragmentWhileTheOldOneIsResolving_ignoresTheOlderAnswer', () => {
    setup('#first-token');
    const older = backend.expectOne(RESOLVE);
    fragment$.next('second-token');
    expect(older.cancelled).toBe(true);
    backend.expectOne(RESOLVE).flush({ ...FILE, file_name: 'second.pdf' });
    fixture.detectChanges();
    expect(root().textContent).toContain('second.pdf');
  });
});
