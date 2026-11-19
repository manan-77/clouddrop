import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';

import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { type GrantRead } from '@core/api/models';
import { MAX_PAGE_SIZE } from '@core/api/pagination';
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
const emptyPage = { items: [], total: 0, page: 1, page_size: MAX_PAGE_SIZE };
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

  it('load_failureShowsTheSafeMessageAndRetryReloads', () => {
    setup();
    backend.expectOne(LIST).flush(ENVELOPE('forbidden'), { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
    expect(text()).toContain('You do not have permission to do that.');
    (root().querySelector('button[type="button"]') as HTMLButtonElement).click();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co')));
    fixture.detectChanges();
    expect(text()).toContain('ann@x.co');
    expect(text()).not.toContain('You do not have permission to do that.');
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

  it.each(['a@b', 'a@b.', '@b.co', 'a b@c.co'])(
    'add_%s_isRejectedInlineLikeTheServerWould',
    (value) => {
      setup();
      backend.expectOne(LIST).flush(emptyPage);
      type(value);
      submit();
      expect(text()).toContain('Enter a valid email address.');
      backend.expectNone(POST);
    },
  );

  it('add_whitespaceOnlyAndOverlongEmailsAreRejected', () => {
    setup();
    backend.expectOne(LIST).flush(emptyPage);
    type('   ');
    submit();
    expect(text()).toContain('Email is required.');
    type(`${'a'.repeat(320)}@x.co`);
    submit();
    expect(text()).toMatch(/Enter a valid email address\.|Email must be at most 320 characters\./);
    backend.expectNone(POST);
  });

  it.each([
    [429, 'rate_limited', 'Too many attempts. Please wait a moment and try again.'],
    [422, 'validation_error', 'Please check the highlighted fields.'],
    [404, 'user_not_found', 'There is no account with that email address.'],
  ])('add_status%i_isShownAndTheFormIsUsableAgain', (status, code, message) => {
    setup();
    backend.expectOne(LIST).flush(emptyPage);
    type('a@x.co');
    submit();
    backend.expectOne(POST).flush(ENVELOPE(code), { status, statusText: 'x' });
    backend.expectOne(LIST).flush(emptyPage);
    fixture.detectChanges();
    expect(text()).toContain(message);
    expect((root().querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it('add_aSuccessfulSaveLeavesTheFormUsableAndTypingClearsTheNotice', () => {
    setup();
    backend.expectOne(LIST).flush(emptyPage);
    type('a@x.co');
    submit();
    backend.expectOne(POST).flush(grant('p1', 'a@x.co'), { status: 201, statusText: 'Created' });
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'a@x.co')));
    fixture.detectChanges();
    expect(text()).toContain('Access saved.');
    expect((root().querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(
      false,
    );
    type('b');
    expect(text()).not.toContain('Access saved.');
  });

  it('files_usesTheFilesPath', () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ShareDialogComponent);
    fixture.componentRef.setInput('kind', 'files');
    fixture.componentRef.setInput('resourceId', 'x1');
    fixture.componentRef.setInput('resourceName', 'a.pdf');
    fixture.detectChanges();
    backend
      .expectOne((r) => r.url === '/api/v1/files/x1/permissions' && r.method === 'GET')
      .flush(emptyPage);
    // A file's dialog also lists its share links.
    backend
      .expectOne((r) => r.url === '/api/v1/files/x1/share-links' && r.method === 'GET')
      .flush({ items: [], total: 0, page: 1, page_size: 50 });
  });

  it('changeRole_refusedShowsTheSavedRoleAgain', () => {
    setup();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'viewer')));
    fixture.detectChanges();
    const select = () =>
      root().querySelector('select[aria-label="Access for ann"]') as HTMLSelectElement;
    select().value = 'editor';
    select().dispatchEvent(new Event('change'));
    backend.expectOne(`${POST}/p1`).flush(ENVELOPE('forbidden'), { status: 404, statusText: 'x' });
    fixture.detectChanges(); // the list shows as loading while it is read again
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'viewer')));
    fixture.detectChanges();
    // The rows were rebuilt from the stored roles, so the refused value is gone.
    expect(select().value).toBe('viewer');
    expect(text()).toContain('You do not have permission to do that.');
  });

  it('reload_keepsTheListOnScreenAndTheNewestResponseWins', () => {
    setup();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co')));
    fixture.detectChanges();
    (root().querySelector('[aria-label="Remove access for ann"]') as HTMLButtonElement).click();
    backend.expectOne(`${POST}/p1`).flush(null, { status: 204, statusText: 'No Content' });
    // The list stays on screen while the reload is pending.
    expect(root().querySelector('cd-skeleton')).toBeNull();
    expect(text()).toContain('ann@x.co');
    // A second write starts a second reload before the first has answered.
    type('b@x.co');
    submit();
    backend.expectOne(POST).flush(grant('p2', 'b@x.co'), { status: 201, statusText: 'Created' });
    const [older, newer] = backend.match(LIST);
    // The older request is cancelled outright, so it can never overwrite the newer list.
    expect(older.cancelled).toBe(true);
    newer.flush(pageOf(grant('p2', 'b@x.co')));
    fixture.detectChanges();
    expect(text()).toContain('b@x.co');
  });

  it('changeRole_whileAnotherActionIsRunningIsIgnoredAndSendsNothing', () => {
    setup();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'viewer')));
    fixture.detectChanges();
    type('b@x.co');
    submit(); // an add is now running
    const select = root().querySelector('select[aria-label="Access for ann"]') as HTMLSelectElement;
    select.value = 'editor';
    select.dispatchEvent(new Event('change'));
    backend.expectNone(`${POST}/p1`);
    backend.expectOne(POST).flush(grant('p2', 'b@x.co'), { status: 201, statusText: 'Created' });
    fixture.detectChanges();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'viewer')));
    fixture.detectChanges();
    expect(root().querySelector('cd-skeleton')).toBeNull();
    expect(
      (root().querySelector('select[aria-label="Access for ann"]') as HTMLSelectElement).value,
    ).toBe('viewer');
  });

  it('focus_goesToTheEmailFieldAfterAnAddAndAfterARevokeButNotAfterARoleChange', () => {
    setup();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'viewer')));
    fixture.detectChanges();
    const email = root().querySelector('#share-email') as HTMLInputElement;
    const roleSelect = root().querySelector(
      'select[aria-label="Access for ann"]',
    ) as HTMLSelectElement;
    roleSelect.focus();
    roleSelect.value = 'editor';
    roleSelect.dispatchEvent(new Event('change'));
    backend.expectOne(`${POST}/p1`).flush(grant('p1', 'ann@x.co', 'editor'));
    expect(document.activeElement).not.toBe(email);
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'editor')));
    fixture.detectChanges();
    (root().querySelector('[aria-label="Remove access for ann"]') as HTMLButtonElement).click();
    backend.expectOne(`${POST}/p1`).flush(null, { status: 204, statusText: 'No Content' });
    expect(document.activeElement).toBe(email);
    backend.expectOne(LIST).flush(emptyPage);
  });

  it('aRefusedChangeMovesFocusToTheMessage', () => {
    setup();
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'viewer')));
    fixture.detectChanges();
    const roleSelect = root().querySelector(
      'select[aria-label="Access for ann"]',
    ) as HTMLSelectElement;
    roleSelect.value = 'editor';
    roleSelect.dispatchEvent(new Event('change'));
    backend.expectOne(`${POST}/p1`).flush(ENVELOPE('forbidden'), { status: 404, statusText: 'x' });
    expect((document.activeElement as HTMLElement).getAttribute('role')).toBe('alert');
    backend.expectOne(LIST).flush(pageOf(grant('p1', 'ann@x.co', 'viewer')));
  });
});
