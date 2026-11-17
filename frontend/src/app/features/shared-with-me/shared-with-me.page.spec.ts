import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { type SharedItem } from '@core/api/models';
import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { DownloadService } from '@core/download/download.service';
import { SharedWithMePage } from './shared-with-me.page';

const folder: SharedItem = {
  resource_type: 'folder',
  id: 'd1',
  name: 'Team docs',
  role: 'editor',
  owner_name: 'Ann',
  updated_at: '2026-01-02T10:00:00Z',
  size_bytes: null,
  content_type: null,
  status: null,
};
const file: SharedItem = {
  ...folder,
  resource_type: 'file',
  id: 'f1',
  name: 'plan.pdf',
  role: 'viewer',
  size_bytes: 1536,
  content_type: 'application/pdf',
  status: 'ready',
};
const isList = (r: { url: string }) => r.url === '/api/v1/shared-with-me';

describe('SharedWithMePage', () => {
  const download = { start: vi.fn() };
  let fixture: ComponentFixture<SharedWithMePage>;
  let backend: HttpTestingController;
  const root = () => fixture.nativeElement as HTMLElement;

  const setup = () => {
    TestBed.configureTestingModule({
      providers: [
        ...provideAuthTesting(),
        provideRouter([]),
        { provide: DownloadService, useValue: download },
      ],
    });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SharedWithMePage);
    fixture.detectChanges();
  };
  beforeEach(() => download.start.mockReset());
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('load_showsLoadingThenTheItemsWithRoleAndOwner', () => {
    setup();
    expect(root().querySelector('cd-skeleton')).not.toBeNull();
    backend.expectOne(isList).flush({ items: [folder, file], total: 2, page: 1, page_size: 50 });
    fixture.detectChanges();
    const rows = [...root().querySelectorAll('tbody tr')].map((r) => r.textContent ?? '');
    expect(rows[0]).toContain('Team docs');
    expect(rows[0]).toContain('Can edit');
    expect(rows[0]).toContain('Ann');
    expect(rows[1]).toContain('plan.pdf');
    expect(rows[1]).toContain('Can view');
  });

  it('folders_linkToTheExplorerByIdOnly', () => {
    setup();
    backend.expectOne(isList).flush({ items: [folder], total: 1, page: 1, page_size: 50 });
    fixture.detectChanges();
    expect(root().querySelector('a')?.getAttribute('href')).toBe('/folders/d1');
  });

  it('empty_showsAnExplanation', () => {
    setup();
    backend.expectOne(isList).flush({ items: [], total: 0, page: 1, page_size: 50 });
    fixture.detectChanges();
    expect(root().textContent).toContain('Nothing has been shared with you');
  });

  it('error_showsSafeTextWithRetry', () => {
    setup();
    backend.expectOne(isList).flush(ENVELOPE('internal_error'), { status: 500, statusText: 'x' });
    fixture.detectChanges();
    expect(root().textContent).toContain('Something went wrong on our side');
  });

  it('download_requestsALinkAndStartsTheBrowserDownload', () => {
    setup();
    backend.expectOne(isList).flush({ items: [file], total: 1, page: 1, page_size: 50 });
    fixture.detectChanges();
    (root().querySelector('[aria-label="Download plan.pdf"]') as HTMLButtonElement).click();
    backend
      .expectOne('/api/v1/files/f1/download')
      .flush({ url: 'https://bucket.s3.amazonaws.com/x', expires_in: 300 });
    expect(download.start).toHaveBeenCalledWith('https://bucket.s3.amazonaws.com/x');
  });

  it('download_failureShowsAMessageAndDoesNotStartADownload', () => {
    setup();
    backend.expectOne(isList).flush({ items: [file], total: 1, page: 1, page_size: 50 });
    fixture.detectChanges();
    (root().querySelector('[aria-label="Download plan.pdf"]') as HTMLButtonElement).click();
    backend
      .expectOne('/api/v1/files/f1/download')
      .flush(ENVELOPE('rate_limited'), { status: 429, statusText: 'x' });
    fixture.detectChanges();
    expect(root().textContent).toContain('Too many attempts');
    expect(download.start).not.toHaveBeenCalled();
  });
});
