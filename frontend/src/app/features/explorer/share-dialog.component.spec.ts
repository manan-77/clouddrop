import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';

import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { type GrantRead } from '@core/api/models';
import { ShareDialogComponent } from './share-dialog.component';

const grant = (id: string, email: string, role: GrantRead['role'] = 'viewer'): GrantRead => ({
  id,
  email,
  display_name: email.split('@')[0],
  role,
  created_at: '2026-01-02T10:00:00Z',
});
const LIST = (r: { url: string; method: string }) =>
  r.url === '/api/v1/folders/f1/permissions' && r.method === 'GET';
const POST = '/api/v1/folders/f1/permissions';
const emptyPage = { items: [], total: 0, page: 1, page_size: 100 };
const pageOf = (...items: GrantRead[]) => ({ ...emptyPage, items, total: items.length });

describe('ShareDialogComponent', () => {
  let fixture: ComponentFixture<ShareDialogComponent>;
  let backend: HttpTestingController;
  const root = () => fixture.nativeElement as HTMLElement;
  const text = () => root().textContent ?? '';
  const type = (value: string) => {
    const input = root().querySelector('#share-email') as HTMLInputElement;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  };
  const submit = () => {
    (root().querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
    fixture.detectChanges();
  };

  const setup = () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ShareDialogComponent);
    fixture.componentRef.setInput('kind', 'folders');
    fixture.componentRef.setInput('resourceId', 'f1');
    fixture.componentRef.setInput('resourceName', 'Docs');
    fixture.detectChanges();
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('load_showsALoadingStateThenAnEmptyMessage', () => {
    setup();
    expect(root().querySelector('cd-skeleton')).not.toBeNull();
    backend.expectOne(LIST).flush(emptyPage);
    fixture.detectChanges();
    expect(text()).toContain('Nobody else has access yet.');
  });

  it('load_failureShowsAnErrorAndRetryReloads', () => {
    setup();
    backend.expectOne(LIST).flush(ENVELOPE('forbidden'), { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
    const alerts = [...root().querySelectorAll('[role="alert"]')].map((a) => a.textContent?.trim());
    expect(alerts.some((a) => a && a.length > 0)).toBe(true);
    (root().querySelector('button[type="button"]') as HTMLButtonElement).click();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co')));
    fixture.detectChanges();
    expect(text()).toContain('ann@x.co');
  });

  it('add_invalidEmailIsShownInlineAndNothingIsSent', () => {
    setup();
    backend.expectOne(LIST).flush(emptyPage);
    type('not-an-email');
    submit();
    expect(text()).toContain('Enter a valid email address.');
    backend.expectNone(POST);
    type('');
    submit();
    expect(text()).toContain('Email is required.');
    backend.expectNone(POST);
  });

  it('add_sendsEmailAndRoleThenReloadsTheListAndClearsTheField', () => {
    setup();
    backend.expectOne(LIST).flush(emptyPage);
    type('  Bob@X.co ');
    const select = root().querySelector('#share-role') as HTMLSelectElement;
    select.value = 'editor';
    select.dispatchEvent(new Event('change'));
    submit();
    const req = backend.expectOne(POST);
    expect(req.request.body).toEqual({ email: 'Bob@X.co', role: 'editor' });
    req.flush(grant('p1', 'bob@x.co', 'editor'), { status: 201, statusText: 'Created' });
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'bob@x.co', 'editor')));
    fixture.detectChanges();
    expect(text()).toContain('Access saved.');
    expect(text()).toContain('bob@x.co');
    expect((root().querySelector('#share-email') as HTMLInputElement).value).toBe('');
  });

  it('add_aSecondSubmitWhileTheFirstRunsIsIgnored', () => {
    setup();
    backend.expectOne(LIST).flush(emptyPage);
    type('a@x.co');
    submit();
    submit();
    expect(backend.match(POST)).toHaveLength(1);
  });

  it.each([
    ['user_not_found', 'There is no account with that email address.'],
    ['cannot_share_with_self', 'You already own this.'],
    ['file_not_ready', 'This file is not available yet.'],
  ])('add_serverRefusal_%s_isShownAsSafeText', (code, message) => {
    setup();
    backend.expectOne(LIST).flush(emptyPage);
    type('a@x.co');
    submit();
    backend.expectOne(POST).flush(ENVELOPE(code), { status: 404, statusText: 'x' });
    backend.expectOne(LIST).flush(emptyPage);
    fixture.detectChanges();
    expect(text()).toContain(message);
  });

  it('changeRole_patchesTheGrantAndReloads', () => {
    setup();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'viewer')));
    fixture.detectChanges();
    const select = root().querySelector('select[aria-label="Access for ann"]') as HTMLSelectElement;
    select.value = 'editor';
    select.dispatchEvent(new Event('change'));
    const req = backend.expectOne(`${POST}/p1`);
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ role: 'editor' });
    req.flush(grant('p1', 'ann@x.co', 'editor'));
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'editor')));
    fixture.detectChanges();
    expect(text()).toContain('Access updated.');
  });

  it('changeRole_toTheSameRoleSendsNothing', () => {
    setup();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'viewer')));
    fixture.detectChanges();
    const select = root().querySelector('select[aria-label="Access for ann"]') as HTMLSelectElement;
    select.value = 'viewer';
    select.dispatchEvent(new Event('change'));
    backend.expectNone(`${POST}/p1`);
  });

  it('revoke_deletesTheGrantAndReloads', () => {
    setup();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co')));
    fixture.detectChanges();
    (root().querySelector('[aria-label="Remove access for ann"]') as HTMLButtonElement).click();
    const req = backend.expectOne(`${POST}/p1`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });
    backend.expectOne(LIST).flush(emptyPage);
    fixture.detectChanges();
    expect(text()).toContain('Access removed.');
    expect(text()).toContain('Nobody else has access yet.');
  });

  it('revoke_failureShowsTheMessageAndTheDialogStaysUsable', () => {
    setup();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co')));
    fixture.detectChanges();
    (root().querySelector('[aria-label="Remove access for ann"]') as HTMLButtonElement).click();
    backend
      .expectOne(`${POST}/p1`)
      .flush(ENVELOPE('permission_not_found'), { status: 404, statusText: 'x' });
    backend.expectOne(LIST).flush(emptyPage);
    fixture.detectChanges();
    expect(text()).toContain('That access no longer exists.');
    const button = root().querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });
});
