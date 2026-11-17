import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';

import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { type AuditEvent } from '@core/api/models';
import { ActivityDialogComponent } from './activity-dialog.component';

const event = (
  id: string,
  action: AuditEvent['action'],
  extra: Partial<AuditEvent> = {},
): AuditEvent => ({
  id,
  created_at: '2026-01-02T10:00:00Z',
  action,
  resource_type: 'file',
  resource_id: 'r1',
  actor_id: 'u1',
  actor_name: 'Ann',
  target_user_id: null,
  detail: null,
  request_id: null,
  ...extra,
});
const isList = (r: { url: string }) => r.url === '/api/v1/audit-events';

describe('ActivityDialogComponent', () => {
  let fixture: ComponentFixture<ActivityDialogComponent>;
  let backend: HttpTestingController;
  const text = () => (fixture.nativeElement as HTMLElement).textContent ?? '';

  const setup = () => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ActivityDialogComponent);
    fixture.componentRef.setInput('resourceId', 'r1');
    fixture.componentRef.setInput('resourceName', 'a.pdf');
    fixture.detectChanges();
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('load_asksForTheResourceAndShowsLoadingThenEvents', () => {
    setup();
    expect((fixture.nativeElement as HTMLElement).querySelector('cd-skeleton')).not.toBeNull();
    const req = backend.expectOne(isList);
    expect(req.request.params.get('resource_id')).toBe('r1');
    req.flush({
      items: [
        event('e1', 'permission.granted', { detail: 'viewer', actor_name: 'Owner' }),
        event('e2', 'file.uploaded', { actor_name: null }),
      ],
      total: 2,
      page: 1,
      page_size: 50,
    });
    fixture.detectChanges();
    expect(text()).toContain('Shared (viewer)');
    expect(text()).toContain('Uploaded');
    expect(text()).toContain('Removed account');
  });

  it('load_emptyShowsAMessage', () => {
    setup();
    backend.expectOne(isList).flush({ items: [], total: 0, page: 1, page_size: 50 });
    fixture.detectChanges();
    expect(text()).toContain('No activity recorded yet.');
  });

  it('load_saysWhenOnlyTheLatestAreShown', () => {
    setup();
    backend
      .expectOne(isList)
      .flush({ items: [event('e1', 'file.downloaded')], total: 120, page: 1, page_size: 50 });
    fixture.detectChanges();
    expect(text()).toContain('Showing the latest 1 of 120.');
  });

  it('load_failureShowsSafeTextAndRetryWorks', () => {
    setup();
    backend.expectOne(isList).flush(ENVELOPE('internal_error'), { status: 500, statusText: 'x' });
    fixture.detectChanges();
    expect(text()).toContain('Something went wrong on our side');
    (
      (fixture.nativeElement as HTMLElement).querySelector(
        'button[type="button"]',
      ) as HTMLButtonElement
    ).click();
    backend.expectOne(isList).flush({ items: [], total: 0, page: 1, page_size: 50 });
  });
});
