import { DOCUMENT } from '@angular/common';
import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';

import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { type ShareLink } from '@core/api/models';
import { ShareLinksComponent } from './share-links.component';

const link = (id: string, revoked: string | null = null): ShareLink => ({
  id,
  expires_at: '2026-12-01T10:00:00Z',
  revoked_at: revoked,
  created_at: '2026-11-01T10:00:00Z',
});
const BASE = '/api/v1/files/f1/share-links';
const LIST = (r: { url: string; method: string }) => r.url === BASE && r.method === 'GET';
const page = (...items: ShareLink[]) => ({ items, total: items.length, page: 1, page_size: 50 });

describe('ShareLinksComponent', () => {
  let fixture: ComponentFixture<ShareLinksComponent>;
  let backend: HttpTestingController;
  const root = () => fixture.nativeElement as HTMLElement;
  const text = () => root().textContent ?? '';
  const click = (selector: string) => (root().querySelector(selector) as HTMLButtonElement).click();

  const setup = () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ShareLinksComponent);
    fixture.componentRef.setInput('fileId', 'f1');
    fixture.detectChanges();
    backend.expectOne(LIST).flush(page());
    fixture.detectChanges();
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('create_sendsTheChosenExpiryAndShowsTheAddressOnce', () => {
    setup();
    const select = root().querySelector('#link-days') as HTMLSelectElement;
    select.value = '30';
    select.dispatchEvent(new Event('change'));
    click('.make button');
    const req = backend.expectOne((r) => r.url === BASE && r.method === 'POST');
    expect(req.request.body).toEqual({ expires_in_days: 30 });
    req.flush({ ...link('l1'), token: 'tok-abc' }, { status: 201, statusText: 'Created' });
    backend.expectOne(LIST).flush(page(link('l1')));
    fixture.detectChanges();
    const origin = TestBed.inject(DOCUMENT).location.origin;
    const field = root().querySelector('input[aria-label="Link address"]') as HTMLInputElement;
    // The token is in the fragment, so no server ever sees it.
    expect(field.value).toBe(`${origin}/s#tok-abc`);
    expect(text()).toContain('It is not shown again.');
  });

  it('create_aSecondClickWhileRunningIsIgnored', () => {
    setup();
    click('.make button');
    click('.make button');
    expect(backend.match((r) => r.url === BASE && r.method === 'POST')).toHaveLength(1);
  });

  it.each([
    [
      'too_many_links',
      422,
      'This file already has the most links it can have. Turn one off first.',
    ],
    ['file_not_ready', 409, 'This file is not available yet.'],
    ['link_too_long', 422, 'A link cannot last that long.'],
  ])('create_%s_isShownAsSafeText', (code, status, message) => {
    setup();
    click('.make button');
    backend
      .expectOne((r) => r.url === BASE && r.method === 'POST')
      .flush(ENVELOPE(code), { status, statusText: 'x' });
    fixture.detectChanges();
    expect(text()).toContain(message);
    expect(root().querySelector('input[aria-label="Link address"]')).toBeNull();
  });

  it('list_showsActiveAndTurnedOffLinksAndOnlyActiveOnesCanBeTurnedOff', () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ShareLinksComponent);
    fixture.componentRef.setInput('fileId', 'f1');
    fixture.detectChanges();
    backend.expectOne(LIST).flush(page(link('a'), link('b', '2026-11-02T10:00:00Z')));
    fixture.detectChanges();
    const rows = [...root().querySelectorAll('.links li')].map((r) => r.textContent ?? '');
    expect(rows[0]).toContain('Active');
    expect(rows[1]).toContain('Turned off');
    expect(root().querySelectorAll('.links li button')).toHaveLength(1);
  });

  it('revoke_deletesTheLinkAndReloadsTheList', () => {
    setup();
    click('.make button');
    backend
      .expectOne((r) => r.url === BASE && r.method === 'POST')
      .flush({ ...link('l1'), token: 't' }, { status: 201, statusText: 'Created' });
    backend.expectOne(LIST).flush(page(link('l1')));
    fixture.detectChanges();
    click('.links li button');
    const req = backend.expectOne(`${BASE}/l1`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });
    backend.expectOne(LIST).flush(page(link('l1', '2026-11-02T10:00:00Z')));
    fixture.detectChanges();
    expect(text()).toContain('Turned off');
  });

  it('copy_usesTheClipboardAndSaysSo', async () => {
    setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(TestBed.inject(DOCUMENT).defaultView!.navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    click('.make button');
    backend
      .expectOne((r) => r.url === BASE && r.method === 'POST')
      .flush({ ...link('l1'), token: 'tok' }, { status: 201, statusText: 'Created' });
    backend.expectOne(LIST).flush(page(link('l1')));
    fixture.detectChanges();
    click('.created button');
    await fixture.whenStable();
    fixture.detectChanges();
    expect(writeText).toHaveBeenCalledOnce();
    expect(text()).toContain('Copied.');
  });
});
