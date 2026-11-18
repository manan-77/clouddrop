import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';

import { type CallerRole, type FileRead, type FolderRead } from '@core/api/models';
import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { MoveDialogComponent } from './move-dialog.component';

const STAMP = '2026-01-02T10:00:00Z';
const folder = (id: string, role: CallerRole = 'owner'): FolderRead => ({
  id,
  parent_id: null,
  name: `Folder ${id}`,
  created_at: STAMP,
  updated_at: STAMP,
  role,
});
const FILE: FileRead = {
  id: 'a',
  folder_id: 'here',
  name: 'plan.pdf',
  content_type: 'application/pdf',
  size_bytes: 1,
  status: 'ready',
  created_at: STAMP,
  updated_at: STAMP,
  role: 'owner',
};
const LIST = (r: { url: string }) => r.url === '/api/v1/folders';
const page = (items: FolderRead[], total = items.length) => ({
  items,
  total,
  page: 1,
  page_size: 20,
});

describe('MoveDialogComponent', () => {
  let fixture: ComponentFixture<MoveDialogComponent>;
  let backend: HttpTestingController;
  const root = () => fixture.nativeElement as HTMLElement;
  const buttons = () => [...root().querySelectorAll('button')];
  const byLabel = (label: string) =>
    buttons().find(
      (b) => b.textContent?.trim() === label || b.getAttribute('aria-label') === label,
    );
  const moveHere = () => byLabel('Move here') as HTMLButtonElement;
  const settle = async () => {
    await fixture.whenStable();
    fixture.detectChanges();
  };

  const setup = async (file: FileRead = FILE) => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(MoveDialogComponent);
    fixture.componentRef.setInput('file', file);
    fixture.detectChanges();
    await settle();
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('opensAtTheTopLevelAndOffersToMoveThereOnlyWhenTheFileIsElsewhere', async () => {
    await setup();
    backend.expectOne(LIST).flush(page([folder('f1')]));
    await settle();
    expect(root().textContent).toContain('Folder f1');
    expect(moveHere().disabled).toBe(false);
  });

  it('theFolderTheFileIsAlreadyInCannotBeChosen', async () => {
    await setup({ ...FILE, folder_id: null });
    backend.expectOne(LIST).flush(page([]));
    await settle();
    expect(moveHere().disabled).toBe(true);
    expect(root().textContent).toContain('No folders here');
  });

  it('movedEmitsTheTopLevelAsNull', async () => {
    await setup();
    const moved = vi.fn();
    fixture.componentInstance.moved.subscribe(moved);
    backend.expectOne(LIST).flush(page([]));
    await settle();
    moveHere().click();
    expect(moved).toHaveBeenCalledWith(null);
  });

  it('opensAFolderAndGoesBackUpThroughTheTrail', async () => {
    await setup({ ...FILE, folder_id: null });
    const moved = vi.fn();
    fixture.componentInstance.moved.subscribe(moved);
    backend.expectOne(LIST).flush(page([folder('f1')]));
    await settle();
    (byLabel('Open folder Folder f1') as HTMLButtonElement).click();
    await settle();
    expect(backend.expectOne(LIST).request.params.get('parent_id')).toBe('f1');
    (byLabel('All files') as HTMLButtonElement).click();
    await settle();
    expect(backend.expectOne(LIST).request.params.has('parent_id')).toBe(false);
    expect(moved).not.toHaveBeenCalled();
  });

  it('aFolderTheCallerCannotWriteToCannotBeChosen', async () => {
    await setup({ ...FILE, folder_id: null });
    backend.expectOne(LIST).flush(page([folder('f1', 'viewer')]));
    await settle();
    (byLabel('Open folder Folder f1') as HTMLButtonElement).click();
    await settle();
    backend.expectOne(LIST).flush(page([]));
    await settle();
    expect(moveHere().disabled).toBe(true);
  });

  it('aFailedListShowsSafeTextAndRetryReloads', async () => {
    await setup();
    backend.expectOne(LIST).flush(ENVELOPE('forbidden'), { status: 404, statusText: 'x' });
    await settle();
    expect(root().textContent).toContain('You do not have permission to do that.');
    (byLabel('Try again') as HTMLButtonElement).click();
    await settle();
    backend.expectOne(LIST).flush(page([]));
    await settle();
    expect(root().textContent).toContain('No folders here');
  });

  it('moveHereIsOffWhileTheListingLoadsAndAfterItFails', async () => {
    await setup();
    expect(moveHere().disabled).toBe(true);
    backend.expectOne(LIST).flush(ENVELOPE('folder_not_found'), { status: 404, statusText: 'x' });
    await settle();
    expect(moveHere().disabled).toBe(true);
  });

  it('theCurrentCrumbIsMarkedAndNavigatingTellsTheParent', async () => {
    await setup({ ...FILE, folder_id: null });
    const navigated = vi.fn();
    fixture.componentInstance.navigated.subscribe(navigated);
    backend.expectOne(LIST).flush(page([folder('f1')]));
    await settle();
    expect(byLabel('All files')?.getAttribute('aria-current')).toBe('location');
    (byLabel('Open folder Folder f1') as HTMLButtonElement).click();
    await settle();
    backend.expectOne(LIST).flush(page([]));
    await settle();
    expect(navigated).toHaveBeenCalledTimes(1);
    expect(byLabel('All files')?.getAttribute('aria-current')).toBeNull();
    expect(byLabel('Folder f1')?.getAttribute('aria-current')).toBe('location');
  });

  it('nextPage_asksTheServerForPageTwo', async () => {
    await setup({ ...FILE, folder_id: null });
    const navigated = vi.fn();
    fixture.componentInstance.navigated.subscribe(navigated);
    backend.expectOne(LIST).flush({ ...page([folder('f1')], 40), page: 1 });
    await settle();
    const next = [...root().querySelectorAll('cd-pager button')].find((b) =>
      /next/i.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    next.click();
    await settle();
    expect(backend.expectOne(LIST).request.params.get('page')).toBe('2');
    expect(navigated).toHaveBeenCalled();
    expect(root().querySelector('[role="status"]')?.textContent).toContain('Loading folders');
  });

  it('whileBusyEveryChoiceIsOff', async () => {
    await setup();
    backend.expectOne(LIST).flush(page([folder('f1')]));
    fixture.componentRef.setInput('busy', true);
    await settle();
    expect((byLabel('Open folder Folder f1') as HTMLButtonElement).disabled).toBe(true);
    expect((byLabel('Cancel') as HTMLButtonElement).disabled).toBe(true);
  });
});
