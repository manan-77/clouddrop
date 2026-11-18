import { DOCUMENT } from '@angular/common';
import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

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
const POST = (r: { url: string; method: string }) => r.url === BASE && r.method === 'POST';
const page = (...items: ShareLink[]) => ({ items, total: items.length, page: 1, page_size: 50 });

describe('ShareLinksComponent', () => {
  let fixture: ComponentFixture<ShareLinksComponent>;
  let backend: HttpTestingController;
  const root = () => fixture.nativeElement as HTMLElement;
  const text = () => root().textContent ?? '';
  const click = (selector: string) => (root().querySelector(selector) as HTMLButtonElement).click();

  const start = () => {
    TestBed.configureTestingModule({ providers: [...provideAuthTesting(), provideRouter([])] });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ShareLinksComponent);
    fixture.componentRef.setInput('fileId', 'f1');
    fixture.detectChanges();
  };
  const setup = (...existing: ShareLink[]) => {
    start();
    backend.expectOne(LIST).flush(page(...existing));
    fixture.detectChanges();
  };
  const make = (days?: string) => {
    if (days) {
      const select = root().querySelector('#link-days') as HTMLSelectElement;
      select.value = days;
      select.dispatchEvent(new Event('change'));
    }
    click('.make button');
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('list_showsLoadingThenAnEmptyMessage', () => {
    start();
    expect(text()).toContain('Loading links');
    backend.expectOne(LIST).flush(page());
    fixture.detectChanges();
    expect(text()).toContain('No links yet.');
    expect(text()).not.toContain('Loading links');
  });

  it('list_failureHasItsOwnMessage', () => {
    start();
    backend.expectOne(LIST).flush(ENVELOPE('forbidden'), { status: 404, statusText: 'x' });
    fixture.detectChanges();
    expect(text()).toContain('You do not have permission to do that.');
    expect(text()).not.toContain('No links yet.');
  });

  it('list_showsActiveAndTurnedOffLinksAndOnlyActiveOnesCanBeTurnedOff', () => {
    setup(link('a'), link('b', '2026-11-02T10:00:00Z'));
    const rows = [...root().querySelectorAll('.links li')].map((r) => r.textContent ?? '');
    expect(rows[0]).toContain('Active');
    expect(rows[1]).toContain('Turned off');
    expect(root().querySelectorAll('.links li button')).toHaveLength(1);
  });

  it('create_sendsTheChosenExpiryAndShowsTheAddressOnceWithTheTokenInTheFragment', () => {
    setup();
    make('30');
    const req = backend.expectOne(POST);
    expect(req.request.body).toEqual({ expires_in_days: 30 });
    req.flush({ ...link('l1'), token: 'tok-abc' }, { status: 201, statusText: 'Created' });
    backend.expectOne(LIST).flush(page(link('l1')));
    fixture.detectChanges();
    const origin = TestBed.inject(DOCUMENT).location.origin;
    const field = root().querySelector('input[aria-label="Link address"]') as HTMLInputElement;
    expect(field.value).toBe(`${origin}/s#tok-abc`);
    expect(text()).toContain('It is not shown again.');
    expect(text()).toContain('Link created. Copy it now.');
  });

  it('create_aSecondClickWhileRunningIsIgnored', () => {
    setup();
    make();
    click('.make button');
    expect(backend.match(POST)).toHaveLength(1);
  });

  it('create_anotherLinkReplacesTheAddressOnScreen', () => {
    setup();
    make();
    backend
      .expectOne(POST)
      .flush({ ...link('l1'), token: 'first' }, { status: 201, statusText: 'C' });
    backend.expectOne(LIST).flush(page(link('l1')));
    fixture.detectChanges();
    expect(root().querySelector('input[aria-label="Link address"]')).not.toBeNull();
    make();
    const second = backend.expectOne(POST);
    fixture.detectChanges();
    expect(root().querySelector('input[aria-label="Link address"]')).toBeNull();
    second.flush({ ...link('l2'), token: 'second' }, { status: 201, statusText: 'C' });
    backend.expectOne(LIST).flush(page(link('l2'), link('l1')));
    fixture.detectChanges();
    const field = root().querySelector('input[aria-label="Link address"]') as HTMLInputElement;
    expect(field.value).toContain('#second');
    expect(field.value).not.toContain('first');
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
    make();
    backend.expectOne(POST).flush(ENVELOPE(code), { status, statusText: 'x' });
    fixture.detectChanges();
    expect(text()).toContain(message);
    expect(root().querySelector('input[aria-label="Link address"]')).toBeNull();
  });

  it('revoke_deletesTheLinkReloadsAndAnnounces', () => {
    setup(link('l1'));
    click('.links li button');
    const req = backend.expectOne(`${BASE}/l1`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });
    backend.expectOne(LIST).flush(page(link('l1', '2026-11-02T10:00:00Z')));
    fixture.detectChanges();
    expect(text()).toContain('Turned off');
    expect(text()).toContain('Link turned off.');
  });

  it('revoke_ofTheLinkJustMadeRemovesItsAddressFromTheScreen', () => {
    setup();
    make();
    backend
      .expectOne(POST)
      .flush({ ...link('l1'), token: 'tok' }, { status: 201, statusText: 'C' });
    backend.expectOne(LIST).flush(page(link('l1')));
    fixture.detectChanges();
    expect(root().querySelector('input[aria-label="Link address"]')).not.toBeNull();
    click('.links li button');
    backend.expectOne(`${BASE}/l1`).flush(null, { status: 204, statusText: 'No Content' });
    backend.expectOne(LIST).flush(page(link('l1', '2026-11-02T10:00:00Z')));
    fixture.detectChanges();
    expect(root().querySelector('input[aria-label="Link address"]')).toBeNull();
  });

  it('revoke_ofADifferentLinkKeepsTheNewAddress', () => {
    setup(link('old'));
    make();
    backend
      .expectOne(POST)
      .flush({ ...link('new'), token: 'tok' }, { status: 201, statusText: 'C' });
    backend.expectOne(LIST).flush(page(link('new'), link('old')));
    fixture.detectChanges();
    const buttons = root().querySelectorAll('.links li button');
    (buttons[1] as HTMLButtonElement).click();
    backend.expectOne(`${BASE}/old`).flush(null, { status: 204, statusText: 'No Content' });
    backend.expectOne(LIST).flush(page(link('new'), link('old', '2026-11-02T10:00:00Z')));
    fixture.detectChanges();
    expect(root().querySelector('input[aria-label="Link address"]')).not.toBeNull();
  });
});
